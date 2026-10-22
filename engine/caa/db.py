from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL DEFAULT 'local',
    enabled INTEGER NOT NULL DEFAULT 1,
    added_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    folder_id INTEGER REFERENCES folders(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER NOT NULL DEFAULT 0,
    mtime REAL NOT NULL DEFAULT 0,
    fingerprint TEXT,
    duration REAL,
    width INTEGER,
    height INTEGER,
    fps REAL,
    has_audio INTEGER NOT NULL DEFAULT 0,
    has_alpha INTEGER NOT NULL DEFAULT 0,
    green_screen INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    caption TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    meta TEXT NOT NULL DEFAULT '{}',
    transcript TEXT,
    source_url TEXT,
    license TEXT,
    captioned_by TEXT,
    indexed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_folder ON assets(folder_id);
CREATE INDEX IF NOT EXISTS idx_assets_fp ON assets(fingerprint);
CREATE TABLE IF NOT EXISTS segments (
    id INTEGER PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL DEFAULT 0,
    start REAL NOT NULL DEFAULT 0,
    end REAL NOT NULL DEFAULT 0,
    caption TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    transcript TEXT,
    thumb TEXT,
    green_ratio REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_segments_asset ON segments(asset_id);
CREATE TABLE IF NOT EXISTS embeddings (
    segment_id INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS text_vectors (
    segment_id INTEGER PRIMARY KEY REFERENCES segments(id) ON DELETE CASCADE,
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vec BLOB NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    name, caption, tags, transcript, folder,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    query TEXT,
    asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
    segment_id INTEGER,
    action TEXT NOT NULL,
    context TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_feedback_asset ON feedback(asset_id);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS downloads (
    path TEXT PRIMARY KEY,
    page_url TEXT NOT NULL,
    media_url TEXT,
    licence TEXT NOT NULL DEFAULT '{}',
    created REAL NOT NULL
);
"""

ASSET_JSON_FIELDS = ("tags", "meta", "license")


def _np_default(o):
    if hasattr(o, "item"):
        return o.item()
    if hasattr(o, "tolist"):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def dumps(o) -> str:
    return json.dumps(o, default=_np_default)
SEGMENT_JSON_FIELDS = ("tags", "details")


def _decode(row: sqlite3.Row | None, json_fields: Iterable[str]) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for f in json_fields:
        if f in d and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except json.JSONDecodeError:
                pass
    return d


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(assets)")}
            for col, typ in (("captured_at", "REAL"), ("captured_src", "TEXT"), ("lat", "REAL"), ("lon", "REAL"), ("device", "TEXT")):
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE assets ADD COLUMN {col} {typ}")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_captured ON assets(captured_at)")
            if "details" not in {r[1] for r in self.conn.execute("PRAGMA table_info(segments)")}:
                self.conn.execute("ALTER TABLE segments ADD COLUMN details TEXT")
            self.conn.commit()

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.conn.execute(sql, tuple(params))
            self.conn.commit()
            return cur

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.conn.execute(sql, tuple(params)).fetchone()

    def add_folder(self, path: str, kind: str = "local") -> dict:
        with self._lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO folders(path, kind, added_at) VALUES (?,?,?)",
                (path, kind, time.time()),
            )
            self.conn.execute("UPDATE folders SET enabled=1 WHERE path=?", (path,))
            self.conn.commit()
            return dict(self.conn.execute("SELECT * FROM folders WHERE path=?", (path,)).fetchone())

    def remove_folder(self, folder_id: int) -> None:
        with self._lock:
            ids = [r[0] for r in self.conn.execute("SELECT id FROM assets WHERE folder_id=?", (folder_id,))]
            for aid in ids:
                self._delete_asset_locked(aid)
            self.conn.execute("DELETE FROM folders WHERE id=?", (folder_id,))
            self.conn.commit()

    def folders(self) -> list[dict]:
        rows = self.query(
            """SELECT f.*, COUNT(a.id) AS assets,
                      SUM(CASE WHEN a.status='indexed' THEN 1 ELSE 0 END) AS n_indexed,
                      SUM(CASE WHEN a.status='error' THEN 1 ELSE 0 END) AS n_errors
               FROM folders f LEFT JOIN assets a ON a.folder_id=f.id
               GROUP BY f.id ORDER BY f.added_at"""
        )
        out = []
        for r in rows:
            d = dict(r)
            d["indexed"] = d.pop("n_indexed") or 0
            d["errors"] = d.pop("n_errors") or 0
            out.append(d)
        return out

    def asset_by_path(self, path: str) -> dict | None:
        return _decode(self.query_one("SELECT * FROM assets WHERE path=?", (path,)), ASSET_JSON_FIELDS)

    def asset(self, asset_id: int) -> dict | None:
        return _decode(self.query_one("SELECT * FROM assets WHERE id=?", (asset_id,)), ASSET_JSON_FIELDS)

    def assets(self, ids: Iterable[int]) -> dict[int, dict]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        out: dict[int, dict] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.query(f"SELECT * FROM assets WHERE id IN ({marks})", chunk):
                out[r["id"]] = _decode(r, ASSET_JSON_FIELDS)
        return out

    def list_assets(self, kind: str | None = None, offset: int = 0, limit: int = 60, status: str | None = None) -> list[dict]:
        sql = "SELECT * FROM assets WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if status:
            sql += " AND status=?"
            params.append(status)
        sql += " ORDER BY COALESCE(indexed_at, 0) DESC, id DESC LIMIT ? OFFSET ?"
        params += [limit, offset]
        return [_decode(r, ASSET_JSON_FIELDS) for r in self.query(sql, params)]

    def upsert_asset(self, data: dict) -> int:
        cols = list(data.keys())
        values = [dumps(data[c]) if c in ASSET_JSON_FIELDS and not isinstance(data[c], str) and data[c] is not None else data[c] for c in cols]
        with self._lock:
            row = self.conn.execute("SELECT id FROM assets WHERE path=?", (data["path"],)).fetchone()
            if row:
                sets = ",".join(f"{c}=?" for c in cols)
                self.conn.execute(f"UPDATE assets SET {sets} WHERE id=?", (*values, row[0]))
                aid = row[0]
            else:
                marks = ",".join("?" * len(cols))
                cur = self.conn.execute(f"INSERT INTO assets({','.join(cols)}) VALUES ({marks})", values)
                aid = cur.lastrowid
            self.conn.commit()
            return int(aid)

    def update_asset(self, asset_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = list(fields.keys())
        values = [dumps(fields[c]) if c in ASSET_JSON_FIELDS and not isinstance(fields[c], str) and fields[c] is not None else fields[c] for c in cols]
        self.execute(f"UPDATE assets SET {','.join(f'{c}=?' for c in cols)} WHERE id=?", (*values, asset_id))

    def _delete_asset_locked(self, asset_id: int) -> None:
        seg_ids = [r[0] for r in self.conn.execute("SELECT id FROM segments WHERE asset_id=?", (asset_id,))]
        for sid in seg_ids:
            self.conn.execute("DELETE FROM fts WHERE rowid=?", (sid,))
            self.conn.execute("DELETE FROM embeddings WHERE segment_id=?", (sid,))
            self.conn.execute("DELETE FROM text_vectors WHERE segment_id=?", (sid,))
        self.conn.execute("DELETE FROM segments WHERE asset_id=?", (asset_id,))
        self.conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))

    def delete_asset(self, asset_id: int) -> list[int]:
        with self._lock:
            seg_ids = [r[0] for r in self.conn.execute("SELECT id FROM segments WHERE asset_id=?", (asset_id,))]
            self._delete_asset_locked(asset_id)
            self.conn.commit()
            return seg_ids

    def clear_segments(self, asset_id: int) -> list[int]:
        with self._lock:
            seg_ids = [r[0] for r in self.conn.execute("SELECT id FROM segments WHERE asset_id=?", (asset_id,))]
            for sid in seg_ids:
                self.conn.execute("DELETE FROM fts WHERE rowid=?", (sid,))
                self.conn.execute("DELETE FROM embeddings WHERE segment_id=?", (sid,))
                self.conn.execute("DELETE FROM text_vectors WHERE segment_id=?", (sid,))
            self.conn.execute("DELETE FROM segments WHERE asset_id=?", (asset_id,))
            self.conn.commit()
            return seg_ids

    def add_segment(self, asset_id: int, idx: int, start: float, end: float, caption: str | None = None,
                    tags: list | None = None, transcript: str | None = None, thumb: str | None = None,
                    green_ratio: float = 0.0) -> int:
        cur = self.execute(
            "INSERT INTO segments(asset_id, idx, start, end, caption, tags, transcript, thumb, green_ratio) VALUES (?,?,?,?,?,?,?,?,?)",
            (asset_id, idx, start, end, caption, dumps(tags or []), transcript, thumb, green_ratio),
        )
        return int(cur.lastrowid)

    def update_segment(self, segment_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = list(fields.keys())
        values = [dumps(fields[c]) if c in SEGMENT_JSON_FIELDS and not isinstance(fields[c], str) else fields[c] for c in cols]
        self.execute(f"UPDATE segments SET {','.join(f'{c}=?' for c in cols)} WHERE id=?", (*values, segment_id))

    def segment(self, segment_id: int) -> dict | None:
        return _decode(self.query_one("SELECT * FROM segments WHERE id=?", (segment_id,)), SEGMENT_JSON_FIELDS)

    def segments_for(self, asset_id: int) -> list[dict]:
        return [_decode(r, SEGMENT_JSON_FIELDS) for r in self.query("SELECT * FROM segments WHERE asset_id=? ORDER BY idx", (asset_id,))]

    def segments(self, ids: Iterable[int]) -> dict[int, dict]:
        ids = list(dict.fromkeys(int(i) for i in ids))
        out: dict[int, dict] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self.query(f"SELECT * FROM segments WHERE id IN ({marks})", chunk):
                out[r["id"]] = _decode(r, SEGMENT_JSON_FIELDS)
        return out

    def get_fts(self, segment_id: int) -> dict | None:
        row = self.query_one("SELECT name, caption, tags, transcript, folder FROM fts WHERE rowid=?", (segment_id,))
        return dict(row) if row else None

    def put_fts(self, segment_id: int, name: str, caption: str, tags: str, transcript: str, folder: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM fts WHERE rowid=?", (segment_id,))
            self.conn.execute(
                "INSERT INTO fts(rowid, name, caption, tags, transcript, folder) VALUES (?,?,?,?,?,?)",
                (segment_id, name, caption, tags, transcript, folder),
            )
            self.conn.commit()

    def fts_search(self, match: str, limit: int = 200) -> list[tuple[int, float]]:
        try:
            rows = self.query(
                "SELECT rowid, bm25(fts, 4.0, 3.0, 3.0, 1.5, 1.0) AS score FROM fts WHERE fts MATCH ? ORDER BY score LIMIT ?",
                (match, limit),
            )
        except sqlite3.OperationalError:
            return []
        return [(int(r[0]), float(r[1])) for r in rows]

    def put_embedding(self, segment_id: int, model: str, vec_bytes: bytes, dim: int, table: str = "embeddings") -> None:
        assert table in ("embeddings", "text_vectors")
        self.execute(
            f"INSERT OR REPLACE INTO {table}(segment_id, model, dim, vec) VALUES (?,?,?,?)",
            (segment_id, model, dim, vec_bytes),
        )

    def all_embeddings(self, model: str, table: str = "embeddings") -> list[tuple[int, bytes, int]]:
        assert table in ("embeddings", "text_vectors")
        return [(int(r[0]), r[1], int(r[2])) for r in self.query(f"SELECT segment_id, vec, dim FROM {table} WHERE model=?", (model,))]

    def add_feedback(self, action: str, asset_id: int | None, segment_id: int | None = None, query: str | None = None, context: dict | None = None) -> int:
        cur = self.execute(
            "INSERT INTO feedback(ts, query, asset_id, segment_id, action, context) VALUES (?,?,?,?,?,?)",
            (time.time(), query, asset_id, segment_id, action, dumps(context or {})),
        )
        return int(cur.lastrowid)

    def feedback_stats(self) -> dict[int, dict[str, int]]:
        out: dict[int, dict[str, int]] = {}
        for r in self.query("SELECT asset_id, action, COUNT(*) c, MAX(ts) last FROM feedback WHERE asset_id IS NOT NULL GROUP BY asset_id, action"):
            d = out.setdefault(int(r["asset_id"]), {})
            d[r["action"]] = int(r["c"])
            d["last_" + r["action"]] = float(r["last"])
        return out

    def recent_feedback(self, limit: int = 50) -> list[dict]:
        return [dict(r) for r in self.query("SELECT * FROM feedback ORDER BY ts DESC LIMIT ?", (limit,))]

    def cache_get(self, key: str, max_age: float | None = None) -> Any:
        row = self.query_one("SELECT value, created FROM cache WHERE key=?", (key,))
        if not row:
            return None
        if max_age is not None and time.time() - float(row[1]) > max_age:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return None

    def cache_put(self, key: str, value: Any) -> None:
        self.execute("INSERT OR REPLACE INTO cache(key, value, created) VALUES (?,?,?)", (key, dumps(value), time.time()))

    def put_download(self, path: str, page_url: str, media_url: str | None, licence: dict | None) -> None:
        self.execute("INSERT OR REPLACE INTO downloads(path, page_url, media_url, licence, created) VALUES (?,?,?,?,?)",
                     (path, page_url, media_url, dumps(licence or {}), time.time()))

    def download_for(self, path: str) -> dict | None:
        row = self.query_one("SELECT * FROM downloads WHERE path=?", (path,)) or \
            self.query_one("SELECT * FROM downloads WHERE lower(path)=lower(?)", (path,))
        return _decode(row, ("licence",))

    def stats(self) -> dict:
        r = self.query_one(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN status='indexed' THEN 1 ELSE 0 END) n_indexed,
                      SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) n_errors,
                      SUM(CASE WHEN status IN ('pending','indexing') THEN 1 ELSE 0 END) n_pending
               FROM assets"""
        )
        kinds = {row["kind"]: row["c"] for row in self.query("SELECT kind, COUNT(*) c FROM assets GROUP BY kind")}
        segs = self.query_one("SELECT COUNT(*) FROM segments")[0]
        captioned = self.query_one("SELECT COUNT(*) FROM assets WHERE captioned_by IS NOT NULL")[0]
        return {
            "total": r["total"] or 0,
            "indexed": r["n_indexed"] or 0,
            "errors": r["n_errors"] or 0,
            "pending": r["n_pending"] or 0,
            "segments": segs,
            "captioned": captioned,
            "kinds": kinds,
        }
