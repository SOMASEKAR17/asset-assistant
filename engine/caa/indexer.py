from __future__ import annotations

import json
import logging
import os
import queue
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import audio as audiofx
from . import media
from . import metadata
from .asr import Transcriber
from .config import Settings
from .db import Database
from .embed import Embedder
from .nemotron import TokenFactory
from .vectors import VectorIndex, normalize

log = logging.getLogger("caa.indexer")

INDEX_VERSION = 2
KEY_TAGS = {"green screen", "blue screen", "chroma key", "keyable", "greenscreen", "bluescreen"}

TEMPLATE_TAGS = {
    ".mogrt": ["motion graphics template", "mogrt", "premiere pro"],
    ".aep": ["after effects", "project"],
    ".aet": ["after effects", "template"],
    ".prproj": ["premiere pro", "project"],
    ".drp": ["davinci resolve", "project"],
    ".drfx": ["davinci resolve", "fusion", "effect"],
    ".setting": ["davinci resolve", "fusion", "macro"],
    ".motn": ["final cut pro", "apple motion"],
    ".moti": ["final cut pro", "title"],
    ".moef": ["final cut pro", "effect"],
    ".cube": ["lut", "color grade", "look"],
    ".look": ["lut", "color grade", "look"],
}

SKIP_DIRS = {"$recycle.bin", "system volume information", ".git", "node_modules", "__macosx", ".trash", "@eadir"}


def name_tokens(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"([a-z])([A-Z])", r"\1 \2", stem)
    stem = re.sub(r"([A-Za-z])(\d)", r"\1 \2", stem)
    stem = re.sub(r"(\d)([A-Za-z])", r"\1 \2", stem)
    return re.sub(r"[_\-.+()\[\]]+", " ", stem).lower().strip()


def folder_tokens(path: str, root: str | None) -> str:
    p = Path(path).parent
    parts = list(p.parts[-3:])
    if root:
        try:
            parts = list(Path(path).parent.relative_to(root).parts) or [Path(root).name]
        except ValueError:
            pass
    return " ".join(name_tokens(x) for x in parts)


def caption_text(c: dict | None) -> str:
    if not c:
        return ""
    bits = [c.get("description", ""), c.get("setting", ""), c.get("shot_type", ""), c.get("camera_motion", ""),
            c.get("background", "") if c.get("background") not in ("", "normal") else "", c.get("on_screen_text", ""),
            c.get("energy", ""), c.get("kind", "")]
    for k in ("subjects", "actions", "mood", "colors", "instruments", "good_for"):
        bits.extend(c.get(k) or [])
    return " ".join(b for b in bits if b)


def caption_details(c: dict | None) -> dict | None:
    if not c:
        return None
    out = {k: v for k, v in c.items() if k not in ("description", "tags") and not k.startswith("_") and v not in ("", None, [], "unknown")}
    if out.get("background") == "normal":
        out.pop("background")
    return out or None


def orientation_tags(w: int | None, h: int | None) -> list[str]:
    if not w or not h:
        return []
    tags = []
    r = w / h
    if r > 1.15:
        tags.append("landscape")
        tags.append("horizontal")
    elif r < 0.87:
        tags += ["portrait", "vertical", "9:16" if abs(r - 9 / 16) < 0.05 else "tall"]
    else:
        tags.append("square")
    long_side = max(w, h)
    if long_side >= 3800:
        tags.append("4k")
    elif long_side >= 1900:
        tags.append("hd")
    return tags


class Indexer:
    def __init__(self, settings: Settings, db: Database, embedder: Embedder, vindex: VectorIndex,
                 tf: TokenFactory, transcriber: Transcriber):
        self.settings = settings
        self.db = db
        self.embedder = embedder
        self.vindex = vindex
        self.tf = tf
        self.transcriber = transcriber
        self.q: queue.Queue = queue.Queue()
        self._queued: set[str] = set()
        self._force: set[str] = set()
        self._qlock = threading.Lock()
        self._plock = threading.Lock()
        self._threads: list[threading.Thread] = []
        self._active: dict[int, str] = {}
        self._stop = threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(settings.caption_workers)), thread_name_prefix="caa-describe")
        self._aux = ThreadPoolExecutor(max_workers=2, thread_name_prefix="caa-aux")
        self.listeners: list = []
        self.semantic = None
        self.progress = {"state": "idle", "queued": 0, "done": 0, "failed": 0, "current": None, "last_error": None,
                         "started": None, "recent": [], "blocker": None}

    def start(self) -> None:
        self._threads = [t for t in self._threads if t.is_alive()]
        if self._threads:
            return
        self._stop.clear()
        for i in range(max(1, int(self.settings.index_workers))):
            t = threading.Thread(target=self._worker, name=f"caa-indexer-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for _ in range(max(1, len(self._threads))):
            self.q.put(None)

    def _emit(self, event: dict) -> None:
        for fn in list(self.listeners):
            try:
                fn(event)
            except Exception:
                pass

    def _folder_for(self, path: str) -> dict | None:
        best = None
        for f in self.db.folders():
            root = f["path"]
            try:
                Path(path).resolve().relative_to(Path(root).resolve())
            except ValueError:
                continue
            if best is None or len(root) > len(best["path"]):
                best = f
        return best

    def is_current(self, path: str, st: os.stat_result | None = None, retry_errors: bool = False) -> bool:
        row = self.db.asset_by_path(str(Path(path)))
        if not row:
            return False
        try:
            st = st or os.stat(path)
        except OSError:
            return False
        if row["size"] != st.st_size or abs(row["mtime"] - st.st_mtime) >= 1:
            return False
        return row["status"] == "indexed" or (row["status"] == "error" and not retry_errors)

    def scan(self, folder_id: int | None = None, retry_errors: bool = False) -> int:
        self.progress["state"] = "scanning"
        count = 0
        have_ffmpeg = media.ffmpeg_available()
        blocked = 0
        if not have_ffmpeg:
            for r in self.db.query("SELECT id FROM assets WHERE status='error' AND (error LIKE '%ffprobe not found%' OR error LIKE '%ffmpeg not found%')"):
                self.remove_asset(r["id"])
        folders = [f for f in self.db.folders() if f["enabled"] and (folder_id is None or f["id"] == folder_id)]
        for f in folders:
            root = Path(f["path"])
            if not root.exists():
                continue
            seen: set[str] = set()
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_DIRS and not d.startswith(".")]
                for fn in filenames:
                    if fn.startswith(".") or fn.startswith("~$"):
                        continue
                    p = str(Path(dirpath) / fn)
                    kind = media.kind_for(p)
                    if kind is None:
                        continue
                    seen.add(p)
                    if not have_ffmpeg and kind in ("video", "audio"):
                        blocked += 1
                        continue
                    try:
                        st = os.stat(p)
                    except OSError:
                        continue
                    if self.is_current(p, st, retry_errors):
                        continue
                    if self.enqueue(p, force=True):
                        count += 1
            for r in self.db.query("SELECT id, path FROM assets WHERE folder_id=?", (f["id"],)):
                if r["path"] not in seen and not Path(r["path"]).exists():
                    self.remove_asset(r["id"])
        if blocked:
            self.progress["blocker"] = {"code": "ffmpeg", "files": blocked,
                                        "message": "FFmpeg is not installed, so videos and sounds are waiting."}
            log.warning("FFmpeg not found: %d videos and sounds are waiting. Install it with: winget install Gyan.FFmpeg", blocked)
        elif folder_id is None or have_ffmpeg:
            self.progress["blocker"] = None
        if self.q.empty() and self.progress["state"] == "scanning":
            self.progress["state"] = "idle"
        return count

    def enqueue(self, path: str, force: bool = False) -> bool:
        path = str(Path(path))
        with self._qlock:
            if force:
                self._force.add(path)
            if path in self._queued:
                return False
            self._queued.add(path)
        self.progress["queued"] = len(self._queued)
        self.q.put(path)
        return True

    def release(self, path: str) -> None:
        with self._qlock:
            self._queued.discard(path)
            self._force.discard(path)
            self.progress["queued"] = len(self._queued)

    def remove_path(self, path: str) -> None:
        row = self.db.asset_by_path(str(Path(path)))
        if row:
            self.remove_asset(row["id"])

    def remove_asset(self, asset_id: int) -> None:
        seg_ids = self.db.delete_asset(asset_id)
        self.vindex.remove(seg_ids)
        if self.semantic is not None:
            self.semantic.remove(seg_ids)
        self._emit({"type": "removed", "asset_id": asset_id})

    def _set_current(self) -> None:
        names = list(self._active.values())
        self.progress["current"] = names[-1] if names else None

    def _worker(self) -> None:
        me = threading.get_ident()
        while not self._stop.is_set():
            path = self.q.get()
            if path is None:
                break
            with self._qlock:
                forced = path in self._force
                self._force.discard(path)
            if not forced and Path(path).exists() and self.is_current(path):
                with self._qlock:
                    self._queued.discard(path)
                    self.progress["queued"] = len(self._queued)
                    if not self._queued:
                        self.progress.update(state="idle", current=None, started=None)
                continue
            with self._plock:
                self.progress["state"] = "indexing"
                if self.progress["started"] is None:
                    self.progress["started"] = time.time()
                self._active[me] = Path(path).name
                self._set_current()
            t0 = time.time()
            try:
                if media.kind_for(path) in ("video", "audio") and not media.ffmpeg_available():
                    b = self.progress.get("blocker") or {"code": "ffmpeg", "files": 0,
                                                         "message": "FFmpeg is not installed, so videos and sounds are waiting."}
                    b["files"] = b.get("files", 0) + 1
                    self.progress["blocker"] = b
                elif Path(path).exists():
                    aid = self.index_file(path)
                    secs = round(time.time() - t0, 1)
                    with self._plock:
                        self.progress["done"] += 1
                        self.progress["recent"] = ([{"asset_id": aid, "name": Path(path).name, "seconds": secs}] + self.progress["recent"])[:12]
                    self._emit({"type": "indexed", "asset_id": aid})
                else:
                    self.remove_path(path)
            except Exception as exc:
                if not Path(path).exists():
                    self.remove_path(path)
                else:
                    with self._plock:
                        self.progress["failed"] += 1
                        self.progress["last_error"] = f"{Path(path).name}: {exc}"
                    log.error("Indexing failed for %s: %s", path, exc)
            finally:
                with self._plock:
                    self._active.pop(me, None)
                    self._set_current()
                with self._qlock:
                    self._queued.discard(path)
                    self.progress["queued"] = len(self._queued)
                    if not self._queued and not self._active:
                        self.progress.update(state="idle", current=None, started=None)

    def index_file(self, path: str) -> int:
        p = Path(path)
        kind = media.kind_for(p)
        if kind is None:
            raise ValueError(f"Unsupported file type: {p.suffix}")
        folder = self._folder_for(str(p))
        st = p.stat()
        base = {
            "path": str(p), "folder_id": folder["id"] if folder else None, "kind": kind, "name": p.name,
            "ext": p.suffix.lower(), "size": st.st_size, "mtime": st.st_mtime, "status": "indexing", "error": None,
        }
        try:
            base["fingerprint"] = media.fingerprint(p)
        except OSError:
            base["fingerprint"] = None
        asset_id = self.db.upsert_asset(base)
        old = self.db.clear_segments(asset_id)
        self.vindex.remove(old)
        if self.semantic is not None:
            self.semantic.remove(old)
        ctx = {"asset_id": asset_id, "path": str(p), "name": p.name, "root": folder["path"] if folder else None}
        try:
            if kind == "video":
                self._index_video(ctx)
            elif kind == "image":
                self._index_image(ctx)
            elif kind == "audio":
                self._index_audio(ctx)
            else:
                self._index_template(ctx)
            meta = (self.db.asset(asset_id) or {}).get("meta") or {}
            meta = meta if isinstance(meta, dict) else {}
            meta["v"] = INDEX_VERSION
            extra = {}
            dl = self.db.download_for(str(p))
            if dl and dl.get("licence"):
                extra = {"license": dl["licence"], "source_url": dl.get("page_url")}
            self.db.update_asset(asset_id, status="indexed", indexed_at=time.time(), meta=meta, **extra)
        except Exception as exc:
            log.debug(traceback.format_exc())
            self.db.update_asset(asset_id, status="error", error=str(exc)[:500], indexed_at=time.time())
            raise
        if self.semantic is not None and self.semantic.ready:
            try:
                self.semantic.sync()
            except Exception as exc:
                log.warning("Meaning search update failed for %s: %s", p.name, exc)
        return asset_id

    def backfill(self) -> dict:
        done, requeued = 0, 0
        rows = self.db.query("SELECT id, path, kind, folder_id, name FROM assets WHERE status='indexed' AND captured_src IS NULL")
        for r in rows:
            p = r["path"]
            if not Path(p).exists():
                continue
            try:
                tags, img = None, None
                if r["kind"] in ("video", "audio") and media.ffmpeg_available():
                    tags = media.probe(p).get("tags")
                elif r["kind"] == "image":
                    img = media.open_image(p)
                md = metadata.collect(p, tags, img)
                self.db.update_asset(r["id"], **md)
                words = metadata.search_words(md)
                if words:
                    for sg in self.db.segments_for(r["id"]):
                        f = self.db.get_fts(sg["id"])
                        if f and words not in (f.get("folder") or ""):
                            self.db.put_fts(sg["id"], f["name"], f["caption"], f["tags"], f["transcript"], f"{f['folder']} {words}".strip())
                done += 1
            except Exception as exc:
                log.debug("Metadata backfill failed for %s: %s", p, exc)
        for r in self.db.query("SELECT id, path, meta FROM assets WHERE status='indexed' AND green_screen=1"):
            try:
                v = (json.loads(r["meta"] or "{}") or {}).get("v", 1)
            except (TypeError, ValueError):
                v = 1
            if v < INDEX_VERSION and Path(r["path"]).exists() and self.enqueue(r["path"], force=True):
                requeued += 1
        return {"metadata": done, "rechecked": requeued}

    def _thumb_path(self, asset_id: int, idx: int) -> Path:
        return self.settings.thumbs_dir / str(asset_id // 1000) / f"{asset_id}_{idx}.jpg"

    def _embed(self, images: list) -> np.ndarray | None:
        imgs = [i for i in images if i is not None]
        if not imgs:
            return None
        vecs = self.embedder.embed_images(imgs)
        return normalize(vecs.mean(axis=0))

    def _embed_groups(self, groups: list[list]) -> list[np.ndarray | None]:
        flat, owner = [], []
        for gi, g in enumerate(groups):
            for im in g:
                if im is not None:
                    flat.append(im)
                    owner.append(gi)
        out: list[np.ndarray | None] = [None] * len(groups)
        if not flat:
            return out
        vecs = self.embedder.embed_images(flat)
        owner_arr = np.asarray(owner)
        for gi in range(len(groups)):
            rows = vecs[owner_arr == gi]
            if len(rows):
                out[gi] = normalize(rows.mean(axis=0))
        return out

    def _describe(self, images: list, name: str, start: float = 0.0, end: float = 0.0, what: str | None = None):
        if not self.tf.available or not [i for i in images if i is not None]:
            return None
        return self._pool.submit(self.tf.caption_frames, images, name, start, end, what)

    @staticmethod
    def _result(fut, label: str):
        if fut is None:
            return None
        try:
            return fut.result()
        except Exception as exc:
            log.warning("%s failed: %s", label, exc)
            return None

    def _transcribe(self, path: str, duration: float) -> list[dict]:
        samples = media.extract_audio(path, 0, min(duration, 900) if duration else 900)
        return self.transcriber.transcribe(samples)

    def _write_fts(self, seg_id: int, ctx: dict, caption: str, tags: list[str], transcript: str = "") -> None:
        folder = (folder_tokens(ctx["path"], ctx.get("root")) + " " + ctx.get("meta_words", "")).strip()
        self.db.put_fts(seg_id, name_tokens(ctx["name"]), caption, " ".join(tags), transcript or "", folder)

    def _apply_metadata(self, ctx: dict, tags: dict | None = None, img=None) -> dict:
        md = metadata.collect(ctx["path"], tags, img)
        ctx["meta_words"] = metadata.search_words(md)
        self.db.update_asset(ctx["asset_id"], **md)
        return md

    def _index_video(self, ctx: dict) -> None:
        aid, path = ctx["asset_id"], ctx["path"]
        t0 = time.time()
        timing: dict[str, float] = {}

        def lap(name: str, since: float) -> float:
            now = time.time()
            timing[name] = now - since
            return now

        info = media.probe(path)
        if not info["has_video"]:
            self.db.update_asset(aid, kind="audio")
            return self._index_audio(ctx, info)
        duration = info["duration"] or 0.0
        self._apply_metadata(ctx, info.get("tags"))
        self.db.update_asset(aid, duration=duration, width=info["width"], height=info["height"], fps=info["fps"],
                             has_audio=int(info["has_audio"]), has_alpha=int(info["has_alpha"]),
                             meta={k: info[k] for k in ("vcodec", "acodec", "pix_fmt", "bit_rate")})
        t = time.time()
        asr = None
        if info["has_audio"] and self.transcriber.available:
            asr = self._aux.submit(self._transcribe, path, duration)
        shots = media.detect_shots(path, duration)
        t = lap("shots", t)
        k = max(1, int(self.settings.keyframes_per_shot))
        times = [media.keyframe_times(s, e, k) for s, e in shots]
        flat = [x for ts in times for x in ts]
        big = (info["width"] or 0) * (info["height"] or 0) >= 2560 * 1440
        frames = media.extract_frames(path, flat, workers=min(6, os.cpu_count() or 2) if big or media.cv2 is None else 1)
        t = lap("frames", t)
        groups, pos = [], 0
        for ts in times:
            groups.append([im for im in frames[pos : pos + len(ts)] if im is not None])
            pos += len(ts)
        pending = {}
        if self.tf.available:
            chosen = sorted(range(len(shots)), key=lambda i: shots[i][1] - shots[i][0], reverse=True)[: self.settings.max_captioned_shots]
            for i in sorted(chosen):
                fut = self._describe(groups[i], ctx["name"], shots[i][0], shots[i][1])
                if fut is not None:
                    pending[i] = fut
        base_tags = orientation_tags(info["width"], info["height"]) + ["video", "clip", "footage", "b-roll"]
        if info["has_alpha"]:
            base_tags += ["transparent", "alpha", "overlay"]
        segs = []
        for i, ((s, e), valid) in enumerate(zip(shots, groups)):
            thumb = None
            ratios = {"green": 0.0, "blue": 0.0, "green_border": 0.0, "blue_border": 0.0}
            if valid:
                mid = valid[len(valid) // 2]
                thumb = media.save_thumb(mid, self._thumb_path(aid, i))
                rs = [media.chroma_ratios(im) for im in valid]
                ratios = {key: float(np.mean([r[key] for r in rs])) for key in rs[0]}
            key = media.is_chroma_key(ratios)
            seg_tags = list(base_tags)
            if key:
                seg_tags += [f"{key} screen", "chroma key", "keyable", f"{key}screen"]
            sid = self.db.add_segment(aid, i, s, e, tags=seg_tags, thumb=thumb, green_ratio=ratios["green"])
            segs.append({"id": sid, "start": s, "end": e, "tags": seg_tags, "caption": None, "key": key})
        for sg, vec in zip(segs, self._embed_groups(groups)):
            if vec is not None:
                self.vindex.add(sg["id"], vec)
        t = lap("local", t)
        captioned_by = None
        for i, fut in pending.items():
            cap = self._result(fut, f"Describing shot {i + 1} of {ctx['name']}")
            if cap:
                sg = segs[i]
                sg["caption"] = cap
                if cap.get("background") in ("green screen", "blue screen") and not sg["key"]:
                    sg["tags"] += [cap["background"], "chroma key", "keyable"]
                captioned_by = self.tf.model("vision")
        t = lap("describe", t)
        captioned = [sg for sg in segs if sg["caption"]]
        if captioned and not any(sg["caption"].get("background") in ("green screen", "blue screen") for sg in captioned):
            for sg in segs:
                if sg["key"]:
                    sg["key"] = None
                    sg["tags"] = [x for x in sg["tags"] if x not in KEY_TAGS]
        transcript_segments: list[dict] = self._result(asr, f"Transcribing {ctx['name']}") or []
        t = lap("speech", t)
        all_tags: list[str] = []
        green_any = False
        for sg in segs:
            cap = sg["caption"]
            tags = list(sg["tags"]) + ((cap or {}).get("tags") or [])
            tags = list(dict.fromkeys(x for x in tags if x))
            text = " ".join(x["text"] for x in transcript_segments if x["end"] > sg["start"] and x["start"] < sg["end"])
            self.db.update_segment(sg["id"], caption=(cap or {}).get("description") or None, tags=tags, transcript=text or None,
                                   details=caption_details(cap))
            self._write_fts(sg["id"], ctx, caption_text(cap), tags, text)
            all_tags.extend(tags)
            green_any = green_any or bool(sg["key"]) or (cap or {}).get("background") in ("green screen", "blue screen")
        best = next((sg["caption"] for sg in sorted(segs, key=lambda x: x["end"] - x["start"], reverse=True) if sg["caption"]), None)
        counts: dict[str, int] = {}
        for x in all_tags:
            counts[x] = counts.get(x, 0) + 1
        top_tags = [x for x, _ in sorted(counts.items(), key=lambda kv: -kv[1])][:30]
        self.db.update_asset(aid, caption=(best or {}).get("description"), tags=top_tags, green_screen=int(green_any),
                             transcript=" ".join(x["text"] for x in transcript_segments) or None,
                             captioned_by=captioned_by,
                             meta={**{k: info[k] for k in ("vcodec", "acodec", "pix_fmt", "bit_rate")}, "shots": len(segs),
                                   "transcript_segments": transcript_segments[:400],
                                   "timing": {k: round(v, 2) for k, v in timing.items()}})
        log.info("Indexed %s in %.1f s: %d shots, %d described in parallel (%s)", ctx["name"], time.time() - t0, len(segs),
                 len(captioned), ", ".join(f"{k} {v:.1f}s" for k, v in timing.items()))

    def _index_image(self, ctx: dict) -> None:
        aid, path = ctx["asset_id"], ctx["path"]
        img = media.open_image(path)
        alpha = media.image_has_alpha(img)
        rgb = media.to_rgb(img)
        w, h = rgb.size
        thumb = media.save_thumb(rgb, self._thumb_path(aid, 0))
        ratios = media.chroma_ratios(rgb)
        key = media.is_chroma_key(ratios)
        tags = orientation_tags(w, h) + ["image", "photo", "still"]
        if alpha:
            tags += ["transparent", "png", "cutout", "overlay"]
        if key:
            tags += [f"{key} screen", "chroma key", "keyable"]
        fut = self._describe([rgb], ctx["name"], what="image")
        self._apply_metadata(ctx, None, img)
        vec = self._embed([rgb])
        cap = self._result(fut, f"Describing {ctx['name']}")
        if cap:
            if cap.get("background") in ("green screen", "blue screen"):
                key = key or cap["background"].split()[0]
            elif key:
                key = None
                tags = [t for t in tags if t not in KEY_TAGS]
            tags += cap.get("tags") or []
        tags = list(dict.fromkeys(tags))
        sid = self.db.add_segment(aid, 0, 0, 0, caption=(cap or {}).get("description"), tags=tags, thumb=thumb, green_ratio=ratios["green"])
        if cap:
            self.db.update_segment(sid, details=caption_details(cap))
        if vec is not None:
            self.vindex.add(sid, vec)
        self._write_fts(sid, ctx, caption_text(cap), tags)
        self.db.update_asset(aid, width=w, height=h, has_alpha=int(alpha), green_screen=int(bool(key)), tags=tags,
                             caption=(cap or {}).get("description"), captioned_by=self.tf.model("vision") if cap else None,
                             meta={"mode": img.mode, "format": img.format})

    def _index_audio(self, ctx: dict, info: dict | None = None) -> None:
        aid, path = ctx["asset_id"], ctx["path"]
        info = info or media.probe(path)
        duration = info["duration"] or 0.0
        self._apply_metadata(ctx, info.get("tags"))
        sr = 16000
        samples = media.extract_audio(path, 0, min(duration, 180) if duration else 180, sr)
        if not duration:
            duration = len(samples) / sr
        feat = audiofx.features(samples, sr)
        tags = audiofx.tags_for({**feat, "duration": duration}) + ["audio", "sound"]
        thumb = media.waveform_image(samples, self._thumb_path(aid, 0))
        desc = None
        if self.tf.available:
            a, b = media.loudest_window(samples, sr, 10.0)
            excerpt = samples[a:b]
            desc = self.tf.describe_audio(media.wav_bytes(excerpt, sr), ctx["name"], len(excerpt) / sr, duration, feat,
                                          folder=folder_tokens(ctx["path"], ctx.get("root")), local_tags=tags)
        described_by = None
        if desc:
            described_by = desc.pop("_model", None) or self.tf.model("omni")
            if desc.pop("_source", None) == "analysis":
                described_by = f"{described_by} (from audio analysis)"
            tags += desc.get("tags") or []
            if desc.get("kind"):
                tags.append(desc["kind"])
        transcript_segments: list[dict] = []
        wants_asr = self.transcriber.available and (
            (desc and desc.get("kind") in ("speech", "mixed")) or (not desc and duration > 8 and "music" not in tags)
        )
        if wants_asr:
            try:
                full = media.extract_audio(path, 0, min(duration, 900), sr) if duration > 180 else samples
                transcript_segments = self.transcriber.transcribe(full, sr)
            except Exception as exc:
                log.warning("Transcription failed for %s: %s", path, exc)
        if transcript_segments:
            tags += ["speech", "voice", "dialogue"]
        tags = list(dict.fromkeys(t for t in tags if t))
        text = " ".join(t["text"] for t in transcript_segments)
        sid = self.db.add_segment(aid, 0, 0, duration, caption=(desc or {}).get("description"), tags=tags, thumb=thumb,
                                  transcript=text or None)
        if desc:
            self.db.update_segment(sid, details=caption_details(desc))
        self._write_fts(sid, ctx, caption_text(desc), tags, text)
        self.db.update_asset(aid, duration=duration, has_audio=1, caption=(desc or {}).get("description"), tags=tags,
                             transcript=text or None, captioned_by=described_by,
                             meta={"features": feat, "audio": desc, "acodec": info.get("acodec"),
                                   "transcript_segments": transcript_segments[:400]})

    def _index_template(self, ctx: dict) -> None:
        aid, path = ctx["asset_id"], ctx["path"]
        ext = Path(path).suffix.lower()
        self._apply_metadata(ctx)
        tags = ["template"] + TEMPLATE_TAGS.get(ext, [])
        preview, source = media.template_preview(path)
        thumb, cap, vec = None, None, None
        if preview is not None:
            fut = self._describe([preview], ctx["name"], what="design template preview")
            thumb = media.save_thumb(preview, self._thumb_path(aid, 0))
            vec = self._embed([preview])
            cap = self._result(fut, f"Describing {ctx['name']}")
        if cap:
            tags += cap.get("tags") or []
        tags = list(dict.fromkeys(tags))
        sid = self.db.add_segment(aid, 0, 0, 0, caption=(cap or {}).get("description"), tags=tags, thumb=thumb)
        if cap:
            self.db.update_segment(sid, details=caption_details(cap))
        if vec is not None:
            self.vindex.add(sid, vec)
        self._write_fts(sid, ctx, caption_text(cap), tags)
        self.db.update_asset(aid, caption=(cap or {}).get("description"), tags=tags,
                             captioned_by=self.tf.model("vision") if cap else None, meta={"preview": source})
