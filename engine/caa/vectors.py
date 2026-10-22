from __future__ import annotations

import threading

import numpy as np

from .db import Database


def normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    if v.ndim == 1:
        n = np.linalg.norm(v)
        return v / n if n > 0 else v
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


class VectorIndex:
    def __init__(self, db: Database, model: str, table: str = "embeddings"):
        self.db = db
        self.model = model
        self.table = table
        self._lock = threading.RLock()
        self._ids: list[int] = []
        self._pos: dict[int, int] = {}
        self._mat = np.zeros((0, 0), dtype=np.float32)
        self._pending: dict[int, np.ndarray] = {}
        self._removed: set[int] = set()
        self.load()

    def load(self) -> None:
        rows = self.db.all_embeddings(self.model, self.table)
        with self._lock:
            if not rows:
                self._ids, self._pos, self._mat = [], {}, np.zeros((0, 0), dtype=np.float32)
            else:
                vecs = [np.frombuffer(b, dtype=np.float16).astype(np.float32) for _, b, _ in rows]
                self._ids = [sid for sid, _, _ in rows]
                self._pos = {sid: i for i, sid in enumerate(self._ids)}
                self._mat = normalize(np.vstack(vecs))
            self._pending.clear()
            self._removed.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._ids) - len(self._removed & set(self._pos)) + len([k for k in self._pending if k not in self._pos])

    def add(self, segment_id: int, vec: np.ndarray) -> None:
        v = normalize(np.asarray(vec, dtype=np.float32).reshape(-1))
        self.db.put_embedding(segment_id, self.model, v.astype(np.float16).tobytes(), int(v.shape[0]), self.table)
        with self._lock:
            self._pending[segment_id] = v
            self._removed.discard(segment_id)

    def remove(self, segment_ids) -> None:
        with self._lock:
            for sid in segment_ids:
                self._pending.pop(sid, None)
                self._removed.add(sid)

    def _compact(self) -> None:
        if not self._pending and not self._removed:
            return
        keep = [sid for sid in self._ids if sid not in self._removed and sid not in self._pending]
        vecs = [self._mat[self._pos[sid]] for sid in keep]
        for sid, v in self._pending.items():
            keep.append(sid)
            vecs.append(v)
        dims = {v.shape[0] for v in vecs}
        if len(dims) > 1:
            target = max(dims, key=lambda d: sum(1 for v in vecs if v.shape[0] == d))
            pairs = [(s, v) for s, v in zip(keep, vecs) if v.shape[0] == target]
            keep = [p[0] for p in pairs]
            vecs = [p[1] for p in pairs]
        self._ids = keep
        self._pos = {sid: i for i, sid in enumerate(keep)}
        self._mat = np.vstack(vecs).astype(np.float32) if vecs else np.zeros((0, 0), dtype=np.float32)
        self._pending.clear()
        self._removed.clear()

    def get(self, segment_id: int) -> np.ndarray | None:
        with self._lock:
            if segment_id in self._pending:
                return self._pending[segment_id]
            i = self._pos.get(segment_id)
            if i is None or segment_id in self._removed:
                return None
            return self._mat[i]

    def search(self, query: np.ndarray, k: int = 200, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        with self._lock:
            self._compact()
            if self._mat.size == 0:
                return []
            q = normalize(np.asarray(query, dtype=np.float32).reshape(-1))
            if q.shape[0] != self._mat.shape[1]:
                return []
            scores = self._mat @ q
            if allowed is not None:
                mask = np.fromiter((sid in allowed for sid in self._ids), dtype=bool, count=len(self._ids))
                scores = np.where(mask, scores, -np.inf)
            k = min(k, scores.shape[0])
            if k <= 0:
                return []
            idx = np.argpartition(-scores, k - 1)[:k]
            idx = idx[np.argsort(-scores[idx])]
            return [(self._ids[i], float(scores[i])) for i in idx if np.isfinite(scores[i])]
