from __future__ import annotations

import logging
import threading

import numpy as np

from . import media, timeq
from .asr import Transcriber, get_transcriber
from .broll import BrollPlanner
from .config import Settings
from .db import Database
from .embed import Embedder, FallbackEmbedder, get_embedder
from .indexer import Indexer
from .nemotron import TokenFactory
from .search import SearchEngine
from .sources import SourceAudit, WebAssets
from .tavily import Tavily
from .textembed import LazyTextEmbedder, SemanticIndex, TextEmbedder
from .vectors import VectorIndex
from .watcher import FolderWatcher

log = logging.getLogger("caa.services")


class LazyEmbedder(Embedder):
    def __init__(self, backend: str, model_id: str):
        self.backend = backend
        self.model_id = model_id
        self._inner: Embedder | None = None
        self._ready = threading.Event()
        self.error: str | None = None
        self.state = "loading"
        threading.Thread(target=self._load, name="caa-embedder", daemon=True).start()

    def _load(self) -> None:
        try:
            self._inner = get_embedder(self.backend, self.model_id)
            self.state = "ready" if not isinstance(self._inner, FallbackEmbedder) else "fallback"
        except Exception as exc:
            self.error = str(exc)
            self._inner = FallbackEmbedder()
            self.state = "fallback"
        finally:
            self._ready.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout)

    @property
    def inner(self) -> Embedder:
        self._ready.wait()
        return self._inner

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def dim(self) -> int:
        return self.inner.dim

    @property
    def supports_text(self) -> bool:
        return self._ready.is_set() and self.inner.supports_text

    def embed_images(self, images) -> np.ndarray:
        return self.inner.embed_images(images)

    def embed_texts(self, texts) -> np.ndarray:
        return self.inner.embed_texts(texts)


class LazyTranscriber(Transcriber):
    def __init__(self, enabled: bool, model: str, model_dir=None, quantization: str | None = None):
        self._inner: Transcriber | None = None
        self._ready = threading.Event()
        self.state = "loading" if enabled else "disabled"
        if not enabled:
            self._inner = Transcriber()
            self._ready.set()
            return

        def load():
            self._inner = get_transcriber(True, model, model_dir, quantization)
            self.state = "ready" if self._inner.available else "unavailable"
            self._ready.set()

        threading.Thread(target=load, name="caa-asr", daemon=True).start()

    @property
    def available(self) -> bool:
        self._ready.wait()
        return self._inner.available

    @property
    def name(self) -> str:
        return getattr(self._inner, "name", "none") if self._inner else "loading"

    def transcribe(self, samples, sr: int = 16000):
        self._ready.wait()
        return self._inner.transcribe(samples, sr)


class Services:
    def __init__(self, settings: Settings, embedder: Embedder | None = None, tf: TokenFactory | None = None,
                 transcriber: Transcriber | None = None, start_worker: bool = True, watch: bool = True,
                 text_embedder: TextEmbedder | None = None, tavily: Tavily | None = None, web_session=None):
        self.settings = settings
        self.db = Database(settings.db_path)
        self.embedder = embedder or LazyEmbedder(settings.embed_backend, settings.embed_model)
        self.tf = tf or TokenFactory(settings, self.db)
        self.transcriber = transcriber or LazyTranscriber(settings.asr_enabled, settings.asr_model, settings.asr_model_dir(),
                                                          settings.asr_quantization)
        self.text_embedder = text_embedder or LazyTextEmbedder(settings.semantic_search, settings.text_model)
        self.semantic = SemanticIndex(self.db, self.text_embedder)
        self._vindex: VectorIndex | None = None
        self._vlock = threading.Lock()
        self.indexer = Indexer(settings, self.db, self.embedder, _VIndexProxy(self), self.tf, self.transcriber)
        self.indexer.semantic = self.semantic
        self.search = SearchEngine(self.db, self.embedder, _VIndexProxy(self), self.tf, self.semantic)
        self.watcher = FolderWatcher(self.indexer, self.db) if watch else None
        self.tavily = tavily or Tavily(settings, self.db)
        self.web = WebAssets(settings, self.db, self.tavily, self.tf, session=web_session, on_saved=self._saved_download)
        self.audit = SourceAudit(self.db, self.web)
        self.broll = BrollPlanner(self.tavily, self.tf, self.search)
        self.apply_settings()
        if start_worker:
            self.indexer.start()
            threading.Thread(target=self._boot, name="caa-boot", daemon=True).start()

    @property
    def vindex(self) -> VectorIndex:
        with self._vlock:
            if self._vindex is None:
                self._vindex = VectorIndex(self.db, self.embedder.name)
            return self._vindex

    def _boot(self) -> None:
        if self.tf.available:
            try:
                self.tf.resolve_models(apply=True)
            except Exception as exc:
                log.warning("Could not list Token Factory models: %s", exc)
        if isinstance(self.embedder, LazyEmbedder):
            self.embedder.wait()
        _ = self.vindex
        if self.watcher:
            self.watcher.start()
        try:
            self.indexer.scan()
        except Exception as exc:
            log.error("Initial scan failed: %s", exc)
        try:
            res = self.indexer.backfill()
            if res["metadata"] or res["rechecked"]:
                log.info("Added recording metadata to %d files; re-checking %d files flagged as green screen", res["metadata"], res["rechecked"])
        except Exception as exc:
            log.error("Metadata backfill failed: %s", exc)
        if hasattr(self.text_embedder, "wait"):
            self.text_embedder.wait()
        try:
            n = self.semantic.sync()
            if n:
                log.info("Prepared meaning search for %d shots", n)
        except Exception as exc:
            log.error("Preparing meaning search failed: %s", exc)

    def ensure_inbox(self) -> dict:
        inbox = str(self.web.inbox())
        known = next((f for f in self.db.folders() if f["path"] == inbox), None)
        if known and known["enabled"]:
            return known
        f = self.db.add_folder(inbox, "inbox")
        if self.watcher:
            self.watcher.sync()
        return f

    def _saved_download(self, path) -> None:
        self.ensure_inbox()
        self.indexer.enqueue(str(path), force=True)

    def apply_settings(self, reconnect: bool = False) -> None:
        media.set_ffmpeg_dir(self.settings.ffmpeg_dir)
        order = self.settings.date_order
        self.search.date_order = order if order in ("DMY", "MDY", "YMD") else timeq.system_date_order()
        if reconnect and self.tf.available:
            def resolve():
                try:
                    self.tf.resolve_models(apply=True)
                except Exception as exc:
                    log.warning("Could not list Token Factory models: %s", exc)
            threading.Thread(target=resolve, name="caa-models", daemon=True).start()

    def status(self) -> dict:
        emb_state = getattr(self.embedder, "state", "fallback" if isinstance(self.embedder, FallbackEmbedder) else "ready")
        emb_name = self.embedder.name if emb_state != "loading" else self.settings.embed_model
        return {
            "library": self.db.stats(),
            "indexer": {k: v for k, v in self.indexer.progress.items()},
            "embedder": {"state": emb_state, "name": emb_name, "text_search": self.embedder.supports_text,
                         "error": getattr(self.embedder, "error", None)},
            "transcriber": {"state": getattr(self.transcriber, "state", "ready" if self.transcriber.available else "unavailable"),
                            "name": getattr(self.transcriber, "name", "none")},
            "nemotron": {"enabled": self.tf.available, "privacy_mode": self.settings.privacy_mode,
                         "has_key": bool(self.settings.nebius_api_key), "models": self.settings.models, **self.tf.stats},
            "watcher": self.watcher.state if self.watcher else "off",
            "semantic": {"state": getattr(self.text_embedder, "state", "ready" if self.text_embedder.available else "off"),
                         "name": self.text_embedder.name.split(":", 1)[-1], "vectors": len(self.semantic),
                         "nemotron_search": bool(self.settings.nemotron_search)},
            "tavily": {"enabled": self.tavily.available, "has_key": self.tavily.has_key, "why_off": self.tavily.why_off(),
                       "inbox": self.settings.inbox_dir, **self.tavily.stats},
            "audit": dict(self.audit.progress),
        }

    def close(self) -> None:
        if self.watcher:
            self.watcher.stop()
        self.indexer.stop()


class _VIndexProxy:
    def __init__(self, services: Services):
        self._s = services

    def __getattr__(self, item):
        return getattr(self._s.vindex, item)

    def __len__(self) -> int:
        return len(self._s.vindex)
