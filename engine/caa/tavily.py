from __future__ import annotations

import hashlib
import json
import logging
import threading
from typing import Any

import requests

from .config import Settings

log = logging.getLogger("caa.tavily")

BASE_URL = "https://api.tavily.com"
DAY = 86400.0


class TavilyError(RuntimeError):
    pass


class Tavily:
    def __init__(self, settings: Settings, db=None, session: requests.Session | None = None):
        self.settings = settings
        self.db = db
        self.session = session or requests.Session()
        self._lock = threading.Lock()
        self.stats = {"calls": 0, "cached": 0, "errors": 0, "credits": 0, "last_error": None}

    @property
    def has_key(self) -> bool:
        return bool(self.settings.tavily_api_key)

    @property
    def available(self) -> bool:
        return self.has_key and self.settings.privacy_mode != "local"

    def why_off(self) -> str | None:
        if self.settings.privacy_mode == "local":
            return "Tavily is off in Local only mode, because it sends text to the web."
        if not self.has_key:
            return "Add a Tavily API key under Folders & privacy, Keys & connections."
        return None

    def _post(self, path: str, body: dict, timeout: float = 30.0) -> dict:
        key = self.settings.tavily_api_key
        if not key:
            raise TavilyError("TAVILY_API_KEY is not set")
        try:
            r = self.session.post(BASE_URL + path, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                  json=body, timeout=timeout)
        except requests.RequestException as exc:
            self._fail(f"network error: {exc}")
            raise TavilyError(f"Could not reach Tavily: {exc}") from exc
        if r.status_code != 200:
            detail = r.text[:300]
            try:
                detail = (r.json().get("detail") or {}).get("error") or detail
            except (ValueError, AttributeError):
                pass
            self._fail(f"{path} -> {r.status_code}: {detail}")
            raise TavilyError(f"Tavily {path} failed ({r.status_code}): {detail}")
        try:
            data = r.json()
        except ValueError as exc:
            self._fail(f"{path}: invalid JSON")
            raise TavilyError("Tavily returned an invalid response") from exc
        with self._lock:
            self.stats["calls"] += 1
            self.stats["credits"] += int(((data.get("usage") or {}).get("credits")) or 0)
        return data

    def _fail(self, message: str) -> None:
        with self._lock:
            self.stats["errors"] += 1
            self.stats["last_error"] = message
        log.warning("Tavily %s", message)

    @staticmethod
    def _key(path: str, body: dict) -> str:
        return "tavily:" + path + ":" + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()

    def _cached(self, path: str, body: dict, ttl: float, timeout: float) -> dict:
        if not self.available:
            raise TavilyError(self.why_off() or "Tavily is off")
        key = self._key(path, body)
        if self.db is not None:
            hit = self.db.cache_get(key, max_age=ttl)
            if hit is not None:
                with self._lock:
                    self.stats["cached"] += 1
                return hit
        data = self._post(path, body, timeout)
        if self.db is not None:
            self.db.cache_put(key, data)
        return data

    def search(self, query: str, *, max_results: int = 8, include_domains: list[str] | None = None, include_images: bool = False,
               include_answer: bool | str = False, search_depth: str = "basic", topic: str = "general",
               time_range: str | None = None, ttl: float = DAY) -> dict:
        body: dict[str, Any] = {"query": query[:400], "max_results": max(1, min(20, max_results)), "search_depth": search_depth,
                                "topic": topic, "include_images": include_images, "include_answer": include_answer}
        if include_domains:
            body["include_domains"] = include_domains
        if time_range:
            body["time_range"] = time_range
        data = self._cached("/search", body, ttl, 40.0)
        data.setdefault("results", [])
        data.setdefault("images", [])
        return data

    @staticmethod
    def _extract_body(urls: list[str], include_images: bool, query: str | None) -> dict:
        body: dict[str, Any] = {"urls": urls, "include_images": include_images, "format": "markdown", "extract_depth": "basic"}
        if query:
            body["query"] = query[:400]
        return body

    def extract(self, urls: list[str] | str, *, include_images: bool = False, query: str | None = None, ttl: float = 7 * DAY) -> dict:
        urls = [urls] if isinstance(urls, str) else list(urls)[:20]
        data = self._cached("/extract", self._extract_body(urls, include_images, query), ttl, 40.0)
        data.setdefault("results", [])
        data.setdefault("failed_results", [])
        return data

    def extract_many(self, urls: list[str], *, include_images: bool = False, ttl: float = 7 * DAY) -> int:
        if not self.available:
            raise TavilyError(self.why_off() or "Tavily is off")
        todo = []
        for u in dict.fromkeys(urls):
            key = self._key("/extract", self._extract_body([u], include_images, None))
            if self.db is None or self.db.cache_get(key, max_age=ttl) is None:
                todo.append(u)
        for i in range(0, len(todo), 20):
            data = self._post("/extract", self._extract_body(todo[i : i + 20], include_images, None), 60.0)
            if self.db is None:
                continue
            for r in data.get("results") or []:
                if r.get("url") in todo and r.get("raw_content"):
                    self.db.cache_put(self._key("/extract", self._extract_body([r["url"]], include_images, None)),
                                      {"results": [r], "failed_results": []})
        return len(todo)

    def ping(self) -> str:
        data = self._post("/search", {"query": "creative commons stock footage", "max_results": 1, "search_depth": "basic"}, 20.0)
        return f"{len(data.get('results') or [])} result(s) in {data.get('response_time', '?')} s"


def image_urls(items: list | None) -> list[str]:
    out = []
    for it in items or []:
        if isinstance(it, str):
            out.append(it)
        elif isinstance(it, dict) and it.get("url"):
            out.append(str(it["url"]))
    return out
