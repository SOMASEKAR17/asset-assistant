"""Persistent anonymous sessions, upload quotas, expiry and an isolated job worker."""
from __future__ import annotations
import hashlib
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from starlette.exceptions import HTTPException

MAX_FILE = 50 * 1024 * 1024
TTL = 24 * 60 * 60
EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.mp4', '.webm', '.mp3', '.wav'}
COOKIE = 'caa_upload_session'


class UploadStore:
    def __init__(self, root, run_jobs=True):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.root / 'sessions.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA foreign_keys=ON;
          CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, expires REAL);
          CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, sid TEXT REFERENCES sessions(id) ON DELETE CASCADE,
            name TEXT, folder TEXT, path TEXT, size INTEGER, status TEXT, created REAL);
          CREATE TABLE IF NOT EXISTS usage(sid TEXT, kind TEXT, ts REAL);
        ''')
        # Interrupted work is not retried automatically, avoiding duplicate paid calls.
        self.db.execute("UPDATE jobs SET status='failed' WHERE status IN ('receiving','processing')")
        self.db.commit()
        self.stop = threading.Event()
        self.process = None
        self.thread = None
        self.janitor = None
        self.cleanup()
        if run_jobs:
            self.janitor = threading.Thread(target=self.expire_loop, daemon=True)
            self.janitor.start()
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()

    def directory(self, sid):
        if not re.fullmatch('[a-f0-9]{64}', sid):
            raise HTTPException(401, 'Upload session required')
        return self.root / sid

    def resolve(self, token):
        if not token or len(token) > 100:
            raise HTTPException(401, 'Start an upload session first')
        sid = hashlib.sha256(token.encode()).hexdigest()
        with self.lock:
            row = self.db.execute('SELECT * FROM sessions WHERE id=? AND expires>?', (sid, time.time())).fetchone()
        if row is None:
            raise HTTPException(401, 'Your upload session expired. Start a new one.')
        return dict(row)

    def create(self):
        with self.lock:
            now = time.time()
            if self.db.execute('SELECT count(*) FROM sessions WHERE expires>?', (now,)).fetchone()[0] >= 100:
                raise HTTPException(429, 'Upload sessions are full. Please try later.')
            self._budget('new-session', 'session', 200, 60, 200)
            token = secrets.token_urlsafe(32)
            sid = hashlib.sha256(token.encode()).hexdigest()
            self.db.execute('INSERT INTO sessions VALUES (?,?)', (sid, now + TTL))
            self.db.commit()
            return token, {'id': sid, 'expires': now + TTL}

    def _budget(self, sid, kind, per_session, hourly, daily):
        now = time.time()
        own = self.db.execute('SELECT count(*) FROM usage WHERE sid=? AND kind=? AND ts>?', (sid, kind, now-TTL)).fetchone()[0]
        hour = self.db.execute('SELECT count(*) FROM usage WHERE kind=? AND ts>?', (kind, now-3600)).fetchone()[0]
        day = self.db.execute('SELECT count(*) FROM usage WHERE kind=? AND ts>?', (kind, now-TTL)).fetchone()[0]
        if own >= per_session or hour >= hourly or day >= daily:
            raise HTTPException(429, 'The demo usage limit has been reached. Please try later.')
        self.db.execute('INSERT INTO usage VALUES (?,?,?)', (sid, kind, now))
        self.db.commit()

    def cloud_budget(self, sid):
        with self.lock:
            self._budget(sid, 'web-search', 10, 30, 100)

    def reserve(self, session, name, folder):
        sid = session['id']
        if not re.fullmatch(r'[\w .()\-]{1,100}', name) or name.startswith('.') or '..' in name:
            raise HTTPException(400, 'Use a simple filename without paths')
        if Path(name).suffix.lower() not in EXTENSIONS:
            raise HTTPException(415, 'Use JPG, PNG, WebP, MP4, WebM, MP3 or WAV')
        if not re.fullmatch(r'[\w \-]{1,50}', folder):
            raise HTTPException(400, 'Folder names may contain letters, numbers, spaces and hyphens')
        with self.lock:
            if self.db.execute("SELECT count(*) FROM jobs WHERE status IN ('receiving','queued','processing')").fetchone()[0] >= 4:
                raise HTTPException(429, 'The upload queue is full. Try again shortly.')
            used = self.db.execute('SELECT coalesce(sum(size),0) FROM jobs WHERE sid=?', (sid,)).fetchone()[0]
            total = self.db.execute('SELECT coalesce(sum(size),0) FROM jobs').fetchone()[0]
            if used + MAX_FILE > 200 * 1024**2 or total + MAX_FILE > 5 * 1024**3:
                raise HTTPException(413, 'Upload storage quota reached')
            self._budget(sid, 'upload', 10, 20, 100)
            job = secrets.token_hex(16)
            folder_id = hashlib.sha256(folder.encode()).hexdigest()[:16]
            path = self.directory(sid) / 'files' / folder_id / job / name
            path.parent.mkdir(parents=True, exist_ok=True)
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)',
                            (job, sid, name, folder, str(path), MAX_FILE, 'receiving', time.time()))
            self.db.commit()
            return job, path

    def finish(self, job, size):
        with self.lock:
            self.db.execute("UPDATE jobs SET size=?,status='queued' WHERE id=? AND status='receiving'", (size, job))
            self.db.commit()

    def cancel(self, job, path):
        path.unlink(missing_ok=True)
        with self.lock:
            self.db.execute('DELETE FROM jobs WHERE id=?', (job,))
            self.db.commit()

    def listing(self, session):
        with self.lock:
            return [dict(r) for r in self.db.execute('SELECT name,folder,size,status FROM jobs WHERE sid=? ORDER BY created DESC', (session['id'],))]

    def cleanup(self):
        with self.lock:
            now = time.time()
            rows = list(self.db.execute('SELECT id FROM sessions WHERE expires<=?', (now,)))
            for row in rows:
                directory = self.directory(row['id'])
                # Only generated session directories under this store are removed.
                if directory.is_dir():
                    try:
                        shutil.rmtree(directory)
                    except OSError:
                        # A currently open file may delay deletion; access is already denied.
                        continue
                self.db.execute('DELETE FROM sessions WHERE id=?', (row['id'],))
            self.db.execute('DELETE FROM usage WHERE ts<?', (now-TTL,))
            self.db.commit()

    def expire_loop(self):
        while not self.stop.wait(30):
            self.cleanup()

    def kill_worker(self):
        process = self.process
        if process and process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()

    def loop(self):
        while not self.stop.is_set():
            self.cleanup()
            with self.lock:
                job = self.db.execute("SELECT j.*,s.expires FROM jobs j JOIN sessions s ON j.sid=s.id WHERE j.status='queued' ORDER BY j.created LIMIT 1").fetchone()
                if job:
                    self.db.execute("UPDATE jobs SET status='processing' WHERE id=?", (job['id'],))
                    self.db.commit()
            if not job:
                self.stop.wait(2)
                continue
            success = False
            try:
                options = {'start_new_session': True} if os.name != 'nt' else {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
                with self.lock:
                    if self.stop.is_set():
                        break
                    self.process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('upload_worker.py')),
                        str(self.directory(job['sid']) / 'data'), job['path']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)
                success = self.process.wait(timeout=max(1, min(300, job['expires']-time.time()))) == 0
            except (subprocess.TimeoutExpired, OSError):
                self.kill_worker()
            finally:
                self.process = None
            with self.lock:
                self.db.execute('UPDATE jobs SET status=? WHERE id=?', ('ready' if success else 'failed', job['id']))
                self.db.commit()
        self.cleanup()

    def close(self):
        with self.lock:
            self.stop.set()
        self.kill_worker()
        if self.thread:
            self.thread.join(timeout=10)
        if self.janitor:
            self.janitor.join(timeout=5)
        with self.lock:
            self.db.close()
