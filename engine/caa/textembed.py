from __future__ import annotations

import logging
import threading
from datetime import datetime

import numpy as np

from .db import Database
from .vectors import VectorIndex, normalize

log = logging.getLogger("caa.textembed")

DEFAULT_TEXT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
NOISE_TAGS = {"video", "clip", "footage", "b-roll", "landscape", "horizontal", "hd", "4k", "16:9", "image", "photo", "still",
              "audio", "sound", "template", "portrait", "vertical", "9:16", "square"}


class TextEmbedder:
    name = "none"
    dim = 0
    available = False

    def embed(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class TransformerTextEmbedder(TextEmbedder):
    available = True

    def __init__(self, model_id: str = DEFAULT_TEXT_MODEL, device: str | None = None, max_length: int = 128):
        import torch
        import transformers
        from transformers import AutoModel, AutoTokenizer

        transformers.logging.set_verbosity_error()
        try:
            transformers.utils.logging.disable_progress_bar()
        except Exception:
            pass
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModel.from_pretrained(model_id).to(self.device).eval()
        self.max_length = max_length
        self.name = f"text:{model_id}"
        self._lock = threading.Lock()
        self.dim = int(self.embed(["test"]).shape[-1])

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = []
        with self._lock, self.torch.no_grad():
            for i in range(0, len(texts), 32):
                batch = self.tokenizer([t or " " for t in texts[i : i + 32]], padding=True, truncation=True,
                                       max_length=self.max_length, return_tensors="pt")
                batch = {k: v.to(self.device) for k, v in batch.items()}
                hidden = self.model(**batch).last_hidden_state
                mask = batch["attention_mask"].unsqueeze(-1).to(hidden.dtype)
                vec = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1e-9)
                out.append(vec.float().cpu().numpy())
        return normalize(np.vstack(out))


class LazyTextEmbedder(TextEmbedder):
    def __init__(self, enabled: bool = True, model_id: str = DEFAULT_TEXT_MODEL):
        self.model_id = model_id
        self._inner: TextEmbedder | None = None
        self._ready = threading.Event()
        self.error: str | None = None
        self.state = "loading" if enabled else "off"
        if not enabled:
            self._inner = TextEmbedder()
            self._ready.set()
            return
        threading.Thread(target=self._load, name="caa-text-embedder", daemon=True).start()

    def _load(self) -> None:
        try:
            self._inner = TransformerTextEmbedder(self.model_id)
            self.state = "ready"
            log.info("Loaded %s (dim %s) for meaning search", self._inner.name, self._inner.dim)
        except Exception as exc:
            self.error = str(exc)
            self._inner = TextEmbedder()
            self.state = "unavailable"
            log.warning("Meaning search unavailable (%s). Searches use keywords and visual search.", exc)
        finally:
            self._ready.set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._ready.wait(timeout)

    @property
    def available(self) -> bool:
        return self._ready.is_set() and bool(self._inner and self._inner.available)

    @property
    def name(self) -> str:
        return self._inner.name if self._ready.is_set() and self._inner else f"text:{self.model_id}"

    @property
    def dim(self) -> int:
        return self._inner.dim if self._ready.is_set() and self._inner else 0

    def embed(self, texts: list[str]) -> np.ndarray:
        self._ready.wait()
        return self._inner.embed(texts)


def segment_doc(fts: dict | None) -> str:
    if not fts:
        return ""
    tags = [t for t in (fts.get("tags") or "").split() if t]
    parts = [fts.get("caption") or "", fts.get("name") or "", " ".join(t for t in tags if t not in NOISE_TAGS),
             (fts.get("transcript") or "")[:300], fts.get("folder") or ""]
    return " . ".join(p.strip() for p in parts if p and p.strip())


KIND_WORDS = {"video": "video clip", "image": "photo", "audio": "sound", "template": "template"}
DOC_VERSION = "d2"


def meta_phrase(a: dict | None) -> str:
    if not a:
        return ""
    bits = []
    w, h = a.get("width"), a.get("height")
    if w and h and a.get("kind") in ("video", "image"):
        bits.append("vertical" if h > w * 1.05 else "horizontal" if w > h * 1.05 else "square")
    bits.append(KIND_WORDS.get(a.get("kind") or "", ""))
    ts = a.get("captured_at")
    if ts and a.get("captured_src") != "file date":
        dt = datetime.fromtimestamp(ts)
        hr = dt.hour
        part = "morning" if 5 <= hr < 12 else "afternoon" if 12 <= hr < 17 else "evening" if 17 <= hr < 21 else "night"
        bits.append(f"recorded on {dt.strftime('%A')} {dt.day} {dt.strftime('%B')} {dt.year} in the {part}")
    if a.get("device"):
        bits.append(f"shot on {a['device']}")
    return " ".join(b for b in bits if b)


class SemanticIndex:
    def __init__(self, db: Database, embedder: TextEmbedder, floor: float = 0.3, window: float = 0.22):
        self.db = db
        self.embedder = embedder
        self.floor = floor
        self.window = window
        self._index: VectorIndex | None = None
        self._lock = threading.Lock()
        self._sync = threading.Lock()

    @property
    def ready(self) -> bool:
        return bool(self.embedder.available)

    @property
    def key(self) -> str:
        return f"{self.embedder.name}|{DOC_VERSION}"

    @property
    def index(self) -> VectorIndex | None:
        if not self.ready:
            return None
        with self._lock:
            if self._index is None:
                self._index = VectorIndex(self.db, self.key, table="text_vectors")
            return self._index

    def __len__(self) -> int:
        idx = self.index
        return len(idx) if idx is not None else 0

    def remove(self, segment_ids) -> None:
        idx = self._index
        if idx is not None:
            idx.remove(segment_ids)

    def sync(self, batch: int = 64) -> int:
        idx = self.index
        if idx is None:
            return 0
        done = 0
        with self._sync:
            while True:
                rows = self.db.query("SELECT s.id, a.kind, a.width, a.height, a.captured_at, a.captured_src, a.device "
                                     "FROM segments s JOIN assets a ON a.id = s.asset_id "
                                     "LEFT JOIN text_vectors t ON t.segment_id = s.id AND t.model = ? "
                                     "WHERE t.segment_id IS NULL AND a.status = 'indexed' LIMIT ?", (self.key, batch))
                if not rows:
                    break
                ids = [int(r["id"]) for r in rows]
                docs = []
                for r in rows:
                    base = segment_doc(self.db.get_fts(int(r["id"])))
                    docs.append(" . ".join(x for x in (base, meta_phrase(dict(r))) if x) if base else "")
                vecs = self.embedder.embed(docs)
                for sid, doc, v in zip(ids, docs, vecs):
                    idx.add(sid, v if doc else np.zeros_like(v))
                done += len(ids)
        return done

    def query_vector(self, text: str) -> np.ndarray | None:
        if not self.ready or not text.strip():
            return None
        return self.embedder.embed([text])[0]

    def search(self, text: str, k: int = 300, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        idx = self.index
        qv = self.query_vector(text)
        if idx is None or qv is None:
            return []
        return self.cut(idx.search(qv, k, allowed))

    def near(self, segment_id: int, k: int = 300) -> list[tuple[int, float]]:
        idx = self.index
        if idx is None:
            return []
        v = idx.get(segment_id)
        if v is None or not np.any(v):
            return []
        return self.cut(idx.search(v, k))

    def cut(self, hits: list[tuple[int, float]]) -> list[tuple[int, float]]:
        if not hits:
            return []
        top = hits[0][1]
        return [(sid, s) for sid, s in hits if s >= self.floor and s >= top - self.window]
