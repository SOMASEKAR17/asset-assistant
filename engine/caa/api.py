from __future__ import annotations

import logging
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from . import __version__, media
from .config import PRIVACY_MODES
from .nemotron import TokenFactoryError
from .search import result_for_asset
from .services import Services
from .sources import SITES, SourceError, identify
from .tavily import TavilyError

log = logging.getLogger("caa.api")

for ext, mt in ((".js", "text/javascript"), (".mjs", "text/javascript"), (".css", "text/css"), (".svg", "image/svg+xml"),
                (".webp", "image/webp"), (".mp4", "video/mp4"), (".webm", "video/webm"), (".mov", "video/quicktime"),
                (".m4v", "video/mp4"), (".mp3", "audio/mpeg"), (".wav", "audio/wav"), (".m4a", "audio/mp4"),
                (".ogg", "audio/ogg"), (".flac", "audio/flac"), (".aac", "audio/aac"), (".opus", "audio/ogg"),
                (".ttf", "font/ttf"), (".woff2", "font/woff2")):
    mimetypes.add_type(mt, ext)

FEEDBACK_ACTIONS = {"use", "like", "dismiss", "reject", "preview"}


def ui_dir() -> Path:
    env = os.environ.get("CAA_UI_DIR")
    if env:
        return Path(env)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and (Path(meipass) / "ui").exists():
        return Path(meipass) / "ui"
    return Path(__file__).resolve().parents[2] / "ui"


def _int(v, default: int, lo: int = 0, hi: int = 10_000) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def create_app(services: Services) -> Starlette:
    s = services

    def status(request: Request):
        return JSONResponse({"version": __version__, **s.status()})

    def folders(request: Request):
        return JSONResponse({"folders": s.db.folders()})

    async def add_folder(request: Request):
        body = await request.json()
        raw = str(body.get("path") or "").strip().strip('"')
        if not raw:
            raise HTTPException(400, "path is required")
        p = Path(os.path.expandvars(raw)).expanduser()
        if not p.exists() or not p.is_dir():
            raise HTTPException(400, f"Folder not found: {p}")
        kind = "drive-desktop" if "google drive" in str(p).lower() or "my drive" in str(p).lower() else "local"
        f = s.db.add_folder(str(p.resolve()), kind)
        if s.watcher:
            s.watcher.sync()
        queued = s.indexer.scan(f["id"])
        return JSONResponse({"folder": f, "queued": queued})

    def remove_folder(request: Request):
        fid = _int(request.path_params["fid"], -1)
        for a in s.db.query("SELECT id FROM assets WHERE folder_id=?", (fid,)):
            s.indexer.remove_asset(a["id"])
        s.db.remove_folder(fid)
        if s.watcher:
            s.watcher.sync()
        return JSONResponse({"ok": True})

    def rescan(request: Request):
        fid = request.path_params.get("fid")
        n = s.indexer.scan(_int(fid, -1) if fid else None, retry_errors=True)
        return JSONResponse({"queued": n})

    def search(request: Request):
        qp = request.query_params
        gs = qp.get("gs")
        res = s.search.search(qp.get("q", ""), kind=qp.get("kind") or None, limit=_int(qp.get("limit"), 40, 1, 200),
                              use_llm=qp.get("llm", "1") != "0",
                              green_screen=True if gs in ("1", "true") else None)
        return JSONResponse(res)

    def assets(request: Request):
        qp = request.query_params
        rows = s.db.list_assets(kind=qp.get("kind") or None, offset=_int(qp.get("offset"), 0), limit=_int(qp.get("limit"), 60, 1, 500),
                                status=qp.get("status") or None)
        return JSONResponse({"results": [result_for_asset(s.db, a) for a in rows]})

    def asset(request: Request):
        aid = _int(request.path_params["aid"], -1)
        a = s.db.asset(aid)
        if not a:
            raise HTTPException(404, "Asset not found")
        segs = s.db.segments_for(aid)
        for sg in segs:
            sg["thumb_url"] = f"/api/thumb/{sg['id']}" if sg.get("thumb") else None
        stats = s.db.feedback_stats().get(aid, {})
        guess = identify(a["name"])
        return JSONResponse({"asset": a, "segments": segs, "feedback": stats, "media_url": f"/api/media/{aid}",
                             "source_guess": {"site": guess["site"], "site_name": SITES[guess["site"]]["name"], "guess": guess["guess"]} if guess else None})

    def thumb(request: Request):
        seg = s.db.segment(_int(request.path_params["sid"], -1))
        if not seg or not seg.get("thumb") or not Path(seg["thumb"]).exists():
            raise HTTPException(404, "No thumbnail")
        return FileResponse(seg["thumb"], media_type="image/jpeg", headers={"Cache-Control": "max-age=3600"})

    def poster(request: Request):
        sid = _int(request.path_params["sid"], -1)
        seg = s.db.segment(sid)
        if not seg:
            raise HTTPException(404, "No such segment")
        a = s.db.asset(seg["asset_id"])
        out = s.settings.thumbs_dir / "posters" / f"{sid}.jpg"
        if not out.exists():
            img = None
            try:
                if a and a["kind"] == "video" and Path(a["path"]).exists():
                    mid = (seg["start"] + seg["end"]) / 2 if seg["end"] else seg["start"]
                    img = media.extract_frames(a["path"], [mid], max_side=1600)[0]
                elif a and a["kind"] == "image" and Path(a["path"]).exists():
                    img = media.to_rgb(media.open_image(a["path"]))
            except Exception:
                img = None
            if img is None:
                if seg.get("thumb") and Path(seg["thumb"]).exists():
                    return FileResponse(seg["thumb"], media_type="image/jpeg")
                raise HTTPException(404, "No poster")
            media.save_thumb(img, out, size=1600)
        return FileResponse(str(out), media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})

    def home(request: Request):
        per = _int(request.query_params.get("limit"), 8, 1, 40)
        rows = {}
        for kind in ("video", "image", "audio", "template"):
            rows[kind] = [result_for_asset(s.db, a) for a in s.db.list_assets(kind=kind, limit=per, status="indexed")]
        hero = None
        for r in rows["video"] + rows["image"]:
            if r.get("hits") and r["hits"][0].get("segment_id") and r.get("thumb"):
                hero = {**r, "poster": f"/api/poster/{r['hits'][0]['segment_id']}"}
                break
        return JSONResponse({"rows": rows, "hero": hero, "library": s.db.stats()})

    def media_file(request: Request):
        a = s.db.asset(_int(request.path_params["aid"], -1))
        if not a or not Path(a["path"]).exists():
            raise HTTPException(404, "Media not found")
        return _ranged(request, a["path"])

    def similar(request: Request):
        return JSONResponse(s.search.similar(_int(request.path_params["sid"], -1), _int(request.query_params.get("limit"), 30, 1, 100)))

    async def feedback(request: Request):
        body = await request.json()
        action = body.get("action")
        if action not in FEEDBACK_ACTIONS:
            raise HTTPException(400, f"action must be one of {sorted(FEEDBACK_ACTIONS)}")
        fid = s.db.add_feedback(action, body.get("asset_id"), body.get("segment_id"), body.get("query"), body.get("context") or {})
        return JSONResponse({"id": fid})

    def public_settings() -> dict:
        d = s.settings.to_public()
        d["ffmpeg_path"] = media.ffmpeg_location()
        return d

    def get_settings(request: Request):
        return JSONResponse(public_settings())

    async def put_settings(request: Request):
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "Send a JSON object")
        if "privacy_mode" in body and body["privacy_mode"] not in PRIVACY_MODES:
            raise HTTPException(400, f"privacy_mode must be one of {PRIVACY_MODES}")
        try:
            s.settings.update(body)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        s.apply_settings(reconnect="nebius_api_key" in body or "tokenfactory_base_url" in body)
        return JSONResponse(public_settings())

    def models(request: Request):
        try:
            available = s.tf.list_models()
        except (TokenFactoryError, Exception) as exc:
            return JSONResponse({"error": str(exc), "models": s.settings.models}, status_code=200)
        resolved = s.tf.resolve_models(available, apply=request.query_params.get("apply") == "1")
        return JSONResponse({"available": available, "resolved": resolved, "models": s.settings.models})

    def reveal(request: Request):
        a = s.db.asset(_int(request.path_params["aid"], -1))
        if not a or not Path(a["path"]).exists():
            raise HTTPException(404, "Asset not found")
        path = a["path"]
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", "/select,", path])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["xdg-open", str(Path(path).parent)])
        except Exception as exc:
            raise HTTPException(500, str(exc))
        return JSONResponse({"ok": True})

    def web_off():
        why = s.tavily.why_off()
        if why:
            raise HTTPException(409, why)

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "Send a JSON object")
        if not isinstance(body, dict):
            raise HTTPException(400, "Send a JSON object")
        return body

    async def guarded(fn, *args, **kw):
        try:
            return await run_in_threadpool(fn, *args, **kw)
        except (SourceError, ValueError) as exc:
            raise HTTPException(400, str(exc))
        except TavilyError as exc:
            raise HTTPException(502, str(exc))

    async def web_search(request: Request):
        qp = request.query_params
        q = (qp.get("q") or "").strip()
        if not q:
            raise HTTPException(400, "q is required")
        why = s.tavily.why_off()
        if why:
            return JSONResponse({"query": q, "items": [], "off": why})
        kind = qp.get("kind") or None
        res = await guarded(s.web.search, q, kind, _int(qp.get("limit"), s.settings.web_results, 1, 20))
        return JSONResponse(res)

    async def web_save(request: Request):
        web_off()
        body = await body_of(request)
        url = str(body.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "url is required")
        res = await guarded(s.web.save, url, body.get("kind") or None)
        return JSONResponse(res)

    async def web_licence(request: Request):
        web_off()
        body = await body_of(request)
        res = await guarded(s.web.check, str(body.get("url") or "").strip())
        return JSONResponse(res)

    def licences(request: Request):
        return JSONResponse(s.audit.listing())

    async def licences_check(request: Request):
        web_off()
        body = await body_of(request)
        if body.get("asset_id") is not None:
            aid = _int(body.get("asset_id"), -1)
            if not s.db.asset(aid):
                raise HTTPException(404, "Asset not found")
            lic = await guarded(s.audit.check_one, aid)
            if lic is None:
                raise HTTPException(400, "This file name does not look like a download from a free site")
            return JSONResponse({"asset_id": aid, "licence": lic})
        return JSONResponse({"audit": s.audit.start(force=bool(body.get("force")))})

    async def licence_set(request: Request):
        aid = _int(request.path_params["aid"], -1)
        if not s.db.asset(aid):
            raise HTTPException(404, "Asset not found")
        body = await body_of(request)
        lic = body.get("licence")
        if lic is not None and not isinstance(lic, dict):
            raise HTTPException(400, "licence must be an object or null")
        if lic is not None:
            lic = {**lic, "method": "you"}
        s.db.update_asset(aid, license=lic, source_url=(lic or {}).get("source_url"))
        return JSONResponse({"asset_id": aid, "licence": lic})

    async def broll(request: Request):
        body = await body_of(request)
        res = await guarded(s.broll.plan, str(body.get("topic") or ""), str(body.get("script") or ""),
                            _int(body.get("seconds"), 60, 15, 1200), bool(body.get("research", True)))
        return JSONResponse(res)

    def inbox(request: Request):
        f = s.ensure_inbox()
        return JSONResponse({"folder": f, "path": f["path"]})

    async def http_error(request: Request, exc: HTTPException):
        return JSONResponse({"error": exc.detail}, status_code=exc.status_code)

    routes = [
        Route("/api/status", status),
        Route("/api/folders", folders, methods=["GET"]),
        Route("/api/folders", add_folder, methods=["POST"]),
        Route("/api/folders/{fid:int}", remove_folder, methods=["DELETE"]),
        Route("/api/folders/{fid:int}/rescan", rescan, methods=["POST"]),
        Route("/api/rescan", rescan, methods=["POST"]),
        Route("/api/search", search),
        Route("/api/assets", assets),
        Route("/api/assets/{aid:int}", asset),
        Route("/api/assets/{aid:int}/reveal", reveal, methods=["POST"]),
        Route("/api/thumb/{sid:int}", thumb),
        Route("/api/media/{aid:int}", media_file),
        Route("/api/poster/{sid:int}", poster),
        Route("/api/home", home),
        Route("/api/similar/{sid:int}", similar),
        Route("/api/feedback", feedback, methods=["POST"]),
        Route("/api/settings", get_settings, methods=["GET"]),
        Route("/api/settings", put_settings, methods=["POST"]),
        Route("/api/models", models),
        Route("/api/web/search", web_search),
        Route("/api/web/save", web_save, methods=["POST"]),
        Route("/api/web/licence", web_licence, methods=["POST"]),
        Route("/api/licences", licences),
        Route("/api/licences/check", licences_check, methods=["POST"]),
        Route("/api/licences/{aid:int}", licence_set, methods=["POST"]),
        Route("/api/broll", broll, methods=["POST"]),
        Route("/api/inbox", inbox, methods=["POST"]),
    ]
    ui = ui_dir()
    if ui.exists():
        routes.append(Mount("/", app=StaticFiles(directory=str(ui), html=True), name="ui"))
    hosts = [h.strip() for h in os.environ.get("CAA_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",") if h.strip()]
    app = Starlette(routes=routes, exception_handlers={HTTPException: http_error},
                    middleware=[Middleware(TrustedHostMiddleware, allowed_hosts=hosts),
                                Middleware(CORSMiddleware, allow_origins=["http://127.0.0.1", "http://localhost"],
                                           allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(:\d+)?", allow_methods=["*"],
                                           allow_headers=["*"])])
    app.state.services = s
    return app


def _ranged(request: Request, path: str) -> Response:
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    rng = request.headers.get("range")
    if not rng or not rng.startswith("bytes="):
        return FileResponse(path, media_type=ctype, headers={"Accept-Ranges": "bytes"})
    try:
        spec = rng.split("=", 1)[1].split(",")[0].strip()
        a, b = spec.split("-")
        if a == "":
            start, end = max(0, size - int(b)), size - 1
        else:
            start, end = int(a), (int(b) if b else size - 1)
        end = min(end, size - 1)
        if start > end or start >= size:
            raise ValueError
    except ValueError:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{size}"})
    length = end - start + 1

    def body():
        with open(path, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(1 << 20, left))
                if not chunk:
                    break
                left -= len(chunk)
                yield chunk

    return StreamingResponse(body(), status_code=206, media_type=ctype, headers={
        "Content-Range": f"bytes {start}-{end}/{size}", "Accept-Ranges": "bytes", "Content-Length": str(length)})
