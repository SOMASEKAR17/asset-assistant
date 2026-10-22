from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from . import media

log = logging.getLogger("caa.watcher")

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except ImportError:
    Observer = None
    FileSystemEventHandler = object


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "FolderWatcher"):
        super().__init__()
        self.w = watcher

    def on_created(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.w.touch(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self.w.gone(event.src_path)
            self.w.touch(event.dest_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self.w.gone(event.src_path)


class FolderWatcher:
    def __init__(self, indexer, db, debounce: float = 3.0, poll_interval: float = 120.0):
        self.indexer = indexer
        self.db = db
        self.debounce = debounce
        self.poll_interval = poll_interval
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._observer = None
        self._watched: dict[str, object] = {}
        self.state = "stopped"

    def start(self) -> None:
        self._stop.clear()
        if Observer is not None:
            self._observer = Observer()
            self._observer.start()
            self.state = "watching"
        else:
            self.state = "polling"
        self.sync()
        threading.Thread(target=self._loop, name="caa-watcher", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            try:
                self._observer.stop()
            except Exception:
                pass
        self.state = "stopped"

    def sync(self) -> None:
        if self._observer is None:
            return
        wanted = {f["path"] for f in self.db.folders() if f["enabled"] and Path(f["path"]).exists()}
        for path in list(self._watched):
            if path not in wanted:
                try:
                    self._observer.unschedule(self._watched.pop(path))
                except Exception:
                    pass
        for path in wanted - set(self._watched):
            try:
                self._watched[path] = self._observer.schedule(_Handler(self), path, recursive=True)
            except Exception as exc:
                log.warning("Cannot watch %s: %s", path, exc)

    def touch(self, path: str) -> None:
        if media.kind_for(path) is None or Path(path).name.startswith((".", "~$")):
            return
        with self._lock:
            self._pending[path] = time.time()

    def gone(self, path: str) -> None:
        with self._lock:
            self._pending.pop(path, None)
        if media.kind_for(path) is not None:
            self.indexer.remove_path(path)

    def _loop(self) -> None:
        last_poll = time.time()
        while not self._stop.wait(1.0):
            now = time.time()
            ready = []
            with self._lock:
                for p, t in list(self._pending.items()):
                    if now - t >= self.debounce:
                        ready.append(p)
                        del self._pending[p]
            for p in ready:
                if Path(p).exists() and not self.indexer.is_current(p):
                    self.indexer.enqueue(p)
            if self._observer is None and now - last_poll >= self.poll_interval:
                last_poll = now
                try:
                    self.indexer.scan()
                except Exception as exc:
                    log.warning("Poll scan failed: %s", exc)
