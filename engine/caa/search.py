from __future__ import annotations

import re
import time
from datetime import datetime

from . import timeq
from .db import Database
from .embed import Embedder
from .nemotron import TokenFactory
from .textembed import SemanticIndex
from .vectors import VectorIndex

STOP = {"a", "an", "the", "of", "for", "with", "in", "on", "at", "to", "and", "or", "some", "me", "my", "i", "need",
        "want", "find", "show", "get", "give", "looking", "please", "something", "like", "that", "this", "is", "are",
        "from", "into", "by", "it", "be", "any"}

AUDIO_WORDS = {"sfx", "sound", "sounds", "whoosh", "swoosh", "swish", "boom", "impact", "riser", "hit", "click", "pop",
               "glitch", "braam", "stinger", "ding", "transition", "foley", "ambience", "ambient", "noise", "drone",
               "audio", "voiceover", "vo", "beep", "thud", "slam", "punch", "punchy", "rumble", "sweep"}
MUSIC_WORDS = {"music", "song", "track", "beat", "bgm", "loop", "melody", "instrumental", "lofi", "lo-fi", "piano",
               "guitar", "orchestral", "cinematic score", "jingle"}
IMAGE_WORDS = {"photo", "photos", "image", "images", "picture", "pictures", "still", "stills", "png", "jpg", "jpeg"}
VIDEO_WORDS = {"clip", "clips", "footage", "video", "videos", "b-roll", "broll", "shot", "shots", "timelapse", "drone shot"}
TEMPLATE_WORDS = {"template", "templates", "mogrt", "lower third", "lower thirds", "title card", "titles", "lut", "luts", "preset"}

SYNONYMS = {
    "whoosh": ["swoosh", "swish", "transition", "sweep"],
    "punchy": ["hit", "impact", "short"],
    "rain": ["rainy", "raining", "storm", "wet"],
    "running": ["run", "runner", "jogging", "sprint"],
    "fire": ["flame", "flames", "burning", "blaze"],
    "city": ["urban", "street", "downtown"],
    "sunset": ["golden hour", "dusk", "evening"],
    "drone": ["aerial"],
    "aerial": ["drone"],
    "night": ["dark", "evening"],
    "happy": ["upbeat", "cheerful"],
    "sad": ["melancholic", "emotional"],
}


def local_plan(q: str) -> dict:
    ql = q.lower()
    words = re.findall(r"[a-z0-9\-:]+", ql)
    plan = {"visual": q, "keywords": [], "kind": "any", "audio_kind": None, "max_duration": None,
            "min_duration": None, "orientation": None, "green_screen": None, "source": "local"}
    ws = set(words)
    if re.search(r"green ?screen|chroma|keyable", ql):
        plan["green_screen"] = True
    if ws & {"vertical", "portrait", "9:16", "tiktok", "reels", "shorts"}:
        plan["orientation"] = "portrait"
    elif ws & {"horizontal", "landscape", "16:9", "widescreen"}:
        plan["orientation"] = "landscape"
    if ws & MUSIC_WORDS or "cinematic score" in ql:
        plan["kind"], plan["audio_kind"] = "audio", "music"
    elif ws & AUDIO_WORDS and not ws & VIDEO_WORDS:
        plan["kind"], plan["audio_kind"] = "audio", "sfx"
    elif ws & TEMPLATE_WORDS or "lower third" in ql or "title card" in ql:
        plan["kind"] = "template"
    elif ws & IMAGE_WORDS:
        plan["kind"] = "image"
    elif ws & VIDEO_WORDS:
        plan["kind"] = "video"
    m = re.search(r"(?:under|less than|shorter than|max|<)\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds|second|m|min|minutes)?", ql)
    if m:
        val = float(m.group(1)) * (60 if (m.group(2) or "").startswith("m") else 1)
        plan["max_duration"] = val
    elif ws & {"short", "quick"} and plan["kind"] == "audio":
        plan["max_duration"] = 3.0 if plan["audio_kind"] == "sfx" else 30.0
    m = re.search(r"(?:over|longer than|more than|at least|>)\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds|m|min|minutes)?", ql)
    if m:
        plan["min_duration"] = float(m.group(1)) * (60 if (m.group(2) or "").startswith("m") else 1)
    kws = [w for w in words if w not in STOP and len(w) > 1 and not w.isdigit()]
    extra = []
    for w in kws:
        extra += SYNONYMS.get(w, [])
    plan["keywords"] = list(dict.fromkeys(kws + extra))
    if plan["kind"] == "audio":
        plan["visual"] = ""
    return plan


def fts_query(terms: list[str]) -> str:
    toks = []
    for t in terms:
        for w in re.findall(r"[a-z0-9]+", t.lower()):
            if w in STOP or len(w) < 2:
                continue
            toks.append(w)
    toks = list(dict.fromkeys(toks))[:24]
    if not toks:
        return ""
    return " OR ".join(f'"{w}"*' if len(w) >= 4 else f'"{w}"' for w in toks)


def when_phrase(label: str) -> str:
    head = label.split(",")[0].strip()
    if re.match(r"(\d{1,2} [A-Z][a-z]{2} \d{4}|(Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day )", head):
        return "on " + label
    if re.fullmatch(r"([A-Z][a-z]+ )?\d{4}", head):
        return "in " + label
    return label


def _fmt_tc(t: float | None) -> str:
    if t is None:
        return ""
    t = max(0.0, float(t))
    m, s = divmod(int(round(t)), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


class SearchEngine:
    def __init__(self, db: Database, embedder: Embedder, vindex: VectorIndex, tf: TokenFactory,
                 semantic: SemanticIndex | None = None):
        self.db = db
        self.embedder = embedder
        self.vindex = vindex
        self.tf = tf
        self.semantic = semantic
        self.last_plan: dict | None = None
        self.date_order = timeq.system_date_order()

    @property
    def meaning_ready(self) -> bool:
        return bool(self.semantic is not None and self.semantic.ready and len(self.semantic))

    def wants_llm(self, use_llm: bool) -> bool:
        if not use_llm or not self.tf.available:
            return False
        return bool(getattr(self.tf.settings, "nemotron_search", False)) or not self.meaning_ready

    def plan(self, q: str, use_llm: bool = True) -> dict:
        base = local_plan(q)
        if self.wants_llm(use_llm):
            cached_key = "plan:" + self.tf.model("fast") + ":" + q.strip().lower()
            hit = self.db.cache_get(cached_key)
            llm = hit if hit is not None else self.tf.rewrite_query(q)
            if llm:
                if hit is None:
                    self.db.cache_put(cached_key, llm)
                merged = dict(base)
                if llm.get("visual") and base["kind"] != "audio":
                    merged["visual"] = llm["visual"]
                merged["keywords"] = list(dict.fromkeys((llm.get("keywords") or []) + base["keywords"]))
                merged["soft"] = {k: llm[k] for k in ("kind", "audio_kind", "max_duration", "min_duration", "orientation", "green_screen")
                                  if llm.get(k) not in (None, "", "any")}
                merged["source"] = "nemotron"
                return merged
        return base

    def _passes(self, a: dict, plan: dict, kinds: set[str] | None) -> bool:
        if kinds and a["kind"] not in kinds:
            return False
        if a["status"] != "indexed":
            return False
        if plan.get("green_screen") and not a["green_screen"]:
            return False
        dur = a.get("duration")
        if plan.get("max_duration") and dur and dur > plan["max_duration"] * 1.25 and a["kind"] in ("audio", "video"):
            return False
        if plan.get("min_duration") and dur is not None and a["kind"] in ("audio", "video") and dur < plan["min_duration"] * 0.8:
            return False
        o = plan.get("orientation")
        if o and a.get("width") and a.get("height") and a["kind"] in ("video", "image"):
            r = a["width"] / a["height"]
            if o == "portrait" and r >= 0.95:
                return False
            if o == "landscape" and r <= 1.05:
                return False
        return True

    @staticmethod
    def _soft_factor(a: dict, soft: dict) -> float:
        if not soft:
            return 1.0
        f = 1.0
        if soft.get("kind") and a["kind"] == soft["kind"]:
            f *= 1.08
        dur = a.get("duration")
        if dur and a["kind"] in ("audio", "video"):
            if soft.get("max_duration") and dur <= soft["max_duration"] * 1.25:
                f *= 1.04
            if soft.get("min_duration") and dur >= soft["min_duration"] * 0.8:
                f *= 1.04
        o = soft.get("orientation")
        if o and a.get("width") and a.get("height"):
            r = a["width"] / a["height"]
            if (o == "portrait" and r < 0.95) or (o == "landscape" and r > 1.05) or (o == "square" and 0.95 <= r <= 1.05):
                f *= 1.04
        if soft.get("green_screen") and a.get("green_screen"):
            f *= 1.1
        return f

    def _memory(self) -> dict[int, float]:
        stats = self.db.feedback_stats()
        now = time.time()
        factor: dict[int, float] = {}
        for aid, s in stats.items():
            f = 1.0 + 0.03 * min(s.get("like", 0), 5) + 0.04 * min(s.get("use", 0), 5) \
                - 0.2 * min(s.get("dismiss", 0), 3) - 0.35 * min(s.get("reject", 0), 2)
            last_use = s.get("last_use")
            if last_use and now - last_use < 900:
                f *= 0.9
            factor[aid] = max(0.4, min(1.15, f))
        return factor

    def _match_when(self, when: dict) -> dict[int, tuple[float, float | None]]:
        sql = "SELECT id, captured_at, duration FROM assets WHERE status='indexed' AND captured_at IS NOT NULL"
        params: list = []
        if when.get("start") is not None:
            sql += " AND captured_at < ? AND captured_at + COALESCE(duration, 0) >= ?"
            params += [when["end"], when["start"]]
        matched: dict[int, tuple[float, float | None]] = {}
        for r in self.db.query(sql, params):
            ok, gap, offset = timeq.match(r["captured_at"], r["duration"], when)
            if ok:
                matched[int(r["id"])] = (gap, offset)
        return matched

    def search(self, q: str, kind: str | None = None, limit: int = 40, use_llm: bool = True,
               green_screen: bool | None = None) -> dict:
        t0 = time.time()
        q = (q or "").strip()
        when = timeq.parse_when(q, self.date_order) if q else None
        if not when:
            return self._search(q, kind, limit, use_llm, green_screen)
        matched = self._match_when(when)
        alt = when.get("alt")
        if alt:
            alt_when = {**when, "start": alt["start"], "end": alt["end"], "label": alt["label"], "alt": None}
            alt_matched = self._match_when(alt_when)
            if not matched and alt_matched:
                alt_when["note"] = f"Read {alt['text']} as {alt['date_label']}, because nothing was recorded on {when['date_label']}"
                when, matched = alt_when, alt_matched
            elif alt_matched:
                when["alt_hits"] = len(alt_matched)
        rest = when.get("rest") or ""
        rest_plan = local_plan(rest)
        if matched and rest_plan["keywords"]:
            res = self._search(rest, kind, limit, use_llm, green_screen, allowed=set(matched))
            if res["results"]:
                for item in res["results"]:
                    gap, offset = matched.get(item["asset_id"], (0.0, None))
                    th = self._time_hit(item["asset_id"], offset)
                    if th:
                        item["hits"] = [th] + [h for h in item["hits"] if h["segment_id"] != th["segment_id"]][:3]
                        self._label_hits(item)
                        item["thumb"] = item["hits"][0]["thumb"] or item["thumb"]
                res["plan"]["when"] = when
                res["took_ms"] = int((time.time() - t0) * 1000)
                res["query"] = q
                return res
        if matched and not rest_plan["keywords"]:
            plan = rest_plan
            if green_screen is not None:
                plan["green_screen"] = green_screen
            kinds = {kind} if kind and kind != "all" else ({plan["kind"]} if plan.get("kind") not in (None, "any") else None)
            assets = self.db.assets(matched.keys())
            rows = [a for a in assets.values() if self._passes(a, plan, kinds)]
            rows.sort(key=lambda a: (matched[a["id"]][0], -(a.get("captured_at") or 0)))
            if rows:
                results = []
                for a in rows[:limit]:
                    gap, offset = matched[a["id"]]
                    th = self._time_hit(a["id"], offset)
                    results.append(self._result(a, [th] if th else [], 1.0 / (1.0 + gap / 60.0)))
                plan["when"] = when
                plan["source"] = "time"
                return {"query": q, "plan": plan, "results": results, "took_ms": int((time.time() - t0) * 1000),
                        "channels": {"time": len(matched)}}
        return self._when_fallback(q, when, bool(matched), kind, limit, use_llm, green_screen, t0)

    def _when_fallback(self, q: str, when: dict, had_dates: bool, kind: str | None, limit: int, use_llm: bool,
                       green_screen: bool | None, t0: float) -> dict:
        rest = when.get("rest") or ""
        rest_plan = local_plan(rest)
        if rest_plan["keywords"]:
            res = self._search(rest, kind, limit, use_llm, green_screen)
            what = f"“{rest}”"
            lead = f"Nothing matching {what} was recorded {when_phrase(when['label'])}" if had_dates else f"Nothing was recorded {when_phrase(when['label'])}"
            when = {**when, "note": f"{lead}, so these are the best matches for {what} from any date"}
            res["plan"]["when"] = when
            res["fallback"] = "any_date"
            res["query"] = q
            res["took_ms"] = int((time.time() - t0) * 1000)
            return res
        plan = rest_plan
        if green_screen is not None:
            plan["green_screen"] = green_screen
        kinds = {kind} if kind and kind != "all" else ({plan["kind"]} if plan.get("kind") not in (None, "any") else None)
        start, end, point, tod = when.get("start"), when.get("end"), when.get("point"), when.get("tod")
        day = 86400.0

        def distance(a: dict) -> float:
            t0a = float(a["captured_at"])
            t1a = t0a + float(a.get("duration") or 0.0)
            if start is not None:
                target = start + (point if point is not None else ((tod[0] + tod[1]) / 2 if tod else (end - start) / 2))
                return max(0.0, t0a - target, target - t1a)
            sod = (t0a - datetime.combine(datetime.fromtimestamp(t0a).date(), datetime.min.time()).timestamp()) % day
            target = point if point is not None else (tod[0] + tod[1]) / 2
            diff = abs(sod - target) % day
            return min(diff, day - diff)

        rows = [a for a in self.db.assets([r["id"] for r in self.db.query(
            "SELECT id FROM assets WHERE status='indexed' AND captured_at IS NOT NULL")]).values() if self._passes(a, plan, kinds)]
        rows.sort(key=distance)
        results = []
        for a in rows[:limit]:
            th = self._time_hit(a["id"], None)
            if th:
                th["why"] = ["nearest time"]
            results.append(self._result(a, [th] if th else [], 1.0 / (1.0 + distance(a) / 3600.0)))
        plan["when"] = {**when, "note": f"Nothing was recorded {when_phrase(when['label'])}. These are the closest recordings in time"}
        plan["source"] = "time"
        return {"query": q, "plan": plan, "results": results, "took_ms": int((time.time() - t0) * 1000),
                "channels": {"time": 0}, "fallback": "nearest"}

    def _time_hit(self, asset_id: int, offset: float | None) -> dict | None:
        segs = self.db.segments_for(asset_id)
        if not segs:
            return None
        seg = segs[0]
        if offset is not None:
            for sg in segs:
                if sg["start"] <= offset < (sg["end"] or 0) or sg is segs[-1]:
                    seg = sg
                    break
        start = offset if offset is not None and seg["end"] else seg["start"]
        return {"segment_id": seg["id"], "start": start, "end": seg["end"], "score": 1.0, "caption": seg.get("caption"),
                "thumb": f"/api/thumb/{seg['id']}" if seg.get("thumb") else None, "why": ["time"], "jump": offset is not None}

    def _search(self, q: str, kind: str | None = None, limit: int = 40, use_llm: bool = True,
                green_screen: bool | None = None, allowed: set[int] | None = None) -> dict:
        t0 = time.time()
        q = (q or "").strip()
        plan = self.plan(q, use_llm=use_llm) if q else local_plan("")
        if green_screen is not None:
            plan["green_screen"] = green_screen
        kinds = {kind} if kind and kind != "all" else ({plan["kind"]} if plan.get("kind") not in (None, "any") else None)
        if plan.get("kind") == "audio" and kind in (None, "all"):
            kinds = {"audio", "video"} if plan.get("audio_kind") == "ambience" else {"audio"}
        ranked: dict[int, float] = {}
        why: dict[int, set] = {}
        seg_allowed = None
        if allowed is not None:
            ids = list(allowed)
            seg_allowed = {int(r["id"]) for i in range(0, len(ids), 500)
                           for r in self.db.query(f"SELECT id FROM segments WHERE asset_id IN ({','.join('?' * len(ids[i:i + 500]))})", ids[i:i + 500])}
        fts_hits: list[tuple[int, float]] = []
        for terms, weight in (([q], 1.0), (plan.get("keywords") or [], 0.6)):
            match = fts_query(terms)
            hits = self.db.fts_search(match, 300) if match else []
            fts_hits += hits
            best_bm25 = hits[0][1] if hits else -1.0
            for rank, (sid, bm) in enumerate(hits):
                ratio = (bm / best_bm25) if best_bm25 < 0 else 1.0
                ranked[sid] = ranked.get(sid, 0.0) + weight * (0.4 + 0.6 * max(0.0, min(1.0, ratio))) / (60 + rank)
                why.setdefault(sid, set()).add("text")
        vec_hits: list[tuple[int, float]] = []
        visual_text = plan.get("visual") or ""
        if visual_text and self.embedder.supports_text and len(self.vindex) and (not kinds or kinds & {"video", "image", "template"}):
            qv = self.embedder.embed_texts([visual_text])[0]
            vec_hits = self.vindex.search(qv, 300, seg_allowed)
            if vec_hits:
                top = vec_hits[0][1]
                for rank, (sid, score) in enumerate(vec_hits):
                    if score < top - 0.12:
                        break
                    ratio = 1.0 - (top - score) / 0.12
                    ranked[sid] = ranked.get(sid, 0.0) + 1.2 * (0.4 + 0.6 * ratio) / (60 + rank)
                    why.setdefault(sid, set()).add("visual")
        sem_hits: list[tuple[int, float]] = []
        if q and self.meaning_ready:
            sem_hits = self.semantic.search(q, 300, seg_allowed)
            if sem_hits:
                top = sem_hits[0][1]
                span = max(1e-6, top - sem_hits[-1][1])
                for rank, (sid, score) in enumerate(sem_hits):
                    ratio = 1.0 - (top - score) / span if len(sem_hits) > 1 else 1.0
                    ranked[sid] = ranked.get(sid, 0.0) + 1.3 * (0.4 + 0.6 * ratio) / (60 + rank)
                    why.setdefault(sid, set()).add("meaning")
        if not q:
            return {"query": q, "plan": plan, "results": [], "took_ms": 0}
        segs = self.db.segments(ranked.keys())
        assets = self.db.assets({s["asset_id"] for s in segs.values()})
        memory = self._memory()
        best: dict[int, dict] = {}
        for sid, score in ranked.items():
            s = segs.get(sid)
            if not s:
                continue
            a = assets.get(s["asset_id"])
            if not a or not self._passes(a, plan, kinds) or (allowed is not None and a["id"] not in allowed):
                continue
            if plan.get("green_screen") and a["kind"] == "video" and s["green_ratio"] < 0.15 and "chroma key" not in (s.get("tags") or []):
                score *= 0.6
            score *= memory.get(a["id"], 1.0) * self._soft_factor(a, plan.get("soft") or {})
            entry = best.get(a["id"])
            hit = {"segment_id": sid, "start": s["start"], "end": s["end"], "score": score, "caption": s.get("caption"),
                   "thumb": f"/api/thumb/{sid}" if s.get("thumb") else None, "why": sorted(why.get(sid, []))}
            if entry is None:
                best[a["id"]] = {"asset": a, "hits": [hit], "score": score}
            else:
                entry["hits"].append(hit)
                entry["score"] = max(entry["score"], score) + 0.15 * min(score, entry["score"]) / max(1, len(entry["hits"]))
        results = []
        for aid, e in sorted(best.items(), key=lambda kv: -kv[1]["score"])[:limit]:
            hits = sorted(e["hits"], key=lambda h: -h["score"])[:4]
            results.append(self._result(e["asset"], hits, e["score"]))
        self.last_plan = plan
        return {"query": q, "plan": plan, "results": results, "took_ms": int((time.time() - t0) * 1000),
                "channels": {"text": len({h[0] for h in fts_hits}), "visual": len(vec_hits), "meaning": len(sem_hits)}}

    def similar(self, segment_id: int, limit: int = 30) -> dict:
        seg = self.db.segment(segment_id)
        if not seg:
            return {"results": []}
        fused: dict[int, float] = {}
        why: dict[int, set] = {}
        v = self.vindex.get(segment_id)
        channels = []
        if v is not None:
            channels.append(("look", self.vindex.search(v, limit * 6), 1.0))
        if self.meaning_ready:
            channels.append(("meaning", self.semantic.near(segment_id, limit * 6), 1.0))
        for name, hits, weight in channels:
            for rank, (sid, _score) in enumerate(hits):
                fused[sid] = fused.get(sid, 0.0) + weight / (60 + rank)
                why.setdefault(sid, set()).add(name)
        segs = self.db.segments(fused.keys())
        assets = self.db.assets({s["asset_id"] for s in segs.values()})
        seen, results = set(), []
        for sid, score in sorted(fused.items(), key=lambda kv: -kv[1]):
            s = segs.get(sid)
            if not s or s["asset_id"] == seg["asset_id"] or s["asset_id"] in seen:
                continue
            a = assets.get(s["asset_id"])
            if not a or a["status"] != "indexed":
                continue
            seen.add(a["id"])
            results.append(self._result(a, [{"segment_id": sid, "start": s["start"], "end": s["end"], "score": score,
                                             "caption": s.get("caption"), "thumb": f"/api/thumb/{sid}" if s.get("thumb") else None,
                                             "why": sorted(why.get(sid, []))}], score))
            if len(results) >= limit:
                break
        return {"results": results, "channels": [c[0] for c in channels]}

    @staticmethod
    def _label_hits(item: dict) -> None:
        for h in item["hits"]:
            h["tc"] = _fmt_tc(h["start"]) + ("–" + _fmt_tc(h["end"]) if item["kind"] == "video" and h["end"] else "")

    @staticmethod
    def _result(a: dict, hits: list[dict], score: float) -> dict:
        for h in hits:
            h["tc"] = _fmt_tc(h["start"]) + ("–" + _fmt_tc(h["end"]) if a["kind"] == "video" and h["end"] else "")
        return {
            "asset_id": a["id"], "name": a["name"], "kind": a["kind"], "path": a["path"], "duration": a.get("duration"),
            "width": a.get("width"), "height": a.get("height"), "caption": a.get("caption"), "tags": (a.get("tags") or [])[:12],
            "green_screen": bool(a.get("green_screen")), "has_alpha": bool(a.get("has_alpha")),
            "license": a.get("license"), "source_url": a.get("source_url"),
            "captured_at": a.get("captured_at"), "captured_src": a.get("captured_src"), "device": a.get("device"),
            "lat": a.get("lat"), "lon": a.get("lon"),
            "score": round(score, 5), "hits": hits, "thumb": hits[0]["thumb"] if hits else None,
            "media_url": f"/api/media/{a['id']}",
        }


def result_for_asset(db: Database, a: dict) -> dict:
    segs = db.segments_for(a["id"])
    hits = [{"segment_id": s["id"], "start": s["start"], "end": s["end"], "score": 0.0, "caption": s.get("caption"),
             "thumb": f"/api/thumb/{s['id']}" if s.get("thumb") else None, "why": []} for s in segs[:1]]
    return SearchEngine._result(a, hits, 0.0)
