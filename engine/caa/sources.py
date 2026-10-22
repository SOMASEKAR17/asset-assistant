from __future__ import annotations

import json
import logging
import re
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from .nemotron import extract_json
from .tavily import Tavily, TavilyError, image_urls

log = logging.getLogger("caa.sources")

SITES = {
    "pexels": {"name": "Pexels", "domain": "pexels.com", "licence": "Pexels License", "commercial_ok": True,
               "attribution_required": False, "terms": "https://www.pexels.com/license/",
               "note": "Free to use; credit is appreciated but not required. Do not resell unaltered copies."},
    "pixabay": {"name": "Pixabay", "domain": "pixabay.com", "licence": "Pixabay Content License", "commercial_ok": True,
                "attribution_required": False, "terms": "https://pixabay.com/service/license-summary/",
                "note": "Free to use without credit. Some music is registered with YouTube Content ID."},
    "unsplash": {"name": "Unsplash", "domain": "unsplash.com", "licence": "Unsplash License", "commercial_ok": True,
                 "attribution_required": False, "terms": "https://unsplash.com/license",
                 "note": "Free to use; credit is appreciated but not required."},
    "mixkit": {"name": "Mixkit", "domain": "mixkit.co", "licence": "Mixkit License", "commercial_ok": None,
               "attribution_required": False, "terms": "https://mixkit.co/license/",
               "note": "Most items use the Mixkit Free License; some use a Restricted License. Check the item."},
    "freesound": {"name": "Freesound", "domain": "freesound.org", "licence": "Creative Commons (per sound)", "commercial_ok": None,
                  "attribution_required": None, "terms": "https://freesound.org/help/faq/",
                  "note": "Each sound has its own licence: CC0, CC BY or CC BY-NC."},
    "openverse": {"name": "Openverse", "domain": "openverse.org", "licence": "Creative Commons (per item)", "commercial_ok": None,
                  "attribution_required": None, "terms": "https://openverse.org/",
                  "note": "Each item has its own Creative Commons licence."},
}

KIND_SITES = {
    "video": ["pexels", "pixabay", "mixkit"],
    "image": ["pexels", "pixabay", "unsplash", "openverse"],
    "audio": ["freesound", "pixabay", "mixkit"],
    "template": ["mixkit"],
}

KIND_WORDS = {"video": "free stock video", "image": "free stock photo", "audio": "free sound effect", "template": "free video template"}

KIND_PATHS = {
    "pexels": [("/video/", "video"), ("/photo/", "image")],
    "pixabay": [("/videos/", "video"), ("/music/", "audio"), ("/sound-effects/", "audio"), ("/photos/", "image"),
                ("/illustrations/", "image"), ("/vectors/", "image")],
    "unsplash": [("/photos/", "image")],
    "mixkit": [("/free-stock-video/", "video"), ("/free-stock-music/", "audio"), ("/free-sound-effects/", "audio"),
               ("-templates/", "template")],
    "freesound": [("/sounds/", "audio"), ("/s/", "audio")],
    "openverse": [("/image/", "image"), ("/audio/", "audio")],
}

ITEM_PAGE = {
    "pexels": re.compile(r"/(photo|video)/[^/]*?(\d{4,})/?$"),
    "pixabay": re.compile(r"/(photos|videos|music|sound-effects|illustrations|vectors)/[^/]*-(\d{4,})/?$"),
    "unsplash": re.compile(r"/photos/[^/]+/?$"),
    "mixkit": re.compile(r"/free-[a-z-]+/[^/]*-(\d{2,})/?$"),
    "freesound": re.compile(r"/(?:people/[^/]+/sounds|s)/(\d+)/?$"),
    "openverse": re.compile(r"/(image|audio)/[0-9a-f-]{20,}/?$"),
}

MEDIA_EXT = {
    "video": (".mp4", ".mov", ".webm", ".m4v"),
    "audio": (".mp3", ".wav", ".ogg", ".flac", ".m4a"),
    "image": (".jpg", ".jpeg", ".png", ".webp"),
}
MEDIA_RX = re.compile(r"https?://[^\s\"'<>()\[\]]+?\.(?:mp4|mov|webm|m4v|mp3|wav|ogg|flac|m4a|jpe?g|png|webp)(?:\?[^\s\"'<>()\[\]]*)?", re.I)
MEDIA_HOSTS = ("images.pexels.com", "videos.pexels.com", "player.vimeo.com", "cdn.pixabay.com", "assets.mixkit.co",
               "cdn.freesound.org", "images.unsplash.com", "plus.unsplash.com", "upload.wikimedia.org", "live.staticflickr.com")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CreatorAssetAssistant/0.1"

CC_DEEDS = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC BY": "https://creativecommons.org/licenses/by/4.0/",
    "CC BY-SA": "https://creativecommons.org/licenses/by-sa/4.0/",
    "CC BY-NC": "https://creativecommons.org/licenses/by-nc/4.0/",
}

STOCK_PATTERNS = [
    ("freesound", re.compile(r"^(?P<id>\d{2,8})__(?P<user>[^_]+)__(?P<title>.+)\.(?:wav|mp3|flac|ogg|aiff?|m4a)$", re.I)),
    ("mixkit", re.compile(r"^mixkit-(?P<slug>[a-z0-9-]+?)-(?P<id>\d{2,6})(?:-(?:hd|4k|full-hd|large|medium|small|uhd|sd)(?:-ready)?)?\.(?:mp4|mov|wav|mp3|zip|mogrt)$", re.I)),
    ("pexels", re.compile(r"^(?P<id>\d{5,10})-(?:uhd|hd|sd)_\d{3,4}_\d{3,4}_\d{2,3}fps\.(?:mp4|mov|webm)$", re.I)),
    ("pexels", re.compile(r"^pexels-(?:photo-)?(?:(?P<slug>[a-z0-9-]+?)-)?(?P<id>\d{5,10})(?:-\d+)?\.(?:jpe?g|png|webp|mp4|mov|webm)$", re.I)),
    ("unsplash", re.compile(r"^(?P<slug>[a-z0-9-]+)-(?P<id>[A-Za-z0-9_-]{11})-unsplash\.(?:jpe?g|png|webp)$", re.I)),
    ("pixabay", re.compile(r"^(?P<slug>[a-z0-9-]+?)-(?P<id>\d{5,9})_(?:180|340|640|960|1280|1920)\.(?:jpe?g|png|webp)$", re.I)),
    ("pixabay", re.compile(r"^(?P<id>\d{5,9})-(?P<slug>\d{6,12})_(?:tiny|small|medium|large)\.mp4$", re.I)),
    ("pixabay?", re.compile(r"^(?P<slug>[a-z][a-z0-9]*(?:-[a-z0-9]+)+)-(?P<id>\d{3,6})\.mp3$", re.I)),
]


class SourceError(RuntimeError):
    pass


def site_for_url(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    for key, site in SITES.items():
        if host == site["domain"] or host.endswith("." + site["domain"]):
            return key
    return None


def kind_for_url(site: str | None, url: str) -> str | None:
    path = urlparse(url).path.lower()
    for frag, kind in KIND_PATHS.get(site or "", []):
        if frag in path:
            return kind
    return None


def is_item_page(site: str | None, url: str) -> bool:
    rx = ITEM_PAGE.get(site or "")
    return bool(rx and rx.search(urlparse(url).path))


def site_defaults(site: str, url: str | None = None, method: str = "site default") -> dict:
    s = SITES[site]
    return {"site": site, "site_name": s["name"], "licence": s["licence"], "commercial_ok": s["commercial_ok"],
            "attribution_required": s["attribution_required"], "credit": "", "note": s["note"], "terms_url": s["terms"],
            "source_url": url, "method": method, "checked_at": None}


def identify(name: str) -> dict | None:
    base = Path(name).name
    for site, rx in STOCK_PATTERNS:
        m = rx.match(base)
        if not m:
            continue
        g = m.groupdict()
        guess = site.endswith("?")
        site = site.rstrip("?")
        if guess and re.fullmatch(r"(?:19|20)\d\d", g.get("id") or ""):
            continue
        ident = {"site": site, "id": g.get("id"), "slug": (g.get("slug") or "").lower(), "file": base, "guess": guess}
        if site == "pixabay" and base.lower().endswith(".mp4"):
            ident["slug"] = ""
        if site == "freesound":
            ident["user"] = g["user"]
            ident["title"] = re.sub(r"[-_]+", " ", Path(g["title"]).stem if "." in g["title"] else g["title"]).strip()
            ident["url"] = f"https://freesound.org/people/{g['user']}/sounds/{g['id']}/"
        elif site == "pexels":
            kind = "video" if Path(base).suffix.lower() in (".mp4", ".mov", ".webm") else "photo"
            ident["url"] = f"https://www.pexels.com/{kind}/{g['id']}/"
        elif site == "unsplash":
            ident["url"] = f"https://unsplash.com/photos/{g['id']}"
        words = " ".join(w for w in re.split(r"[-_ ]+", ident["slug"] or ident.get("title", "")) if w and not w.isdigit())
        ident["query"] = " ".join(x for x in (SITES[site]["name"], words, ident["id"]) if x)
        return ident
    low = base.lower()
    for site in ("pexels", "pixabay", "mixkit", "unsplash", "freesound"):
        if site in low:
            words = " ".join(w for w in re.split(r"[^a-z0-9]+", Path(low).stem) if w and w != site and not w.isdigit())
            return {"site": site, "id": None, "slug": words, "file": base, "guess": False,
                    "query": f"{SITES[site]['name']} {words}".strip()}
    return None


def _excerpt(text: str, size: int = 3500) -> str:
    low = text.lower()
    spots = [m.start() for m in re.finditer(r"licen[cs]e|attribution|creative commons|cc0|cc by|commercial", low)]
    if not spots:
        return text[:size]
    out, used = [], 0
    for pos in spots:
        a, b = max(0, pos - 300), min(len(text), pos + 500)
        chunk = text[a:b]
        if any(chunk in o for o in out):
            continue
        out.append(chunk)
        used += len(chunk)
        if used >= size:
            break
    return "\n...\n".join(out)[:size]


def licence_from_rules(site: str, text: str, url: str, title: str | None = None) -> dict:
    lic = site_defaults(site, url, "page")
    low = (text or "").lower()
    if site in ("freesound", "openverse"):
        if re.search(r"creative commons 0|\bcc0\b|public domain dedication|cc zero", low):
            lic.update(licence="CC0", commercial_ok=True, attribution_required=False, note="Public domain dedication: no credit needed.")
        elif re.search(r"attribution[- ]non-?commercial|\bcc by-nc\b|by-nc", low):
            lic.update(licence="CC BY-NC", commercial_ok=False, attribution_required=True,
                       note="Credit the author, and do not use it in monetised or sponsored videos.")
        elif re.search(r"\bcc by-sa\b|attribution[- ]share ?alike", low):
            lic.update(licence="CC BY-SA", commercial_ok=True, attribution_required=True,
                       note="Credit the author; changed versions must use the same licence.")
        elif re.search(r"sampling\+", low):
            lic.update(licence="Sampling+", commercial_ok=None, attribution_required=True,
                       note="Old Creative Commons licence: use as part of a larger work only, with credit.")
        elif re.search(r"\bcc by\b|attribution 4\.0|attribution 3\.0|creative commons attribution", low):
            lic.update(licence="CC BY", commercial_ok=True, attribution_required=True, note="Credit the author in your video description.")
    if lic["licence"] in CC_DEEDS:
        lic["terms_url"] = CC_DEEDS[lic["licence"]]
    if site == "mixkit":
        if "restricted license" in low:
            lic.update(licence="Mixkit Restricted License", commercial_ok=None, note="Restricted use; read the Mixkit Restricted License before monetised use.")
        elif re.search(r"free license|mixkit (stock )?(video|music|sound effects?) free license", low):
            lic.update(licence="Mixkit Free License", commercial_ok=True, attribution_required=False, note="Free for commercial and personal projects, no credit needed.")
    author = None
    m = re.search(r"/people/([^/]+)/", url)
    if m:
        author = unquote(m.group(1))
    if not author:
        m = re.search(r"\b(?:photo|video|image|music|sound|clip|footage|track)\s+by\s+([^\n|·,()\[\]]{2,40})", text or "", re.I)
        author = re.sub(r"\s+(?:on|from|via)\s+\w+.*$", "", m.group(1)).strip(" .") if m else None
    name = title or ""
    who = f" by {author}" if author else ""
    lic["author"] = author
    lic["credit"] = f"\"{name}\"{who} ({SITES[site]['name']}, {lic['licence']}) {url}".replace('"" ', "").strip() if name or author else f"{SITES[site]['name']}: {url}"
    return lic


LICENCE_PROMPT = """Read this licence information from a free stock asset page on {site}. Return JSON with keys:
licence: the licence name as written on the page, for example "CC BY 4.0", "Pexels License", "Mixkit Free License"
commercial_ok: true, false, or null if the page does not say
attribution_required: true, false, or null if the page does not say
credit: the credit line a creator should put in a video description, using the author and title if shown, or ""
notes: one short sentence about restrictions, or ""
Page: {url}
Excerpt:
{excerpt}"""


class WebAssets:
    def __init__(self, settings, db, tavily: Tavily, tf=None, session: requests.Session | None = None, on_saved=None):
        self.settings = settings
        self.db = db
        self.tavily = tavily
        self.tf = tf
        self.session = session or requests.Session()
        self.on_saved = on_saved

    def licence_for(self, site: str, text: str, url: str, title: str | None = None) -> dict:
        lic = licence_from_rules(site, text, url, title)
        ruled = lic["licence"] != SITES[site]["licence"]
        fixed = site in ("pexels", "pixabay", "unsplash")
        if self.tf is not None and getattr(self.tf, "available", False) and text:
            prompt = LICENCE_PROMPT.format(site=SITES[site]["name"], url=url, excerpt=_excerpt(text))
            try:
                raw = self.tf.chat("fast", [{"role": "system", "content": "You read licence terms carefully. Reply with one JSON object only."},
                                            {"role": "user", "content": prompt}], max_tokens=300, temperature=0.0, budget=25)
                got = extract_json(raw) or {}
            except Exception as exc:
                log.warning("Licence reading with Nemotron failed: %s", exc)
                got = {}
            if got:
                for key in ("commercial_ok", "attribution_required"):
                    if isinstance(got.get(key), bool) and lic[key] is None:
                        lic[key] = got[key]
                if str(got.get("licence") or "").strip() and not ruled and not fixed:
                    lic["licence"] = str(got["licence"]).strip()[:80]
                if str(got.get("credit") or "").strip():
                    lic["credit"] = str(got["credit"]).strip()[:300]
                if str(got.get("notes") or "").strip() and not ruled:
                    lic["note"] = str(got["notes"]).strip()[:300]
                lic["method"] = "page + nemotron"
        lic["checked_at"] = time.time()
        return lic

    def search(self, q: str, kind: str | None = None, limit: int = 8) -> dict:
        q = (q or "").strip()
        if not q:
            return {"query": q, "kind": kind, "items": []}
        kinds = [kind] if kind in KIND_SITES else ["video", "image", "audio"]
        sites = list(dict.fromkeys(s for k in kinds for s in KIND_SITES[k]))
        words = KIND_WORDS.get(kind or "", "free stock video photo or sound")
        data = self.tavily.search(f"{q} {words}", max_results=min(20, max(limit * 2, 10)),
                                  include_domains=[SITES[s]["domain"] for s in sites], include_images=True)
        items = []
        seen = set()
        pool = image_urls(data.get("images"))
        for r in data.get("results") or []:
            url = str(r.get("url") or "")
            site = site_for_url(url)
            if not site or url in seen:
                continue
            seen.add(url)
            k = kind_for_url(site, url)
            if kind and k and k != kind:
                continue
            thumbs = image_urls(r.get("images"))
            ident = _page_id(url)
            if not thumbs and ident:
                thumbs = [u for u in pool if ident in u]
            m = re.search(r"/photo/[^/]*?(\d{4,})/?$", urlparse(url).path) if site == "pexels" else None
            if not thumbs and m:
                thumbs = [f"https://images.pexels.com/photos/{m.group(1)}/pexels-photo-{m.group(1)}.jpeg?auto=compress&w=640"]
            items.append({"title": _clean_title(r.get("title") or url), "url": url, "site": site, "site_name": SITES[site]["name"],
                          "kind": k, "item": is_item_page(site, url), "snippet": str(r.get("content") or "")[:220],
                          "thumb": thumbs[0] if thumbs else None, "score": float(r.get("score") or 0.0),
                          "licence": site_defaults(site, url)})
        items.sort(key=lambda it: (not it["item"], -it["score"]))
        return {"query": q, "kind": kind, "items": items[:limit], "sites": [SITES[s]["name"] for s in sites]}

    def read_page(self, url: str) -> tuple[str, list[str], str]:
        data = self.tavily.extract(url, include_images=True)
        res = next((r for r in data.get("results") or [] if r.get("raw_content")), None)
        if not res:
            failed = (data.get("failed_results") or [{}])[0].get("error") if data.get("failed_results") else None
            raise SourceError(f"Tavily could not read this page{': ' + failed if failed else ''}")
        text = str(res.get("raw_content") or "")
        title = ""
        m = re.search(r"^#\s+(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()[:120]
        return text, image_urls(res.get("images")), title

    def check(self, url: str) -> dict:
        site = site_for_url(url)
        if not site:
            raise SourceError("This page is not on a supported free site")
        text, _, title = self.read_page(url)
        return self.licence_for(site, text, url, title or None)

    def pick_media(self, site: str, url: str, text: str, images: list[str], kind: str | None) -> str | None:
        kind = kind or kind_for_url(site, url) or "image"
        exts = MEDIA_EXT.get("audio" if kind == "audio" else kind, MEDIA_EXT["image"])
        cands = list(dict.fromkeys(MEDIA_RX.findall(text or "") + list(images or [])))

        def score(u: str) -> float:
            p = urlparse(u)
            path = p.path.lower()
            if not path.endswith(exts):
                return -1
            s = 1.0
            if any(p.hostname and p.hostname.endswith(h) for h in MEDIA_HOSTS):
                s += 2
            for good, w in (("1920", 1.0), ("1080", 1.0), ("hd", 0.5), ("large", 0.5), ("original", 1.0), ("2560", 0.8), ("hq", 0.4)):
                if good in u.lower():
                    s += w
            for bad, w in (("avatar", 3), ("logo", 3), ("icon", 3), ("thumb", 1), ("small", 0.5), ("tiny", 1), ("w=150", 1)):
                if bad in u.lower():
                    s -= w
            return s

        ranked = sorted((c for c in cands if score(c) > 0), key=score, reverse=True)
        if ranked:
            return ranked[0]
        if site == "pexels":
            m = re.search(r"/(photo|video)/[^/]*?(\d{4,})/?$", urlparse(url).path)
            if m:
                return f"https://www.pexels.com/{m.group(1)}/{m.group(2)}/download/"
        if site == "unsplash":
            m = re.search(r"/photos/(?:[^/]*-)?([A-Za-z0-9_-]{11})/?$", urlparse(url).path)
            if m:
                return f"https://unsplash.com/photos/{m.group(1)}/download?force=true"
        return None

    def inbox(self) -> Path:
        p = Path(self.settings.inbox_dir).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()

    def _download(self, media_url: str, dest_dir: Path, stem: str, max_bytes: int = 800 * 1024 * 1024) -> Path:
        with self.session.get(media_url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=(15, 120), allow_redirects=True) as r:
            if r.status_code != 200:
                raise SourceError(f"The site refused the download ({r.status_code}). Open the page and download it there.")
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype.startswith("text/") or "html" in ctype:
                raise SourceError("The site returned a web page instead of a file. Open the page and download it there.")
            ext = Path(urlparse(r.url).path).suffix.lower()
            if ext not in sum(MEDIA_EXT.values(), ()):
                ext = {"video/mp4": ".mp4", "video/quicktime": ".mov", "video/webm": ".webm", "audio/mpeg": ".mp3", "audio/wav": ".wav",
                       "audio/x-wav": ".wav", "audio/ogg": ".ogg", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(ctype, ".bin")
            dest = dest_dir / f"{stem}{ext}"
            n = 1
            while dest.exists():
                dest = dest_dir / f"{stem}-{n}{ext}"
                n += 1
            tmp = dest.with_name(dest.name + ".part")
            size = 0
            with open(tmp, "wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        fh.close()
                        tmp.unlink(missing_ok=True)
                        raise SourceError("The file is larger than 800 MB; download it from the page instead.")
                    fh.write(chunk)
        tmp.replace(dest)
        return dest

    def save(self, url: str, kind: str | None = None) -> dict:
        site = site_for_url(url)
        if not site:
            raise SourceError("This page is not on a supported free site")
        text, images, title = self.read_page(url)
        media = self.pick_media(site, url, text, images, kind)
        if not media:
            raise SourceError("No downloadable file was found on this page. Open the page and download it there.")
        lic = self.licence_for(site, text, url, title or None)
        slug = _slug(urlparse(url).path.rstrip("/").split("/")[-1] or title or "asset")
        path = self._download(media, self.inbox(), f"{site}-{slug}")
        lic["file"] = path.name
        self.db.put_download(str(path), url, media, lic)
        if self.on_saved:
            self.on_saved(path)
        return {"path": str(path), "name": path.name, "licence": lic, "media_url": media, "inbox": str(self.inbox())}

    def find_source(self, name: str) -> dict | None:
        ident = identify(name)
        if not ident:
            return None
        site = ident["site"]
        url = ident.get("url")
        if not url:
            data = self.tavily.search(ident["query"], max_results=6, include_domains=[SITES[site]["domain"]])
            cands = [r for r in data.get("results") or [] if site_for_url(str(r.get("url") or "")) == site]
            words = {w for w in re.split(r"[-_ ]+", ident.get("slug") or "") if len(w) > 2}

            def fit(r: dict) -> float:
                u = str(r.get("url") or "").lower()
                s = 0.0
                if ident.get("id") and ident["id"] in u:
                    s += 5
                s += sum(1 for w in words if w in u) / max(1, len(words)) * 3
                s += 1 if is_item_page(site, u) else 0
                return s

            cands.sort(key=fit, reverse=True)
            need = 5 if ident.get("guess") else 2
            if cands and fit(cands[0]) >= need:
                url = str(cands[0]["url"])
        if not url and ident.get("guess"):
            return None
        if not url:
            out = site_defaults(site, None, "file name")
            out.update(status="not_found", identified=ident, checked_at=time.time(),
                       note=f"Looks like a {SITES[site]['name']} download, but the page was not found. {SITES[site]['note']}")
            return out
        try:
            text, _, title = self.read_page(url)
            lic = self.licence_for(site, text, url, ident.get("title") or title or None)
            lic["status"] = "found"
        except (SourceError, TavilyError) as exc:
            lic = site_defaults(site, url, "site default")
            lic.update(status="unverified", checked_at=time.time(), note=f"{SITES[site]['note']} The page could not be read ({exc}).")
        lic["identified"] = ident
        return lic


class SourceAudit:
    def __init__(self, db, web: WebAssets):
        self.db = db
        self.web = web
        self._thread: threading.Thread | None = None
        self.progress = {"state": "idle", "done": 0, "total": 0, "found": 0, "current": None, "error": None, "finished_at": None}

    def candidates(self, force: bool = False) -> list[dict]:
        rows = self.db.query("SELECT id, name, license FROM assets WHERE status='indexed'")
        out = []
        for r in rows:
            if identify(r["name"]) and (force or not r["license"] or r["license"] in ("null", "{}")):
                out.append({"id": r["id"], "name": r["name"]})
        return out

    def check_one(self, asset_id: int) -> dict | None:
        a = self.db.asset(asset_id)
        if not a:
            return None
        lic = self.web.find_source(a["name"])
        if lic:
            self.db.update_asset(asset_id, license=lic, source_url=lic.get("source_url"))
        return lic

    def start(self, force: bool = False) -> dict:
        if self._thread and self._thread.is_alive():
            return self.progress
        todo = self.candidates(force)
        self.progress.update(state="running", done=0, total=len(todo), found=0, current=None, error=None, finished_at=None)

        def run():
            urls = [i["url"] for i in (identify(t["name"]) for t in todo) if i and i.get("url")]
            if len(urls) > 1:
                try:
                    self.web.tavily.extract_many(urls, include_images=True)
                except Exception as exc:
                    log.warning("Batch page read failed, reading pages one by one: %s", exc)
            for item in todo:
                self.progress["current"] = item["name"]
                try:
                    lic = self.check_one(item["id"])
                    if lic and lic.get("status") == "found":
                        self.progress["found"] += 1
                except Exception as exc:
                    self.progress["error"] = f"{item['name']}: {exc}"
                    log.warning("Source check failed for %s: %s", item["name"], exc)
                self.progress["done"] += 1
            self.progress.update(state="idle", current=None, finished_at=time.time())

        self._thread = threading.Thread(target=run, name="caa-source-audit", daemon=True)
        self._thread.start()
        return self.progress

    def listing(self) -> dict:
        rows = self.db.query("SELECT id, name, kind, path, license, source_url FROM assets WHERE status='indexed' ORDER BY name")
        items = []
        for r in rows:
            lic = None
            if r["license"]:
                try:
                    lic = json.loads(r["license"])
                except (TypeError, ValueError):
                    lic = None
            ident = identify(r["name"])
            if not lic and not ident:
                continue
            items.append({"asset_id": r["id"], "name": r["name"], "kind": r["kind"], "path": r["path"], "licence": lic or None,
                          "site": (lic or {}).get("site") or (ident or {}).get("site"), "source_url": r["source_url"],
                          "checked": bool(lic), "guess": bool((ident or {}).get("guess")) and not lic})
        summary = {"files": len(items), "checked": sum(1 for i in items if i["checked"]),
                   "credit_needed": sum(1 for i in items if (i["licence"] or {}).get("attribution_required")),
                   "not_commercial": sum(1 for i in items if (i["licence"] or {}).get("commercial_ok") is False),
                   "unclear": sum(1 for i in items if i["checked"] and (i["licence"] or {}).get("commercial_ok") is None)}
        return {"items": items, "summary": summary, "audit": self.progress}


def _page_id(url: str) -> str | None:
    m = re.search(r"(\d{4,})/?$", urlparse(url).path)
    return m.group(1) if m else None


def _clean_title(t: str) -> str:
    t = re.sub(r"\s*[|·-]\s*(Free Stock.*|Pexels|Pixabay|Mixkit|Unsplash|Freesound|Openverse)\s*$", "", t.strip(), flags=re.I)
    return t[:120]


def _slug(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", unquote(s).lower()).strip("-")
    return s[:60] or "asset"
