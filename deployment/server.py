"""Public sample library plus isolated private uploads. Never mounts desktop APIs."""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor' / 'engine'))

import anyio
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from caa.config import Settings
from caa.search import result_for_asset
from caa.services import Services
from uploads import UploadStore
from private_api import routes as private_routes


def safe_file(raw, root):
    candidate = Path(raw).resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise HTTPException(404, 'Sample media not found')
    return candidate


def public(value):
    """Do not expose server paths, GPS, device IDs or error diagnostics."""
    private = {'path', 'thumb', 'folder', 'folder_id', 'lat', 'lon', 'device', 'meta', 'error', 'details'}
    if isinstance(value, dict):
        result = {k: public(v) for k, v in value.items() if k not in private}
        if isinstance(value.get('thumb'), str) and value['thumb'].startswith('/api/thumb/'):
            result['thumb'] = value['thumb']
        return result
    if isinstance(value, list):
        return [public(v) for v in value]
    return value


class Guard:
    """Global bounded budget; intentionally ignores spoofable forwarded IPs.

    Single process by design. Put per-client limits at your trusted ingress.
    Search concurrency is separately capped below.
    """
    def __init__(self, app, limit=240):
        self.app, self.limit = app, limit
        self.tokens, self.updated = float(limit), time.monotonic()
        self.lock = threading.Lock()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        allowed_post = path in {'/api/private/session', '/api/private/upload', '/api/cloud/search'}
        if scope['method'] not in ('GET', 'HEAD') and not (scope['method'] == 'POST' and allowed_post):
            return await JSONResponse({'error': 'This operation is not available in the public sandbox.'}, 405)(scope, receive, send)
        if len(scope.get('query_string', b'')) > 2048:
            return await JSONResponse({'error': 'Query too long'}, 414)(scope, receive, send)
        if path.startswith('/api/') and not path.startswith(('/api/media/', '/api/thumb/')):
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.limit, self.tokens + (now-self.updated) * self.limit / 60)
                self.updated = now
                allowed = self.tokens >= 1
                if allowed:
                    self.tokens -= 1
            if not allowed:
                return await JSONResponse({'error': 'The demo is busy. Try again shortly.'}, 429,
                                          headers={'Retry-After': '10'})(scope, receive, send)

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                headers = list(message.get('headers', []))
                if path.startswith(('/api/private/', '/api/cloud/')):
                    headers = [(k,v) for k,v in headers if k.lower() != b'cache-control']
                    headers.append((b'cache-control', b'private, no-store'))
                headers += [(b'x-content-type-options', b'nosniff'), (b'referrer-policy', b'no-referrer'),
                            (b'content-security-policy', b"default-src 'self'; img-src 'self'; media-src 'self'; style-src 'self'; script-src 'self'; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
                            (b'permissions-policy', b'camera=(), microphone=(), geolocation=()')]
                message['headers'] = headers
            await send(message)
        await self.app(scope, receive, secure_send)


def create_app(services=None, library=None, home=None, hosts=None, rate_limit=240, upload_root=None, run_jobs=True):
    library = Path(library or os.environ.get('DEMO_LIBRARY', ROOT / 'library')).resolve()
    home = Path(home or os.environ.get('DEMO_HOME', ROOT / '.preview' / 'data')).resolve()

    @asynccontextmanager
    async def lifespan(app):
        if services is None:
            seed = Path(os.environ.get('DEMO_SEED', ROOT / 'seed'))
            home.mkdir(parents=True, exist_ok=True)
            if seed.exists():
                # The seed is an operator-supplied, checkpointed SQLite index.
                for name in ('library.db', 'thumbs'):
                    source = seed / name
                    if source.is_dir():
                        shutil.copytree(source, home / name, dirs_exist_ok=True)
                    elif source.is_file():
                        shutil.copy2(source, home / name)
            ml = os.environ.get('DEMO_ML', '1') == '1'
            # Explicit settings avoid loading desktop .env/settings or using cloud APIs.
            settings = Settings(home=home, privacy_mode='local', asr_enabled=False,
                                embed_backend='auto' if ml else 'fallback', semantic_search=ml,
                                nemotron_search=False)
            settings.ensure_dirs()
            app.state.services = Services(settings, start_worker=False, watch=False)
        else:
            app.state.services = services
        app.state.search_slots = anyio.CapacityLimiter(2)
        app.state.cloud_slots = anyio.CapacityLimiter(1)
        app.state.uploads = UploadStore(upload_root or os.environ.get('DEMO_UPLOADS', home.parent / 'uploads'), run_jobs=run_jobs)
        try:
            yield
        finally:
            app.state.uploads.close()
            if services is None:
                app.state.services.db.close()

    async def health(request):
        return JSONResponse({'ok': True, 'mode': 'private-uploads'})

    def status(request):
        s = request.app.state.services
        return JSONResponse({'library': s.db.stats(), 'mode': 'private-uploads',
                             'meaning': s.semantic.ready, 'visual': s.embedder.supports_text})

    def bounded(request, name, default, maximum):
        try:
            return max(0, min(maximum, int(request.query_params.get(name, default))))
        except ValueError:
            raise HTTPException(400, 'Invalid number')

    def kind(request):
        value = request.query_params.get('kind') or None
        if value not in (None, 'video', 'image', 'audio', 'template'):
            raise HTTPException(400, 'Invalid media type')
        return value

    def assets(request):
        db = request.app.state.services.db
        offset = bounded(request, 'offset', 0, 10000)
        rows = db.list_assets(kind=kind(request), offset=offset, limit=25, status='indexed')
        return JSONResponse({'results': public([result_for_asset(db, a) for a in rows[:24]]),
                             'has_more': len(rows) > 24})

    async def search(request):
        query = request.query_params.get('q', '').strip()
        if not query or len(query) > 300:
            raise HTTPException(400, 'Enter a search of 1–300 characters')
        selected = kind(request)
        s = request.app.state.services
        result = await anyio.to_thread.run_sync(
            lambda: s.search.search(query, kind=selected, limit=24, use_llm=False),
            limiter=request.app.state.search_slots)
        return JSONResponse(public(result))

    def asset(request):
        db = request.app.state.services.db
        a = db.asset(request.path_params['aid'])
        if not a or a['status'] != 'indexed':
            raise HTTPException(404, 'Asset not found')
        segments = db.segments_for(a['id'])
        for segment in segments:
            segment['thumb_url'] = f"/api/thumb/{segment['id']}" if segment.get('thumb') else None
        return JSONResponse(public({'asset': a, 'segments': segments, 'media_url': f"/api/media/{a['id']}"}))

    def media(request):
        a = request.app.state.services.db.asset(request.path_params['aid'])
        if not a or a['status'] != 'indexed' or a['kind'] not in ('video', 'image', 'audio'):
            raise HTTPException(404, 'Media not found')
        path = safe_file(a['path'], library)
        # Never serve active document formats such as HTML or SVG inline.
        if path.suffix.lower() not in {'.mp4','.webm','.mov','.m4v','.jpg','.jpeg','.png','.webp','.gif','.mp3','.wav','.ogg','.flac','.m4a','.aac'}:
            raise HTTPException(415, 'Preview format not supported')
        return FileResponse(path, headers={'Cache-Control': 'public, max-age=3600'})

    def thumb(request):
        sg = request.app.state.services.db.segment(request.path_params['sid'])
        if not sg or not sg.get('thumb'):
            raise HTTPException(404, 'Thumbnail not found')
        path = safe_file(sg['thumb'], home / 'thumbs')
        return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'public, max-age=3600'})

    async def similar(request):
        s = request.app.state.services
        sid = request.path_params['sid']
        if not s.db.segment(sid):
            raise HTTPException(404, 'Shot not found')
        result = await anyio.to_thread.run_sync(lambda: s.search.similar(sid, 24), limiter=request.app.state.search_slots)
        return JSONResponse(public(result))

    async def error(request, exc):
        return JSONResponse({'error': str(exc.detail)}, status_code=exc.status_code)

    routes = [Route('/healthz', health), Route('/api/status', status), Route('/api/assets', assets),
              Route('/api/search', search), Route('/api/assets/{aid:int}', asset),
              Route('/api/media/{aid:int}', media), Route('/api/thumb/{sid:int}', thumb),
              Route('/api/similar/{sid:int}', similar)]
    routes += private_routes(safe_file, public)
    routes.append(Mount('/', app=StaticFiles(directory=ROOT / 'site', html=True)))
    return Starlette(routes=routes, lifespan=lifespan, exception_handlers={HTTPException: error}, middleware=[
        Middleware(TrustedHostMiddleware, allowed_hosts=hosts or os.environ.get('DEMO_ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver').split(',')),
        Middleware(Guard, limit=rate_limit)])


app = create_app()
