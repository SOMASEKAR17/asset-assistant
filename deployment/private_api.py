"""Private uploads and owner-funded API calls; no arbitrary URL/file proxy."""
import json
import os
from contextlib import contextmanager
from urllib.parse import unquote, urlparse

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route
from caa.services import Services
from caa.search import result_for_asset
from caa.asr import Transcriber
from cloud import ServerSettings, secret
from uploads import COOKIE, EXTENSIONS, MAX_FILE, TTL


def routes(safe_file, public):
    def store(request):
        return request.app.state.uploads

    def session(request):
        return store(request).resolve(request.cookies.get(COOKIE))

    def intent(request):
        # Custom header prevents cross-origin form uploads. No CORS is enabled.
        origin = request.headers.get('origin')
        if request.headers.get('x-upload-intent') != '1' or (origin and urlparse(origin).netloc != request.headers.get('host')):
            raise HTTPException(403, 'Use the upload controls on this website')

    def refs(value):
        if isinstance(value, dict):
            return {k: refs(v) for k,v in value.items()}
        if isinstance(value, list):
            return [refs(v) for v in value]
        if isinstance(value, str) and value.startswith(('/api/thumb/', '/api/media/')):
            return value.replace('/api/', '/api/private/', 1)
        return value

    @contextmanager
    def engine(request, owner):
        base = request.app.state.services
        settings = ServerSettings(home=store(request).directory(owner['id']) / 'data', privacy_mode='local',
                                  asr_enabled=False, semantic_search=False)
        settings.ensure_dirs()
        service = Services(settings, embedder=base.embedder, text_embedder=base.text_embedder,
                           transcriber=Transcriber(), start_worker=False, watch=False)
        try:
            yield service
        finally:
            service.db.close()

    def start(request):
        intent(request)
        token = request.cookies.get(COOKIE)
        try:
            owner = store(request).resolve(token)
        except HTTPException:
            token, owner = store(request).create()
        response = JSONResponse({'expires': owner['expires'], 'max_file_bytes': MAX_FILE,
                                 'session_bytes': 200*1024**2, 'allowed': sorted(EXTENSIONS),
                                 'captioning': bool(secret('NEBIUS_API_KEY')), 'web_search': bool(secret('TAVILY_API_KEY'))})
        # Never extend storage expiry by refreshing a cookie.
        import time
        response.set_cookie(COOKIE, token, max_age=max(0, int(owner['expires']-time.time())),
                            httponly=True, secure=os.environ.get('DEMO_SECURE_COOKIE', '1') == '1', samesite='strict')
        return response

    async def upload(request):
        intent(request)
        owner = session(request)
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError:
            raise HTTPException(400, 'Invalid upload length')
        if length > MAX_FILE or length < 0:
            raise HTTPException(413, 'Each file must be 50 MB or smaller')
        name = unquote(request.headers.get('x-file-name', ''))
        folder = request.query_params.get('folder', 'My uploads')
        job, path = store(request).reserve(owner, name, folder)
        size = 0
        try:
            with anyio.fail_after(60):
                async with await anyio.open_file(path, 'wb') as output:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_FILE:
                            raise HTTPException(413, 'Each file must be 50 MB or smaller')
                        await output.write(chunk)
            if size == 0:
                raise HTTPException(400, 'The file is empty')
            # Check expiry again: a session cannot finish an upload after expiry.
            session(request)
            store(request).finish(job, size)
        except BaseException as error:
            store(request).cancel(job, path)
            if isinstance(error, TimeoutError):
                raise HTTPException(408, 'Upload timed out. Try a smaller file.')
            raise
        return JSONResponse({'status': 'queued', 'name': name, 'folder': folder}, 202)

    def jobs(request):
        owner = session(request)
        return JSONResponse({'files': store(request).listing(owner), 'expires': owner['expires']})

    def assets(request):
        owner = session(request)
        try:
            offset = max(0, min(10000, int(request.query_params.get('offset', 0))))
        except ValueError:
            raise HTTPException(400, 'Invalid offset')
        kind = request.query_params.get('kind') or None
        if kind not in (None, 'video', 'audio', 'image'):
            raise HTTPException(400, 'Invalid media type')
        with engine(request, owner) as service:
            rows = service.db.list_assets(kind=kind, offset=offset, limit=25, status='indexed')
            result = [result_for_asset(service.db, a) for a in rows[:24]]
        return JSONResponse({'results': refs(public(result)), 'has_more': len(rows)>24})

    async def search(request):
        owner = session(request)
        query = request.query_params.get('q', '').strip()
        kind = request.query_params.get('kind') or None
        if not query or len(query)>300 or kind not in (None, 'video','image','audio'):
            raise HTTPException(400, 'Invalid search')
        def work():
            with engine(request, owner) as service:
                return service.search.search(query, kind=kind, limit=24, use_llm=False)
        result = await anyio.to_thread.run_sync(work, limiter=request.app.state.search_slots)
        return JSONResponse(refs(public(result)))

    def asset(request):
        owner = session(request)
        with engine(request, owner) as service:
            item = service.db.asset(request.path_params['aid'])
            if not item or item['status'] != 'indexed':
                raise HTTPException(404, 'Asset not found')
            segments = service.db.segments_for(item['id'])
        return JSONResponse(refs(public({'asset':item, 'segments':segments, 'media_url':f"/api/media/{item['id']}"})))

    def media(request):
        owner = session(request)
        with engine(request, owner) as service:
            item = service.db.asset(request.path_params['aid'])
            if not item or item['status'] != 'indexed':
                raise HTTPException(404, 'Asset not found')
            path = safe_file(item['path'], store(request).directory(owner['id']) / 'files')
            if path.suffix.lower() not in EXTENSIONS:
                raise HTTPException(415, 'Unsupported media')
        return FileResponse(path, headers={'Cache-Control':'private, no-store'})

    def thumb(request):
        owner = session(request)
        with engine(request, owner) as service:
            segment = service.db.segment(request.path_params['sid'])
            if not segment or not segment.get('thumb'):
                raise HTTPException(404, 'Thumbnail not found')
            path = safe_file(segment['thumb'], service.settings.thumbs_dir)
        return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control':'private, no-store'})

    async def similar(request):
        owner = session(request)
        def work():
            with engine(request, owner) as service:
                return service.search.similar(request.path_params['sid'], 24)
        result = await anyio.to_thread.run_sync(work, limiter=request.app.state.search_slots)
        return JSONResponse(refs(public(result)))

    async def web_search(request):
        intent(request)
        owner = session(request)
        if not secret('TAVILY_API_KEY'):
            raise HTTPException(503, 'Web search is not configured')
        # No caller-controlled URLs, provider addresses or arbitrary API proxying.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>2048:
                raise HTTPException(413, 'Search request too large')
        try:
            query = json.loads(body).get('query', '').strip()
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(400, 'Invalid search')
        if not query or len(query)>300:
            raise HTTPException(400, 'Enter 1–300 characters')
        store(request).cloud_budget(owner['id'])
        def work():
            from caa.tavily import Tavily
            settings = ServerSettings(privacy_mode='standard', request_timeout=20)
            data = Tavily(settings).search(query, max_results=5, search_depth='basic')
            return [{'title':str(r.get('title',''))[:200], 'url':str(r.get('url',''))[:1000],
                     'snippet':str(r.get('content',''))[:500]} for r in data.get('results', [])[:5]]
        try:
            result = await anyio.to_thread.run_sync(work, limiter=request.app.state.cloud_slots)
        except Exception:
            raise HTTPException(502, 'Web search is temporarily unavailable')
        return JSONResponse({'results':result})

    return [Route('/api/private/session', start, methods=['POST']), Route('/api/private/upload', upload, methods=['POST']),
            Route('/api/private/jobs', jobs), Route('/api/private/assets', assets), Route('/api/private/search', search),
            Route('/api/private/assets/{aid:int}', asset), Route('/api/private/media/{aid:int}', media),
            Route('/api/private/thumb/{sid:int}', thumb), Route('/api/private/similar/{sid:int}', similar),
            Route('/api/cloud/search', web_search, methods=['POST'])]
