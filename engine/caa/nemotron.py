from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import threading
import time
from typing import Any

import requests
from PIL import Image

from .config import MODEL_HINTS, Settings
from .media import to_rgb

log = logging.getLogger("caa.nemotron")

CAPTION_SYSTEM = "You label footage, images and design templates for a video editor's private asset library. Reply with one JSON object only, no prose."

VIDEO_PROMPT = """These {n} frames come from one shot ({start:.1f}s to {end:.1f}s) of the file "{name}".
Describe what a video editor would search for. Return JSON with keys:
description: one concrete sentence, no guessing about things not visible
subjects: list
setting: short phrase
actions: list
shot_type: one of extreme wide, wide, medium, close-up, extreme close-up, aerial, top-down, insert, unknown
camera_motion: one of static, pan, tilt, zoom, handheld, tracking, unknown
mood: list of 1-3 words
colors: list of dominant colours
on_screen_text: visible text or ""
background: one of normal, green screen, blue screen, transparent, solid color
tags: 8-15 short search keywords including synonyms"""

IMAGE_PROMPT = """This is the {what} "{name}".
Describe what a video editor would search for. Return JSON with keys:
description: one concrete sentence
subjects: list
setting: short phrase
shot_type: one of extreme wide, wide, medium, close-up, extreme close-up, aerial, top-down, graphic, unknown
mood: list of 1-3 words
colors: list of dominant colours
on_screen_text: visible text or ""
background: one of normal, green screen, blue screen, transparent, solid color
tags: 8-15 short search keywords including synonyms"""

AUDIO_PROMPT = """This is a {dur:.1f}s excerpt of the audio file "{name}" (full length {full:.1f}s).
Local analysis: {feat}.
Return JSON with keys:
kind: one of sfx, music, speech, ambience, mixed
description: one concrete sentence
mood: list of 1-3 words
energy: one of low, medium, high
instruments: list (music only, else [])
tags: 8-15 search keywords, use editor terms where they fit (whoosh, swoosh, riser, impact, hit, glitch, pop, click, braam, stinger, drone, bed, loop)
good_for: list of edit uses (transition, intro, outro, jump cut, b-roll bed, reveal, title, montage)"""

AUDIO_META_PROMPT = """You cannot hear this file. Describe it for a video editor's search index using only the evidence below.
File name: "{name}"
Folder: "{folder}"
Length: {full:.1f}s
Measured features: {feat}
Tags from signal analysis: {tags}
Rules: trust the file and folder names when they name the sound; use the measurements for character (attack_ms small = punchy, flatness high = noisy/airy, centroid_hz high = bright, trend > 0 = rising, tempo_bpm present = rhythmic). Do not invent instruments, voices or scenes the evidence does not support.
Return JSON with keys:
kind: one of sfx, music, speech, ambience, mixed
description: one cautious sentence
mood: list of 1-3 words
energy: one of low, medium, high
instruments: list (only if the name says so, else [])
tags: 8-15 search keywords, use editor terms where they fit (whoosh, swoosh, riser, impact, hit, glitch, pop, click, braam, stinger, drone, bed, loop)
good_for: list of edit uses (transition, intro, outro, jump cut, b-roll bed, reveal, title, montage)"""

REWRITE_SYSTEM = "You turn a video editor's request into a search plan for their private asset library. Reply with one JSON object only."

REWRITE_PROMPT = """Request: "{q}"
Return JSON with keys:
visual: English description of what a matching frame or image shows, or "" if the request is only about sound
keywords: 6-12 search terms including synonyms and editor jargon
kind: video, image, audio or template only if the request explicitly names that media type (clip, footage, photo, sound, music, template...), otherwise any
audio_kind: one of sfx, music, speech, ambience, or null
max_duration: seconds if the request states a length limit, else null
min_duration: seconds if the request states a minimum length, else null
orientation: landscape, portrait or square only if the request says so, else null
green_screen: true only if the request asks for green screen or keyable footage, else null"""

THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def _b64_image(img: Image.Image, max_side: int) -> str:
    im = to_rgb(img).copy()
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = THINK_RE.sub("", text).strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                        return obj if isinstance(obj, dict) else None
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _strs(v: Any, lower: bool = False, limit: int = 20) -> list[str]:
    if isinstance(v, str):
        v = [p for p in re.split(r"[,;]", v) if p.strip()]
    if not isinstance(v, list):
        return []
    out = []
    for x in v:
        if isinstance(x, (str, int, float)) and str(x).strip():
            s = str(x).strip()
            out.append(s.lower() if lower else s)
    return list(dict.fromkeys(out))[:limit]


def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", "null") else None
    except (TypeError, ValueError):
        return None


def clean_caption(d: dict | None) -> dict | None:
    if not d:
        return None
    out = {
        "description": str(d.get("description") or "").strip(),
        "subjects": _strs(d.get("subjects")),
        "setting": str(d.get("setting") or "").strip(),
        "actions": _strs(d.get("actions")),
        "shot_type": str(d.get("shot_type") or "").strip().lower(),
        "camera_motion": str(d.get("camera_motion") or "").strip().lower(),
        "mood": _strs(d.get("mood"), lower=True, limit=5),
        "colors": _strs(d.get("colors"), lower=True, limit=6),
        "on_screen_text": str(d.get("on_screen_text") or "").strip(),
        "background": str(d.get("background") or "normal").strip().lower(),
        "tags": _strs(d.get("tags"), lower=True, limit=20),
    }
    return out if out["description"] or out["tags"] else None


def clean_audio(d: dict | None) -> dict | None:
    if not d:
        return None
    kind = str(d.get("kind") or "").strip().lower()
    out = {
        "kind": kind if kind in {"sfx", "music", "speech", "ambience", "mixed"} else "",
        "description": str(d.get("description") or "").strip(),
        "mood": _strs(d.get("mood"), lower=True, limit=5),
        "energy": str(d.get("energy") or "").strip().lower(),
        "instruments": _strs(d.get("instruments"), lower=True, limit=8),
        "tags": _strs(d.get("tags"), lower=True, limit=20),
        "good_for": _strs(d.get("good_for"), lower=True, limit=8),
    }
    return out if out["description"] or out["tags"] else None


def clean_plan(d: dict | None) -> dict | None:
    if not d:
        return None
    kind = str(d.get("kind") or "any").strip().lower()
    orient = str(d.get("orientation") or "").strip().lower()
    ak = str(d.get("audio_kind") or "").strip().lower()
    gs = d.get("green_screen")
    if isinstance(gs, str):
        gs = {"true": True, "false": False}.get(gs.lower())
    return {
        "visual": str(d.get("visual") or "").strip(),
        "keywords": _strs(d.get("keywords"), lower=True, limit=14),
        "kind": kind if kind in {"video", "image", "audio", "template"} else "any",
        "audio_kind": ak if ak in {"sfx", "music", "speech", "ambience"} else None,
        "max_duration": _num(d.get("max_duration")),
        "min_duration": _num(d.get("min_duration")),
        "orientation": orient if orient in {"landscape", "portrait", "square"} else None,
        "green_screen": gs if isinstance(gs, bool) else None,
    }


class TokenFactoryError(RuntimeError):
    pass


class TokenFactory:
    def __init__(self, settings: Settings, db=None, session: requests.Session | None = None):
        self.settings = settings
        self.db = db
        if session is None:
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=4, pool_maxsize=32)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        self.session = session
        self._lock = threading.Lock()
        self._compat: dict[str, dict] = {}
        self.stats = {"calls": 0, "errors": 0, "cached": 0, "last_error": None, "by_role": {}}

    @property
    def available(self) -> bool:
        return self.settings.cloud_enabled

    def model(self, role: str) -> str:
        return self.settings.models.get(role) or ""

    def _headers(self) -> dict:
        key = self.settings.nebius_api_key
        if not key:
            raise TokenFactoryError("NEBIUS_API_KEY is not set")
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _url(self, path: str) -> str:
        return self.settings.tokenfactory_base_url.rstrip("/") + path

    def list_models(self) -> list[str]:
        r = self.session.get(self._url("/models"), headers=self._headers(), timeout=30)
        if r.status_code != 200:
            raise TokenFactoryError(f"GET /models -> {r.status_code}: {r.text[:300]}")
        data = r.json()
        items = data.get("data", data if isinstance(data, list) else [])
        return sorted({m.get("id") for m in items if isinstance(m, dict) and m.get("id")})

    def resolve_models(self, available: list[str] | None = None, apply: bool = True) -> dict:
        ids = available if available is not None else self.list_models()
        lower = {i.lower(): i for i in ids}
        nvidia = [i for i in ids if "nemotron" in i.lower()]
        resolved = {}
        for role, hints in MODEL_HINTS.items():
            current = self.settings.models.get(role, "")
            if current.lower() in lower:
                resolved[role] = lower[current.lower()]
                continue
            pick = None
            for h in hints:
                cands = [i for i in nvidia if h in i.lower()]
                if role == "fast":
                    cands = [c for c in cands if "omni" not in c.lower() and "vl" not in c.lower()]
                if role == "agent":
                    cands = [c for c in cands if "vl" not in c.lower()]
                if cands:
                    pick = sorted(cands, key=len)[0]
                    break
            resolved[role] = pick or ("" if role == "omni" else current)
        if apply:
            self.settings.models.update(resolved)
            self.settings.save()
        return resolved

    def _cache_key(self, role: str, messages: list, extra: dict) -> str:
        def strip(o):
            if isinstance(o, dict):
                return {k: (hashlib.sha1(v.encode()).hexdigest() if isinstance(v, str) and len(v) > 2000 else strip(v)) for k, v in o.items()}
            if isinstance(o, list):
                return [strip(x) for x in o]
            return o
        raw = json.dumps({"m": self.model(role), "msgs": strip(messages), "x": extra}, sort_keys=True)
        return "tf:" + hashlib.sha1(raw.encode()).hexdigest()

    def chat(self, role: str, messages: list, max_tokens: int = 700, temperature: float = 0.2, json_mode: bool = True,
             use_cache: bool = True, budget: float | None = None) -> str:
        deadline = time.time() + budget if budget else None
        if not self.available:
            raise TokenFactoryError("Token Factory disabled (local mode or no API key)")
        model = self.model(role)
        key = self._cache_key(role, messages, {"t": temperature, "mt": max_tokens, "j": json_mode})
        if use_cache and self.db is not None:
            hit = self.db.cache_get(key)
            if hit is not None:
                self.stats["cached"] += 1
                return hit
        compat = self._compat.setdefault(model, {"json": json_mode, "no_think": True})
        attempts = [dict(compat)]
        if compat["json"] or compat["no_think"]:
            attempts.append({"json": False, "no_think": False})
        last_err = None
        for opt in attempts:
            payload: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
            if opt["json"] and json_mode:
                payload["response_format"] = {"type": "json_object"}
            if opt["no_think"]:
                payload["chat_template_kwargs"] = {"enable_thinking": False}
            if deadline and time.time() >= deadline:
                last_err = "0: time budget exceeded"
                break
            status, body = self._post(payload, deadline)
            if status == 200:
                text = (((body.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
                if isinstance(text, list):
                    text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
                with self._lock:
                    self.stats["calls"] += 1
                    self.stats["by_role"][role] = self.stats["by_role"].get(role, 0) + 1
                    self._compat[model] = {**self._compat.get(model, {}), **opt}
                if use_cache and self.db is not None and text:
                    self.db.cache_put(key, text)
                return text
            last_err = f"{status}: {body}"
            if status not in (400, 415, 422):
                break
        with self._lock:
            self.stats["errors"] += 1
            self.stats["last_error"] = f"{role}/{model}: {last_err}"
        raise TokenFactoryError(f"{role}/{model}: {last_err}")

    def _post(self, payload: dict, deadline: float | None = None) -> tuple[int, Any]:
        last: tuple[int, Any] = (0, "no response")
        for retry in range(4):
            timeout = self.settings.request_timeout
            if deadline:
                timeout = min(timeout, deadline - time.time())
                if timeout <= 0.5:
                    return (0, "time budget exceeded")
            try:
                r = self.session.post(self._url("/chat/completions"), headers=self._headers(), json=payload, timeout=timeout)
            except requests.RequestException as exc:
                last = (0, f"network error: {exc}")
                if deadline:
                    return last
                time.sleep(1.5 * (retry + 1))
                continue
            if r.status_code == 200:
                try:
                    return 200, r.json()
                except ValueError:
                    return 502, r.text[:300]
            last = (r.status_code, r.text[:300])
            if r.status_code in (429, 500, 502, 503, 504):
                if not deadline:
                    time.sleep(min(20, 1.5 * 2 ** retry))
                    continue
                if deadline - time.time() > 1.5:
                    time.sleep(0.3)
                    continue
            return last
        return last

    def chat_json(self, role: str, messages: list, **kw) -> dict | None:
        try:
            return extract_json(self.chat(role, messages, **kw))
        except TokenFactoryError as exc:
            log.warning("%s", exc)
            return None

    def caption_frames(self, images: list[Image.Image], name: str, start: float = 0.0, end: float = 0.0,
                       what: str | None = None) -> dict | None:
        imgs = [i for i in images if i is not None]
        if not imgs:
            return None
        size = self.settings.caption_image_size
        if what or (len(imgs) == 1 and end == 0):
            prompt = IMAGE_PROMPT.format(what=what or "image", name=name)
        else:
            prompt = VIDEO_PROMPT.format(n=len(imgs), start=start, end=end, name=name)
        content: list[dict] = [{"type": "text", "text": prompt}]
        content += [{"type": "image_url", "image_url": {"url": _b64_image(im, size)}} for im in imgs]
        messages = [{"role": "system", "content": CAPTION_SYSTEM}, {"role": "user", "content": content}]
        return clean_caption(self.chat_json("vision", messages, max_tokens=600))

    def audio_model_usable(self) -> bool:
        model = self.model("omni")
        return bool(model) and self._compat.get(model, {}).get("audio") is not False

    def describe_audio(self, wav: bytes, name: str, excerpt_s: float, full_s: float, feat: dict,
                       folder: str = "", local_tags: list[str] | None = None) -> dict | None:
        if self.audio_model_usable():
            model = self.model("omni")
            summary = ", ".join(f"{k}={v}" for k, v in feat.items() if v is not None)
            content = [
                {"type": "text", "text": AUDIO_PROMPT.format(dur=excerpt_s, full=full_s, name=name, feat=summary)},
                {"type": "input_audio", "input_audio": {"data": base64.b64encode(wav).decode(), "format": "wav"}},
            ]
            messages = [{"role": "system", "content": CAPTION_SYSTEM}, {"role": "user", "content": content}]
            try:
                out = clean_audio(extract_json(self.chat("omni", messages, max_tokens=500)))
                if out:
                    out["_model"] = model
                    out["_source"] = "audio"
                return out
            except TokenFactoryError as exc:
                msg = str(exc)
                if any(code in msg for code in (": 400", ": 404", ": 415", ": 422")):
                    self._compat.setdefault(model, {"json": True, "no_think": True})["audio"] = False
                    log.warning("Audio input rejected by %s; describing sounds from audio analysis with %s instead.",
                                model, self.model("fast"))
                else:
                    log.warning("%s", exc)
                    return None
        return self.describe_audio_from_analysis(name, full_s, feat, folder, local_tags or [])

    def describe_audio_from_analysis(self, name: str, full_s: float, feat: dict, folder: str = "",
                                     local_tags: list[str] | None = None) -> dict | None:
        summary = ", ".join(f"{k}={v}" for k, v in feat.items() if v is not None and k != "duration")
        prompt = AUDIO_META_PROMPT.format(name=name, folder=folder or "-", full=full_s, feat=summary,
                                          tags=", ".join(local_tags or []) or "-")
        messages = [{"role": "system", "content": CAPTION_SYSTEM}, {"role": "user", "content": prompt}]
        out = clean_audio(self.chat_json("fast", messages, max_tokens=400))
        if out:
            out["_model"] = self.model("fast")
            out["_source"] = "analysis"
        return out

    def rewrite_query(self, q: str) -> dict | None:
        messages = [{"role": "system", "content": REWRITE_SYSTEM}, {"role": "user", "content": REWRITE_PROMPT.format(q=q.replace('"', "'"))}]
        return clean_plan(self.chat_json("fast", messages, max_tokens=300, temperature=0.0, budget=self.settings.search_budget))

    def ping(self, role: str = "fast") -> str:
        return self.chat(role, [{"role": "user", "content": 'Reply with {"ok": true}'}], max_tokens=20, use_cache=False)
