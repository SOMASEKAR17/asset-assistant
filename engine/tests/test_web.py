from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from caa import media
from caa.asr import Transcriber
from caa.broll import BrollPlanner, clean_beats
from caa.config import load_settings
from caa.db import Database
from caa.embed import FallbackEmbedder
from caa.sources import WebAssets, identify, licence_from_rules, site_for_url
from caa.tavily import Tavily, TavilyError
from fixtures import FakeTextEmbedder, FakeTokenFactory, make_library

HAS_FFMPEG = media.ffmpeg_available()

PEXELS_VIDEO = "https://www.pexels.com/video/waves-on-a-beach-at-sunset-1093662/"
PEXELS_PHOTO = "https://www.pexels.com/photo/5698420/"
MIXKIT_PAGE = "https://mixkit.co/free-sound-effects/fast-small-sweep-transition-166/"
FREESOUND_PAGE = "https://freesound.org/people/InspectorJ/sounds/123456/"

PAGES = {
    PEXELS_VIDEO: "# Waves On A Beach At Sunset\nVideo by Ruvim Miksanskiy\nFree to use. Pexels License.\n"
                  "![avatar](https://images.pexels.com/users/avatars/123/ruvim.jpeg?w=60)\n"
                  "[Download](https://videos.pexels.com/video-files/1093662/1093662-hd_1920_1080_30fps.mp4)\n"
                  "https://videos.pexels.com/video-files/1093662/1093662-sd_640_360_30fps.mp4",
    PEXELS_PHOTO: "# Woman Holding a Camera\nPhoto by cottonbro studio\nFree to use under the Pexels License.\n"
                  "https://images.pexels.com/photos/5698420/pexels-photo-5698420.jpeg?cs=srgb&dl=pexels-cottonbro-5698420.jpg&fm=jpg",
    MIXKIT_PAGE: "# Fast small sweep transition\nDownload this free sound effect. Licensed under the Mixkit Sound Effects Free License.\n"
                 "https://assets.mixkit.co/active_storage/sfx/166/166.wav",
    FREESOUND_PAGE: "# wind chime gamelan\nby InspectorJ\nLicense: Attribution 4.0\n",
}


def jpeg_bytes(color=(250, 120, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (320, 180), color).save(buf, "JPEG")
    return buf.getvalue()


class FakeTavily(Tavily):
    has_key = True

    def __init__(self, settings, db=None):
        super().__init__(settings, db)
        self.posts: list[tuple[str, dict]] = []

    def _post(self, path, body, timeout=30.0):
        self.posts.append((path, body))
        self.stats["calls"] += 1
        if path == "/extract":
            out, failed = [], []
            for u in body["urls"]:
                if u in PAGES:
                    out.append({"url": u, "raw_content": PAGES[u], "images": []})
                else:
                    failed.append({"url": u, "error": "404"})
            return {"results": out, "failed_results": failed}
        q = body["query"].lower()
        if "mixkit" in q:
            return {"results": [{"url": "https://mixkit.co/free-sound-effects/whoosh/", "title": "Whoosh sounds", "score": 0.9},
                                {"url": MIXKIT_PAGE, "title": "Fast small sweep transition", "score": 0.8}]}
        if "free stock" in q:
            return {"results": [
                {"url": "https://pixabay.com/videos/search/sunset/", "title": "Sunset Videos - Pixabay", "content": "Free sunset videos", "score": 0.95},
                {"url": PEXELS_VIDEO, "title": "Waves On A Beach At Sunset · Free Stock Video", "content": "Ocean waves", "score": 0.9},
                {"url": "https://www.pexels.com/photo/sunset-1234567/", "title": "Sunset photo", "score": 0.85},
                {"url": "https://example.com/stock/sunset", "title": "Paid stock", "score": 0.99},
            ], "images": ["https://images.pexels.com/videos/1093662/free-video-1093662.jpg?w=640"]}
        return {"results": [{"url": "https://example.org/coffee", "title": "How coffee is grown", "content": "Coffee grows in the tropics.",
                             "score": 0.8}], "answer": "Coffee grows on shrubs in tropical highlands.", "images": []}


class FakeResponse:
    def __init__(self, url, data, ctype, status=200):
        self.url, self._data, self.status_code = url, data, status
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_content(self, n):
        for i in range(0, len(self._data), n):
            yield self._data[i : i + n]


class FakeSession:
    def __init__(self):
        self.gets = []

    def get(self, url, **kw):
        self.gets.append(url)
        if "html" in url:
            return FakeResponse(url, b"<html></html>", "text/html")
        if url.endswith(".mp4"):
            return FakeResponse(url, b"\x00" * 2048, "video/mp4")
        return FakeResponse(url, jpeg_bytes(), "image/jpeg")


class PlanTokenFactory(FakeTokenFactory):
    def chat(self, role, messages, **kw):
        prompt = messages[-1]["content"]
        self.calls[role] = self.calls.get(role, 0) + 1
        if "licence information" in prompt and "on Pexels" in prompt:
            return json.dumps({"licence": "Pexels License", "commercial_ok": True, "attribution_required": False,
                               "credit": "Photo by cottonbro studio on Pexels", "notes": ""})
        if "licence information" in prompt and "on Freesound" in prompt:
            return json.dumps({"licence": "Attribution 4.0", "commercial_ok": False, "attribution_required": True,
                               "credit": "wind chime gamelan by InspectorJ (freesound.org), CC BY 4.0", "notes": "Made up"})
        if "b-roll" in prompt:
            return json.dumps({"title": "Where coffee comes from", "hook": "Your coffee started on a mountain.",
                               "beats": [{"line": "Coffee grows in the tropics.", "shot": "sunset over the beach", "search": "sunset beach",
                                          "kind": "video", "seconds": 5, "why": "warm opener"},
                                         {"line": "Picked by hand.", "shot": "hands picking red coffee cherries", "search": "coffee cherries picking",
                                          "kind": "video", "seconds": 6, "why": "shows the work"},
                                         {"line": "", "shot": "", "search": "", "kind": "video"}],
                               "facts": [{"fact": "Coffee grows on shrubs in tropical highlands.", "source": 1}]})
        return "{}"


class UnitTests(unittest.TestCase):
    def test_identify(self):
        cases = {
            "pexels-cottonbro-5698420.jpg": ("pexels", "https://www.pexels.com/photo/5698420/"),
            "3195394-uhd_3840_2160_25fps.mp4": ("pexels", "https://www.pexels.com/video/3195394/"),
            "pexels-tima-miroshnichenko-6010489.mp4": ("pexels", "https://www.pexels.com/video/6010489/"),
            "123456__InspectorJ__wind-chime-gamelan.wav": ("freesound", FREESOUND_PAGE),
            "john-doe-AbCdEfGhIjK-unsplash.jpg": ("unsplash", "https://unsplash.com/photos/AbCdEfGhIjK"),
            "mountain-landscape-2031539_1920.jpg": ("pixabay", None),
            "mixkit-fast-small-sweep-transition-166.wav": ("mixkit", None),
            "mixkit-a-girl-blowing-a-bubble-gum-at-an-amusement-park-1226-medium.mp4": ("mixkit", None),
        }
        for name, (site, url) in cases.items():
            got = identify(name)
            self.assertIsNotNone(got, name)
            self.assertEqual(got["site"], site, name)
            self.assertEqual(got.get("url"), url, name)
        self.assertTrue(identify("the-cradle-of-your-soul-15700.mp3")["guess"])
        for name in ("VID_20260906_115320856.mp4", "IMG_1234.jpg", "intro-music-2024.mp3", "sunset_beach.jpg"):
            self.assertIsNone(identify(name), name)

    def test_licence_rules(self):
        lic = licence_from_rules("freesound", "License: Creative Commons 0", FREESOUND_PAGE, "wind chime")
        self.assertEqual((lic["licence"], lic["commercial_ok"], lic["attribution_required"]), ("CC0", True, False))
        lic = licence_from_rules("freesound", "This sound is licensed under Attribution NonCommercial 4.0", FREESOUND_PAGE, "wind chime")
        self.assertEqual((lic["licence"], lic["commercial_ok"]), ("CC BY-NC", False))
        lic = licence_from_rules("freesound", PAGES[FREESOUND_PAGE], FREESOUND_PAGE, "wind chime gamelan")
        self.assertEqual(lic["licence"], "CC BY")
        self.assertTrue(lic["attribution_required"])
        self.assertIn("InspectorJ", lic["credit"])
        self.assertEqual(licence_from_rules("mixkit", PAGES[MIXKIT_PAGE], MIXKIT_PAGE)["licence"], "Mixkit Free License")
        self.assertEqual(licence_from_rules("mixkit", "Restricted License applies", MIXKIT_PAGE)["licence"], "Mixkit Restricted License")
        lic = licence_from_rules("pexels", "", PEXELS_PHOTO)
        self.assertEqual((lic["licence"], lic["commercial_ok"], lic["attribution_required"]), ("Pexels License", True, False))

    def test_sites_and_beats(self):
        self.assertEqual(site_for_url("https://images.pexels.com/x.jpg"), "pexels")
        self.assertIsNone(site_for_url("https://notpexels.com/x"))
        beats = clean_beats([{"line": "Hi", "shot": "a city street at night", "search": "city, street!", "kind": "gif"},
                             {"line": "", "shot": ""}, "junk"], 30)
        self.assertEqual(len(beats), 1)
        self.assertEqual(beats[0]["search"], "city street")
        self.assertEqual(beats[0]["kind"], "video")
        self.assertEqual(beats[0]["seconds"], 30.0)


class WebAssetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = load_settings(self.tmp / "home")
        self.settings.inbox_dir = str(self.tmp / "Inbox")
        self.db = Database(self.settings.db_path)
        self.tv = FakeTavily(self.settings, self.db)
        self.session = FakeSession()
        self.saved = []
        self.web = WebAssets(self.settings, self.db, self.tv, None, session=self.session, on_saved=self.saved.append)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_search_filters_sorts_and_caches(self):
        res = self.web.search("sunset beach", "video", 5)
        urls = [i["url"] for i in res["items"]]
        self.assertEqual(urls[0], PEXELS_VIDEO)
        self.assertNotIn("https://example.com/stock/sunset", urls)
        self.assertNotIn("https://www.pexels.com/photo/sunset-1234567/", urls)
        top = res["items"][0]
        self.assertTrue(top["item"])
        self.assertEqual(top["title"], "Waves On A Beach At Sunset")
        self.assertIn("1093662", top["thumb"])
        self.assertEqual(top["licence"]["licence"], "Pexels License")
        body = self.tv.posts[0][1]
        self.assertIn("pexels.com", body["include_domains"])
        self.assertNotIn("unsplash.com", body["include_domains"])
        self.web.search("sunset beach", "video", 5)
        self.assertEqual(len(self.tv.posts), 1)
        self.assertEqual(self.tv.stats["cached"], 1)

    def test_local_mode_turns_tavily_off(self):
        self.settings.privacy_mode = "local"
        self.assertFalse(self.tv.available)
        self.assertIn("Local only", self.tv.why_off())
        with self.assertRaises(TavilyError):
            self.web.search("sunset", "video")
        self.settings.privacy_mode = "standard"

    def test_pick_media(self):
        url = self.web.pick_media("pexels", PEXELS_VIDEO, PAGES[PEXELS_VIDEO], [], "video")
        self.assertEqual(url, "https://videos.pexels.com/video-files/1093662/1093662-hd_1920_1080_30fps.mp4")
        self.assertEqual(self.web.pick_media("pexels", "https://www.pexels.com/photo/a-cat-77777/", "", [], "image"),
                         "https://www.pexels.com/photo/77777/download/")
        self.assertIsNone(self.web.pick_media("mixkit", MIXKIT_PAGE, "no links", [], "audio"))

    def test_save_downloads_into_inbox_with_licence(self):
        out = self.web.save(PEXELS_PHOTO, "image")
        p = Path(out["path"])
        self.assertTrue(p.exists())
        self.assertEqual(p.parent, (self.tmp / "Inbox").resolve())
        self.assertTrue(p.name.startswith("pexels-"))
        self.assertEqual(p.suffix, ".jpeg")
        self.assertEqual(self.saved, [p])
        rec = self.db.download_for(str(p))
        self.assertEqual(rec["page_url"], PEXELS_PHOTO)
        self.assertEqual(rec["licence"]["licence"], "Pexels License")
        self.assertIn("cottonbro", rec["licence"]["credit"])
        self.assertFalse(list(p.parent.glob("*.part")))
        again = self.web.save(PEXELS_PHOTO, "image")
        self.assertNotEqual(again["path"], out["path"])

    def test_save_refuses_web_pages_and_unknown_sites(self):
        PAGES["https://www.pexels.com/photo/html-page-99999/"] = "https://www.pexels.com/x/html/page.jpg"
        from caa.sources import SourceError
        with self.assertRaises(SourceError):
            self.web.save("https://www.pexels.com/photo/html-page-99999/", "image")
        with self.assertRaises(SourceError):
            self.web.save("https://example.com/photo/1", "image")
        self.assertFalse(list((self.tmp / "Inbox").glob("*")))

    def test_find_source(self):
        lic = self.web.find_source("pexels-cottonbro-5698420.jpg")
        self.assertEqual(lic["status"], "found")
        self.assertEqual(lic["source_url"], PEXELS_PHOTO)
        self.assertTrue(lic["commercial_ok"])
        lic = self.web.find_source("mixkit-fast-small-sweep-transition-166.wav")
        self.assertEqual(lic["source_url"], MIXKIT_PAGE)
        self.assertEqual(lic["licence"], "Mixkit Free License")
        lic = self.web.find_source("123456__InspectorJ__wind-chime-gamelan.wav")
        self.assertEqual(lic["licence"], "CC BY")
        self.assertIn("wind chime gamelan", lic["credit"])
        lic = self.web.find_source("pexels-someone-4444444.jpg")
        self.assertEqual(lic["status"], "unverified")
        self.assertEqual(lic["licence"], "Pexels License")
        self.assertIsNone(self.web.find_source("the-cradle-of-your-soul-15700.mp3"))
        self.assertIsNone(self.web.find_source("holiday.mp4"))

    def test_batch_page_reads_fill_the_cache(self):
        n = self.tv.extract_many([PEXELS_PHOTO, FREESOUND_PAGE, "https://www.pexels.com/photo/404404/"], include_images=True)
        self.assertEqual(n, 3)
        self.assertEqual(len(self.tv.posts), 1)
        self.assertEqual(len(self.tv.posts[0][1]["urls"]), 3)
        self.web.find_source("pexels-cottonbro-5698420.jpg")
        self.web.find_source("123456__InspectorJ__wind-chime-gamelan.wav")
        self.assertEqual(len(self.tv.posts), 1)
        self.assertEqual(self.tv.extract_many([PEXELS_PHOTO], include_images=True), 0)

    def test_licence_with_nemotron(self):
        self.web.tf = PlanTokenFactory(self.settings, self.db)
        lic = self.web.check(PEXELS_PHOTO)
        self.assertEqual(lic["method"], "page + nemotron")
        self.assertEqual(lic["credit"], "Photo by cottonbro studio on Pexels")
        lic = self.web.check(FREESOUND_PAGE)
        self.assertEqual(lic["licence"], "CC BY")
        self.assertTrue(lic["commercial_ok"])
        self.assertEqual(lic["note"], "Credit the author in your video description.")
        self.assertIn("InspectorJ", lic["credit"])


class FakeSearch:
    def search(self, q, kind=None, limit=3, use_llm=False):
        if "sunset" in q:
            return {"results": [{"asset_id": 7, "name": "sunset_beach.jpg", "kind": "image", "thumb": "/api/thumb/9", "score": 0.5,
                                 "caption": "A sunset", "hits": [{"start": 0, "end": 0, "tc": "0:00", "caption": "A sunset"}]}]}
        return {"results": []}


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.settings = load_settings(self.tmp / "home")
        self.db = Database(self.settings.db_path)
        self.tv = FakeTavily(self.settings, self.db)

    def tearDown(self):
        self.db.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_plan_with_research_and_nemotron(self):
        tf = PlanTokenFactory(self.settings, self.db)
        plan = BrollPlanner(self.tv, tf, FakeSearch()).plan("where coffee comes from", seconds=30)
        self.assertEqual(plan["title"], "Where coffee comes from")
        self.assertEqual(len(plan["beats"]), 2)
        self.assertEqual(tf.calls.get("reasoning"), 1)
        self.assertFalse(plan["beats"][0]["gap"])
        self.assertEqual(plan["beats"][0]["matches"][0]["name"], "sunset_beach.jpg")
        self.assertTrue(plan["beats"][1]["gap"])
        self.assertEqual((plan["covered"], plan["gaps"]), (1, 1))
        self.assertEqual(plan["facts"][0]["source"]["url"], "https://example.org/coffee")
        self.assertTrue(plan["researched"])
        body = self.tv.posts[0][1]
        self.assertEqual(body["include_answer"], "basic")

    def test_plan_without_nemotron_uses_the_script(self):
        plan = BrollPlanner(self.tv, None, FakeSearch()).plan("", "A sunset over the sea. Then we pick coffee.", 20, research=False)
        self.assertEqual(len(plan["beats"]), 2)
        self.assertIsNone(plan["model"])
        self.assertEqual(plan["beats"][0]["search"], "sunset over sea")
        self.assertFalse(plan["beats"][0]["gap"])
        self.assertEqual(self.tv.posts, [])
        with self.assertRaises(ValueError):
            BrollPlanner(self.tv, None, FakeSearch()).plan("", "")


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg not installed")
class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import requests
        import uvicorn

        from caa.api import create_app
        from caa.services import Services

        cls.requests = requests
        cls.tmp = Path(tempfile.mkdtemp())
        files = make_library(cls.tmp / "lib")
        shutil.copy(files["photo"], cls.tmp / "lib" / "Stills" / "pexels-cottonbro-5698420.jpg")
        s = load_settings(cls.tmp / "home")
        s.inbox_dir = str(cls.tmp / "Inbox")
        tv = FakeTavily(s)
        cls.svc = Services(s, embedder=FallbackEmbedder(), transcriber=Transcriber(), text_embedder=FakeTextEmbedder(),
                           tavily=tv, web_session=FakeSession())
        tv.db = cls.svc.db
        tf = PlanTokenFactory(s, cls.svc.db)
        for obj in (cls.svc, cls.svc.indexer, cls.svc.search, cls.svc.web, cls.svc.broll):
            obj.tf = tf
        cls.server = uvicorn.Server(uvicorn.Config(create_app(cls.svc), host="127.0.0.1", port=8812, log_level="error"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        cls.base = "http://127.0.0.1:8812"
        for _ in range(50):
            try:
                requests.get(cls.base + "/api/status", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        requests.post(cls.base + "/api/folders", json={"path": str(cls.tmp / "lib")})
        cls.wait_idle(11)

    @classmethod
    def wait_idle(cls, n):
        for _ in range(160):
            st = cls.requests.get(cls.base + "/api/status").json()
            if st["indexer"]["state"] == "idle" and st["library"]["indexed"] >= n:
                return st
            time.sleep(0.25)
        raise AssertionError("indexing did not finish")

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.svc.close()
        time.sleep(0.3)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def post(self, path, body):
        return self.requests.post(self.base + path, json=body)

    def test_1_status_and_search(self):
        st = self.requests.get(self.base + "/api/status").json()
        self.assertTrue(st["tavily"]["enabled"])
        r = self.requests.get(self.base + "/api/web/search", params={"q": "sunset beach", "kind": "video"}).json()
        self.assertEqual(r["items"][0]["url"], PEXELS_VIDEO)
        self.assertEqual(self.requests.get(self.base + "/api/web/search").status_code, 400)

    def test_2_save_indexes_with_licence(self):
        r = self.post("/api/web/save", {"url": PEXELS_PHOTO, "kind": "image"})
        self.assertEqual(r.status_code, 200, r.text)
        name = r.json()["name"]
        self.wait_idle(12)
        folders = self.requests.get(self.base + "/api/folders").json()["folders"]
        self.assertTrue(any(f["kind"] == "inbox" for f in folders))
        a = self.svc.db.asset_by_path(r.json()["path"])
        self.assertEqual(a["status"], "indexed")
        self.assertEqual(a["license"]["licence"], "Pexels License")
        self.assertEqual(a["source_url"], PEXELS_PHOTO)
        lst = self.requests.get(self.base + "/api/licences").json()
        self.assertIn(name, [i["name"] for i in lst["items"]])
        self.assertEqual(self.post("/api/web/save", {"url": "https://example.com/x"}).status_code, 400)
        self.assertEqual(self.post("/api/web/save", {}).status_code, 400)

    def test_3_audit_finds_stock_files(self):
        a = self.svc.db.query("SELECT id FROM assets WHERE name='pexels-cottonbro-5698420.jpg'")[0]["id"]
        r = self.post("/api/licences/check", {})
        self.assertEqual(r.status_code, 200)
        for _ in range(40):
            if self.svc.audit.progress["state"] == "idle":
                break
            time.sleep(0.1)
        self.assertGreaterEqual(self.svc.audit.progress["found"], 1)
        lic = self.svc.db.asset(a)["license"]
        self.assertEqual(lic["source_url"], PEXELS_PHOTO)
        r = self.post(f"/api/licences/{a}", {"licence": {"licence": "My own", "commercial_ok": True}})
        self.assertEqual(self.svc.db.asset(a)["license"]["method"], "you")
        other = self.svc.db.query("SELECT id FROM assets WHERE name='sunset_beach.jpg'")[0]["id"]
        self.assertEqual(self.post("/api/licences/check", {"asset_id": other}).status_code, 400)
        summary = self.requests.get(self.base + "/api/licences").json()["summary"]
        self.assertGreaterEqual(summary["checked"], 1)

    def test_4_broll(self):
        r = self.post("/api/broll", {"topic": "where coffee comes from", "seconds": 30})
        self.assertEqual(r.status_code, 200, r.text)
        plan = r.json()
        self.assertEqual(plan["beats"][0]["matches"][0]["name"].split(".")[0] in ("sunset_beach", "pexels-cottonbro-5698420"), True)
        self.assertTrue(plan["beats"][1]["gap"])
        self.assertEqual(self.post("/api/broll", {}).status_code, 400)

    def test_5_local_mode_blocks_web(self):
        self.svc.settings.privacy_mode = "local"
        try:
            self.assertEqual(self.post("/api/web/save", {"url": PEXELS_PHOTO}).status_code, 409)
            r = self.requests.get(self.base + "/api/web/search", params={"q": "sunset"}).json()
            self.assertIn("off", r)
            plan = self.post("/api/broll", {"topic": "coffee"}).json()
            self.assertFalse(plan["researched"])
        finally:
            self.svc.settings.privacy_mode = "standard"


if __name__ == "__main__":
    unittest.main()
