from __future__ import annotations

import logging
import re
import time

from .nemotron import TokenFactoryError, extract_json
from .tavily import TavilyError

log = logging.getLogger("caa.broll")

KINDS = ("video", "image", "audio")
ROLES = ("reasoning", "agent", "fast")

PLAN_PROMPT = """You plan b-roll for a short video by a solo creator.
Topic: {topic}
Target length: about {seconds} seconds.
{script_block}
Research notes from the web (numbered sources):
{notes}

Return one JSON object with keys:
title: a working title for the video
hook: the first line the creator says, under 20 words
beats: a list of {n_min} to {n_max} beats in order. Each beat has:
  line: what the creator says in this beat (use the script's own words when a script is given)
  shot: the b-roll shot to show, concrete and filmable, for example "close-up of hands pouring coffee"
  search: 3 to 8 plain words to find this shot in a footage library, no punctuation
  kind: "video", "image" or "audio" (audio only for music or a sound effect)
  seconds: how long the beat lasts
  why: a few words on why this shot fits
facts: up to 5 facts worth saying on screen, each {{"fact": "...", "source": n}} where n is the source number. Use only facts from the research notes.
Write plainly. Do not invent statistics."""


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 3]


def _keywords(text: str, n: int = 6) -> str:
    stop = {"the", "a", "an", "and", "or", "but", "of", "to", "in", "on", "for", "with", "is", "are", "was", "were", "it", "this",
            "that", "you", "your", "we", "our", "i", "my", "be", "as", "at", "by", "from", "so", "if", "about", "into", "how", "what",
            "why", "when", "can", "will", "just", "do", "does", "not", "they", "their", "there", "here", "have", "has", "more"}
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z'-]+", text.lower()) if w not in stop and len(w) > 2]
    return " ".join(list(dict.fromkeys(words))[:n])


def clean_beats(raw: list, seconds: int) -> list[dict]:
    beats = []
    for b in raw or []:
        if not isinstance(b, dict):
            continue
        shot = str(b.get("shot") or "").strip()
        line = str(b.get("line") or "").strip()
        search = re.sub(r"[^\w\s'-]", " ", str(b.get("search") or "")).strip() or _keywords(shot or line)
        if not (shot or line) or not search:
            continue
        kind = str(b.get("kind") or "video").lower()
        try:
            secs = float(b.get("seconds") or 0)
        except (TypeError, ValueError):
            secs = 0.0
        beats.append({"line": line[:400], "shot": shot[:200], "search": " ".join(search.split())[:80],
                      "kind": kind if kind in KINDS else "video", "seconds": round(min(max(secs, 1.0), 60.0), 1) if secs else None,
                      "why": str(b.get("why") or "").strip()[:160]})
    if beats and not any(b["seconds"] for b in beats):
        each = round(seconds / len(beats), 1)
        for b in beats:
            b["seconds"] = each
    return beats[:16]


class BrollPlanner:
    def __init__(self, tavily, tf, search):
        self.tavily = tavily
        self.tf = tf
        self.search = search

    def research(self, topic: str) -> tuple[list[dict], str]:
        if not self.tavily.available:
            return [], ""
        data = self.tavily.search(topic, max_results=6, include_answer="basic", search_depth="basic")
        sources = [{"n": i + 1, "title": str(r.get("title") or r.get("url"))[:140], "url": str(r.get("url") or ""),
                    "snippet": str(r.get("content") or "")[:500]} for i, r in enumerate(data.get("results") or [])]
        return sources, str(data.get("answer") or "")

    def _ask(self, prompt: str) -> tuple[dict | None, str | None]:
        if self.tf is None or not self.tf.available:
            return None, None
        for role in ROLES:
            try:
                raw = self.tf.chat(role, [{"role": "system", "content": "You are a video producer. Reply with one JSON object only."},
                                          {"role": "user", "content": prompt}], max_tokens=2200, temperature=0.3, budget=120)
            except TokenFactoryError as exc:
                log.warning("B-roll plan with %s failed: %s", role, exc)
                continue
            got = extract_json(raw)
            if got and got.get("beats"):
                return got, self.tf.model(role)
        return None, None

    def _fallback(self, topic: str, script: str, answer: str, seconds: int) -> dict:
        lines = _sentences(script) or _sentences(answer)[:6] or [topic]
        lines = lines[:12]
        beats = [{"line": ln, "shot": "", "search": _keywords(ln) or _keywords(topic), "kind": "video", "seconds": None, "why": ""}
                 for ln in lines]
        return {"title": topic, "hook": lines[0] if lines else topic, "beats": clean_beats(beats, seconds) or beats, "facts": []}

    def _match(self, beat: dict) -> list[dict]:
        kind = beat["kind"] if beat["kind"] == "audio" else None
        res = self.search.search(beat["search"], kind=kind, limit=3, use_llm=False)
        out = []
        for r in (res.get("results") or [])[:3]:
            hit = (r.get("hits") or [{}])[0]
            out.append({"asset_id": r["asset_id"], "name": r["name"], "kind": r["kind"], "thumb": r.get("thumb"), "segment_id": hit.get("segment_id"),
                        "start": hit.get("start"), "end": hit.get("end"), "tc": hit.get("tc"), "caption": hit.get("caption") or r.get("caption"),
                        "score": r.get("score"), "license": r.get("license")})
        return out

    def plan(self, topic: str, script: str = "", seconds: int = 60, research: bool = True) -> dict:
        t0 = time.time()
        topic = (topic or "").strip()
        script = (script or "").strip()
        if not topic and not script:
            raise ValueError("Give a topic or a script")
        topic = topic or _sentences(script)[0][:120]
        seconds = max(15, min(int(seconds or 60), 1200))
        sources, answer, research_error = [], "", None
        if research:
            try:
                sources, answer = self.research(topic)
            except TavilyError as exc:
                research_error = str(exc)
        notes = ""
        if answer:
            notes += f"Summary: {answer}\n"
        notes += "\n".join(f"[{s['n']}] {s['title']} ({s['url']}): {s['snippet']}" for s in sources) or "(no web research)"
        n_beats = max(3, min(12, round(seconds / 6)))
        prompt = PLAN_PROMPT.format(topic=topic, seconds=seconds, notes=notes[:9000], n_min=max(3, n_beats - 2), n_max=n_beats + 2,
                                    script_block=f"Script:\n{script[:6000]}\n" if script else "No script yet; write the lines too.")
        got, model = self._ask(prompt)
        if got:
            plan = {"title": str(got.get("title") or topic)[:140], "hook": str(got.get("hook") or "")[:240],
                    "beats": clean_beats(got.get("beats"), seconds), "facts": []}
            for f in got.get("facts") or []:
                if isinstance(f, dict) and str(f.get("fact") or "").strip():
                    try:
                        n = int(f.get("source"))
                    except (TypeError, ValueError):
                        n = None
                    src = next((s for s in sources if s["n"] == n), None)
                    plan["facts"].append({"fact": str(f["fact"]).strip()[:300], "source": src})
            plan["facts"] = plan["facts"][:5]
        else:
            plan = self._fallback(topic, script, answer, seconds)
        if not plan["beats"]:
            plan = self._fallback(topic, script, answer, seconds)
        covered = 0
        for b in plan["beats"]:
            b["matches"] = self._match(b)
            b["gap"] = not b["matches"]
            covered += 0 if b["gap"] else 1
        return {"topic": topic, "seconds": seconds, **plan, "sources": sources, "answer": answer, "model": model,
                "researched": bool(sources), "research_error": research_error,
                "covered": covered, "gaps": len(plan["beats"]) - covered, "took_ms": int((time.time() - t0) * 1000)}
