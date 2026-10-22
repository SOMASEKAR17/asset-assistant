from __future__ import annotations

import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from caa import audio as audiofx
from caa import media
from caa.asr import Transcriber
from caa.config import load_settings
from caa.db import Database
from caa.embed import FallbackEmbedder
from caa.indexer import Indexer, name_tokens, orientation_tags
from caa.nemotron import clean_plan, extract_json
from caa.search import SearchEngine, fts_query, local_plan
from caa.textembed import SemanticIndex, segment_doc
from caa.vectors import VectorIndex
from fixtures import FakeTextEmbedder, FakeTokenFactory, make_library

HAS_FFMPEG = media.ffmpeg_available()


class UnitTests(unittest.TestCase):
    def test_name_tokens(self):
        self.assertEqual(name_tokens("GreenScreen_Fire-01.mp4"), "green screen fire 01")
        self.assertEqual(name_tokens("whoosh.fast(2).wav"), "whoosh fast 2")

    def test_orientation(self):
        self.assertIn("portrait", orientation_tags(1080, 1920))
        self.assertIn("4k", orientation_tags(3840, 2160))
        self.assertIn("square", orientation_tags(1000, 1000))

    def test_local_plan(self):
        p = local_plan("punchy whoosh under 2 seconds")
        self.assertEqual(p["kind"], "audio")
        self.assertEqual(p["audio_kind"], "sfx")
        self.assertEqual(p["max_duration"], 2.0)
        self.assertIn("swoosh", p["keywords"])
        p = local_plan("vertical green screen clip of fire")
        self.assertTrue(p["green_screen"])
        self.assertEqual(p["orientation"], "portrait")
        self.assertEqual(p["kind"], "video")
        self.assertEqual(local_plan("chill lofi music")["audio_kind"], "music")
        self.assertEqual(local_plan("lower third for names")["kind"], "template")

    def test_fts_query(self):
        q = fts_query(["the punchy whoosh", "a"])
        self.assertIn('"punchy"*', q)
        self.assertNotIn('"the"', q)
        self.assertEqual(fts_query(["a", "of"]), "")

    def test_extract_json(self):
        self.assertEqual(extract_json('<think>hmm {"x":1}</think> here {"a": {"b": "}"}, "c": 2} done'), {"a": {"b": "}"}, "c": 2})
        self.assertEqual(extract_json('```json\n{"k": [1,2]}\n```'), {"k": [1, 2]})
        self.assertIsNone(extract_json("no json"))

    def test_clean_plan(self):
        p = clean_plan({"kind": "Audio", "green_screen": "true", "max_duration": "3", "keywords": "a, b", "orientation": "sideways"})
        self.assertEqual(p["kind"], "audio")
        self.assertTrue(p["green_screen"])
        self.assertEqual(p["max_duration"], 3.0)
        self.assertEqual(p["keywords"], ["a", "b"])
        self.assertIsNone(p["orientation"])

    def test_filename_dates(self):
        from datetime import datetime
        from caa.metadata import from_filename
        cases = {
            "VID_20260906_115320856.mp4": "2026-09-06 11:53:20",
            "IMG_20260906_115320.jpg": "2026-09-06 11:53:20",
            "PXL_20260906_062320123.mp4": "2026-09-06 06:23:20",
            "20260906_115320.mp4": "2026-09-06 11:53:20",
            "Screen Recording 2026-09-06 at 11.53.20.mov": "2026-09-06 11:53:20",
            "WhatsApp Video 2026-09-06 at 11.53.20 AM.mp4": "2026-09-06 11:53:20",
            "DJI_20260906115320_0001_D.MP4": "2026-09-06 11:53:20",
        }
        for name, want in cases.items():
            ts, _ = from_filename(name)
            self.assertEqual(datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), want, name)
        self.assertIsNone(from_filename("sunset_beach.jpg"))
        self.assertEqual(from_filename("VID-20260906-WA0001.mp4")[1], "file name (date only)")

    def test_exif_date_and_gps(self):
        from datetime import datetime
        from caa.metadata import from_exif
        img = Image.new("RGB", (32, 32))
        ex = img.getexif()
        ex[271] = "Canon"
        ex[272] = "Canon EOS R6"
        ex.get_ifd(0x8769)[36867] = "2026:09:06 11:53:20"
        ex.get_ifd(0x8825).update({1: "N", 2: (12.0, 58.0, 9.12), 3: "E", 4: (79.0, 9.0, 21.24)})
        tmp = Path(tempfile.mkdtemp()) / "x.jpg"
        img.save(tmp, exif=ex)
        out = from_exif(Image.open(tmp))
        self.assertEqual(datetime.fromtimestamp(out["captured_at"]).strftime("%H:%M:%S"), "11:53:20")
        self.assertEqual(out["device"], "Canon EOS R6")
        self.assertAlmostEqual(out["lat"], 12.9692, places=3)
        shutil.rmtree(tmp.parent, ignore_errors=True)

    def test_parse_when(self):
        from datetime import date
        from caa.timeq import parse_when
        T = date(2026, 10, 20)
        w = parse_when("11:54am on 6/9/26", "DMY", T)
        self.assertEqual((w["label"], w["point"], w["rest"]), ("6 Sep 2026, around 11:54 am", 11 * 3600 + 54 * 60, ""))
        self.assertEqual(parse_when("6/9/26", "MDY", T)["label"], "9 Jun 2026")
        self.assertEqual(parse_when("13/9/26", "MDY", T)["label"], "13 Sep 2026")
        self.assertIsNone(parse_when("vertical 9:16 clip", "DMY", T))
        self.assertIsNone(parse_when("may contain whoosh", "DMY", T))
        self.assertEqual(parse_when("trees at 5pm", "DMY", T)["rest"], "trees")
        self.assertEqual(parse_when("yesterday morning", "DMY", T)["tod"], [5 * 3600, 12 * 3600])
        w = parse_when("9-6-2026 dji", "DMY", T)
        self.assertEqual((w["label"], w["rest"], w["alt"]["date_label"], w["alt"]["query"]), ("9 Jun 2026", "dji", "6 Sep 2026", "6 Sep 2026 dji"))
        self.assertIsNone(parse_when("13/9/26", "DMY", T)["alt"])
        self.assertIsNone(parse_when("6/6/26", "DMY", T)["alt"])

    def test_grass_is_not_green_screen(self):
        yy, xx = np.mgrid[0:90, 0:160]
        hue_noise = np.sin(xx / 7.0) * np.cos(yy / 5.0)
        r = (60 + 40 * hue_noise).clip(0, 255)
        g = (150 + 50 * np.cos(xx / 11.0 + yy / 9.0)).clip(0, 255)
        b = (30 + 15 * hue_noise).clip(0, 255)
        foliage = np.stack([r, g, b], -1).astype(np.uint8)
        img = Image.fromarray(foliage).resize((640, 360), Image.BILINEAR)
        self.assertIsNone(media.is_chroma_key(media.chroma_ratios(img)))

    def test_chroma(self):
        img = np.zeros((360, 640, 3), np.uint8)
        img[...] = (0, 177, 64)
        img[100:260, 260:380] = (200, 120, 90)
        self.assertEqual(media.is_chroma_key(media.chroma_ratios(Image.fromarray(img))), "green")
        rng = np.random.default_rng(1)
        grass = np.stack([rng.integers(20, 90, (90, 160)), rng.integers(110, 230, (90, 160)), rng.integers(10, 60, (90, 160))], -1).astype(np.uint8)
        self.assertIsNone(media.is_chroma_key(media.chroma_ratios(Image.fromarray(grass).resize((640, 360), Image.NEAREST))))
        sky = np.zeros((360, 640, 3), np.uint8)
        sky[...] = (30, 80, 200)
        self.assertIsNone(media.is_chroma_key(media.chroma_ratios(Image.fromarray(sky))))

    def test_audio_tags(self):
        sr = 16000
        t = np.arange(int(sr * 0.6)) / sr
        noise = np.random.default_rng(0).normal(0, 0.4, len(t)).astype(np.float32) * np.hanning(len(t)).astype(np.float32)
        tags = audiofx.tags_for(audiofx.features(noise, sr))
        self.assertIn("short", tags)
        self.assertIn("whoosh", tags)
        hit = (np.exp(-8 * t) * np.sin(2 * np.pi * 60 * t)).astype(np.float32)
        self.assertIn("punchy", audiofx.tags_for(audiofx.features(hit, sr)))

    def test_vector_index(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            db = Database(tmp / "t.db")
            aid = db.upsert_asset({"path": "/x", "kind": "image", "name": "x", "ext": ".jpg", "status": "indexed"})
            ids = [db.add_segment(aid, i, 0, 0) for i in range(3)]
            vi = VectorIndex(db, "m")
            vi.add(ids[0], np.array([1, 0, 0]))
            vi.add(ids[1], np.array([0, 1, 0]))
            vi.add(ids[2], np.array([0.9, 0.1, 0]))
            hits = vi.search(np.array([1, 0, 0]), 2)
            self.assertEqual([h[0] for h in hits], [ids[0], ids[2]])
            vi.remove([ids[0]])
            self.assertEqual(vi.search(np.array([1, 0, 0]), 1)[0][0], ids[2])
            vi2 = VectorIndex(db, "m")
            self.assertEqual(len(vi2.search(np.array([1, 0, 0]), 5)), 3)
            self.assertEqual(vi.search(np.array([1, 0, 0]), 5, allowed={ids[1]})[0][0], ids[1])
            db.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg not installed")
class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.files = make_library(cls.tmp / "lib")
        cls.settings = load_settings(cls.tmp / "home")
        cls.db = Database(cls.settings.db_path)
        cls.emb = FallbackEmbedder()
        cls.vi = VectorIndex(cls.db, cls.emb.name)
        cls.tf = FakeTokenFactory(cls.settings, cls.db)
        cls.ix = Indexer(cls.settings, cls.db, cls.emb, cls.vi, cls.tf, Transcriber())
        cls.db.add_folder(str(cls.tmp / "lib"))
        cls.ix.scan()
        while not cls.ix.q.empty():
            p = cls.ix.q.get()
            cls.ix.index_file(p)
            cls.ix.release(p)
        cls.se = SearchEngine(cls.db, cls.emb, cls.vi, cls.tf)
        cls.se.date_order = "DMY"

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def asset(self, key):
        return self.db.asset_by_path(str(self.files[key]))

    def test_all_indexed(self):
        st = self.db.stats()
        self.assertEqual(st["total"], 10)
        self.assertEqual(st["errors"], 0)
        self.assertEqual(st["kinds"], {"audio": 3, "image": 2, "template": 1, "video": 4})

    def test_shots(self):
        segs = self.db.segments_for(self.asset("two_shots")["id"])
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[1]["start"], 3.0, delta=0.6)

    def test_flags(self):
        self.assertTrue(self.asset("green")["green_screen"])
        self.assertFalse(self.asset("two_shots")["green_screen"])
        self.assertTrue(self.asset("logo")["has_alpha"])
        v = self.asset("vertical")
        self.assertEqual((v["width"], v["height"]), (360, 640))
        self.assertIn("portrait", v["tags"])
        self.assertIsNotNone(self.db.segments_for(self.asset("template")["id"])[0]["thumb"])

    def test_search_ranking(self):
        cases = {
            "punchy whoosh": "whoosh",
            "green screen fire": "green",
            "guy running in the rain": "vertical",
            "sunset beach": "photo",
            "lower third": "template",
            "chill background music": "music",
            "deep boom impact": "impact",
        }
        for q, key in cases.items():
            res = self.se.search(q)["results"]
            self.assertTrue(res, q)
            self.assertEqual(res[0]["path"], str(self.files[key]), q)

    def test_llm_type_guess_is_not_a_filter(self):
        res = self.se.search("city")
        self.assertEqual(res["plan"]["kind"], "any")
        self.assertEqual(res["plan"]["soft"]["kind"], "image")
        self.assertIn(str(self.files["two_shots"]), [r["path"] for r in res["results"]])
        self.assertEqual(local_plan("trees")["kind"], "any")
        self.assertEqual(local_plan("fire overlay")["kind"], "any")

    def test_local_mode_search(self):
        self.settings.privacy_mode = "local"
        try:
            res = self.se.search("whoosh", use_llm=False)["results"]
            self.assertEqual(res[0]["path"], str(self.files["whoosh"]))
            res = self.se.search("vertical clip", use_llm=False)["results"]
            self.assertEqual(res[0]["path"], str(self.files["vertical"]))
        finally:
            self.settings.privacy_mode = "standard"

    def test_filters(self):
        res = self.se.search("fire", green_screen=True)["results"]
        self.assertTrue(all(r["green_screen"] for r in res))
        res = self.se.search("clip", kind="audio")["results"]
        self.assertTrue(all(r["kind"] == "audio" for r in res))

    def test_feedback_memory(self):
        a = self.asset("impact")
        before = self.se.search("sfx")["results"]
        pos = [r["asset_id"] for r in before].index(a["id"])
        for _ in range(3):
            self.db.add_feedback("like", a["id"])
        after = self.se.search("sfx")["results"]
        self.assertLessEqual([r["asset_id"] for r in after].index(a["id"]), pos)

    def test_reindex_unchanged_skipped(self):
        self.assertEqual(self.ix.scan(), 0)

    def test_reading_a_file_does_not_reindex_it(self):
        p = str(self.files["green"])
        before = self.asset("green")["indexed_at"]
        Path(p).read_bytes()
        self.assertTrue(self.ix.is_current(p))
        self.ix.enqueue(p)
        self.ix.q.put(None)
        self.ix._worker()
        self.assertEqual(self.asset("green")["indexed_at"], before)
        self.assertFalse(self.ix._queued)

    def test_changed_file_is_not_current(self):
        p = self.tmp / "lib" / "Stills" / "touched.png"
        Image.new("RGB", (32, 32), (10, 120, 200)).save(p)
        self.ix.index_file(str(p))
        self.assertTrue(self.ix.is_current(str(p)))
        st = p.stat()
        import os
        os.utime(p, (st.st_atime, st.st_mtime + 30))
        self.assertFalse(self.ix.is_current(str(p)))
        self.ix.remove_path(str(p))
        p.unlink()

    def test_meaning_search_without_nemotron(self):
        sem = SemanticIndex(self.db, FakeTextEmbedder())
        self.assertGreaterEqual(sem.sync(), 10)
        self.assertEqual(sem.sync(), 0)
        se = SearchEngine(self.db, self.emb, self.vi, self.tf, sem)
        se.date_order = "DMY"
        before = self.tf.calls["fast"]
        res = se.search("jogger in a downpour")
        self.assertEqual(self.tf.calls["fast"], before)
        self.assertEqual(res["plan"]["source"], "local")
        self.assertGreater(res["channels"]["meaning"], 0)
        self.assertEqual(res["results"][0]["asset_id"], self.asset("vertical")["id"])
        self.assertIn("meaning", res["results"][0]["hits"][0]["why"])
        self.settings.nemotron_search = True
        try:
            se.search("relaxing beats")
            self.assertEqual(self.tf.calls["fast"], before + 1)
        finally:
            self.settings.nemotron_search = False

    def test_similar_uses_look_and_meaning(self):
        sem = SemanticIndex(self.db, FakeTextEmbedder())
        sem.sync()
        se = SearchEngine(self.db, self.emb, self.vi, self.tf, sem)
        sid = self.db.segments_for(self.asset("vertical")["id"])[0]["id"]
        res = se.similar(sid, 5)
        self.assertEqual(res["channels"], ["look", "meaning"])
        self.assertNotIn(self.asset("vertical")["id"], [r["asset_id"] for r in res["results"]])

    def test_segment_doc_uses_description(self):
        sid = self.db.segments_for(self.asset("green")["id"])[0]["id"]
        doc = segment_doc(self.db.get_fts(sid))
        self.assertIn("flames", doc.lower())
        self.assertNotIn(" b-roll ", f" {doc} ")

    def test_shot_details_stored(self):
        segs = self.db.segments_for(self.asset("green")["id"])
        self.assertTrue(any(isinstance(sg.get("details"), dict) and sg["details"] for sg in segs))

    def test_capture_metadata(self):
        a = self.asset("dated")
        from datetime import datetime
        self.assertEqual(datetime.fromtimestamp(a["captured_at"]).strftime("%Y-%m-%d %H:%M:%S"), "2026-09-06 11:53:20")
        self.assertEqual(a["captured_src"], "file name")
        self.assertAlmostEqual(a["lat"], 12.9692, places=3)
        self.assertAlmostEqual(a["lon"], 79.1559, places=3)
        self.assertIn("SM-S918B", a["device"])

    def test_time_search_jumps_inside_clip(self):
        res = self.se.search("11:54am on 6/9/26")
        self.assertEqual(res["plan"]["when"]["label"], "6 Sep 2026, around 11:54 am")
        top = res["results"][0]
        self.assertEqual(top["path"], str(self.files["dated"]))
        self.assertAlmostEqual(top["hits"][0]["start"], 40.0, delta=1.0)
        self.assertTrue(top["hits"][0]["jump"])
        self.assertEqual(len(res["results"]), 1)
        near = self.se.search("11:58am on 6/9/26")
        self.assertEqual(near["fallback"], "nearest")
        self.assertEqual(near["results"][0]["path"], str(self.files["dated"]))
        self.assertIn("Nothing was recorded on 6 Sep 2026", near["plan"]["when"]["note"])
        self.assertEqual(self.se.search("6 sep 2026")["results"][0]["path"], str(self.files["dated"]))
        other = self.se.search("trees 6/9/26")
        self.assertEqual(other["fallback"], "any_date")
        self.assertNotIn(str(self.files["dated"]), [r["path"] for r in other["results"]])

    def test_ambiguous_date_uses_the_order_that_has_footage(self):
        res = self.se.search("9-6-2026 vid")
        self.assertEqual(res["plan"]["when"]["label"], "6 Sep 2026")
        self.assertIn("Read 9-6-2026 as 6 Sep 2026", res["plan"]["when"]["note"])
        self.assertEqual(res["results"][0]["path"], str(self.files["dated"]))
        res = self.se.search("9/6/2026")
        self.assertEqual(res["results"][0]["path"], str(self.files["dated"]))
        self.assertNotIn("fallback", res)

    def test_meaning_doc_includes_recording_metadata(self):
        from caa.textembed import meta_phrase
        phrase = meta_phrase(self.asset("dated"))
        self.assertIn("recorded on Sunday 6 September 2026 in the morning", phrase)
        self.assertIn("SM-S918B", phrase)

    def test_missing_ffmpeg_blocks_media_only(self):
        tmp = Path(tempfile.mkdtemp())
        orig = media.ffmpeg_available
        try:
            (tmp / "lib").mkdir()
            shutil.copy(self.files["green"], tmp / "lib" / "a.mp4")
            shutil.copy(self.files["whoosh"], tmp / "lib" / "b.wav")
            shutil.copy(self.files["photo"], tmp / "lib" / "c.jpg")
            s = load_settings(tmp / "home")
            db = Database(s.db_path)
            ix = Indexer(s, db, self.emb, VectorIndex(db, self.emb.name), self.tf, Transcriber())
            db.add_folder(str(tmp / "lib"))
            media.ffmpeg_available = lambda: False
            self.assertEqual(ix.scan(), 1)
            self.assertEqual(ix.progress["blocker"]["files"], 2)
            media.ffmpeg_available = orig
            while not ix.q.empty():
                ix.release(ix.q.get())
            self.assertEqual(ix.scan(), 3)
            self.assertIsNone(ix.progress["blocker"])
            db.close()
        finally:
            media.ffmpeg_available = orig
            shutil.rmtree(tmp, ignore_errors=True)

    def test_similar(self):
        seg = self.db.segments_for(self.asset("green")["id"])[0]
        res = self.se.similar(seg["id"])["results"]
        self.assertTrue(res)
        self.assertNotIn(self.asset("green")["id"], [r["asset_id"] for r in res])


@unittest.skipUnless(HAS_FFMPEG, "FFmpeg not installed")
class SlowTokenFactory(FakeTokenFactory):
    def __init__(self, settings, db=None):
        super().__init__(settings, db)
        self.active = 0
        self.peak = 0
        self.guard = threading.Lock()

    def caption_frames(self, images, name, start=0.0, end=0.0, what=None):
        with self.guard:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(0.4)
        try:
            return super().caption_frames(images, name, start, end, what)
        finally:
            with self.guard:
                self.active -= 1


@unittest.skipUnless(HAS_FFMPEG, "ffmpeg not installed")
class ParallelTests(unittest.TestCase):
    def test_shots_are_described_in_parallel(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            files = make_library(tmp / "lib")
            settings = load_settings(tmp / "home")
            settings.caption_workers = 4
            db = Database(settings.db_path)
            emb = FallbackEmbedder()
            vi = VectorIndex(db, emb.name)
            tf = SlowTokenFactory(settings, db)
            ix = Indexer(settings, db, emb, vi, tf, Transcriber())
            db.add_folder(str(tmp / "lib"))
            clip = tmp / "lib" / "Footage" / "four_shots.mp4"
            parts = [str(files[k]) for k in ("two_shots", "green", "vertical")]
            listing = tmp / "parts.txt"
            listing.write_text("".join(f"file '{x}'\n" for x in parts))
            media._run([media._bin("ffmpeg"), "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
                        "-vf", "scale=320:180,setsar=1", "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)])
            aid = ix.index_file(str(clip))
            segs = db.segments_for(aid)
            self.assertGreaterEqual(len(segs), 3)
            self.assertGreaterEqual(tf.peak, 2)
            self.assertEqual(tf.calls["vision"], len(segs))
            db.close()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import requests
        import uvicorn

        from caa.api import create_app
        from caa.services import Services

        cls.requests = requests
        cls.tmp = Path(tempfile.mkdtemp())
        cls.files = make_library(cls.tmp / "lib")
        s = load_settings(cls.tmp / "home")
        cls.svc = Services(s, embedder=FallbackEmbedder(), transcriber=Transcriber(), text_embedder=FakeTextEmbedder())
        cls.svc.tf = FakeTokenFactory(s, cls.svc.db)
        cls.svc.indexer.tf = cls.svc.tf
        cls.svc.search.tf = cls.svc.tf
        cls.server = uvicorn.Server(uvicorn.Config(create_app(cls.svc), host="127.0.0.1", port=8811, log_level="error"))
        threading.Thread(target=cls.server.run, daemon=True).start()
        cls.base = "http://127.0.0.1:8811"
        for _ in range(50):
            try:
                requests.get(cls.base + "/api/status", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        r = requests.post(cls.base + "/api/folders", json={"path": str(cls.tmp / "lib")})
        assert r.status_code == 200, r.text
        for _ in range(120):
            st = requests.get(cls.base + "/api/status").json()
            if st["indexer"]["state"] == "idle" and st["library"]["indexed"] >= 10:
                break
            time.sleep(0.25)

    @classmethod
    def tearDownClass(cls):
        cls.server.should_exit = True
        cls.svc.close()
        time.sleep(0.3)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path, **kw):
        return self.requests.get(self.base + path, **kw)

    def test_status(self):
        st = self.get("/api/status").json()
        self.assertEqual(st["library"]["indexed"], 10)
        self.assertEqual(st["embedder"]["state"], "fallback")
        self.assertEqual(st["semantic"]["state"], "ready")
        self.assertGreaterEqual(st["semantic"]["vectors"], 10)

    def test_settings_keys_and_environment(self):
        post = lambda body: self.requests.post(self.base + "/api/settings", json=body)
        r = post({"tavily_api_key": "tvly-test-123456789", "date_order": "MDY", "tokenfactory_base_url": "https://example.test/v1/"})
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertTrue(d["secrets"]["TAVILY_API_KEY"]["set"])
        self.assertEqual(d["secrets"]["TAVILY_API_KEY"]["hint"], "…6789")
        self.assertNotIn("tvly-test-123456789", r.text)
        self.assertEqual(d["date_order"], "MDY")
        self.assertEqual(d["tokenfactory_base_url"], "https://example.test/v1")
        self.assertEqual(self.svc.search.date_order, "MDY")
        self.assertEqual(post({"date_order": "XYZ"}).status_code, 400)
        self.assertEqual(post({"ffmpeg_dir": str(self.tmp / "missing")}).status_code, 400)
        self.assertEqual(post({"tokenfactory_base_url": "ftp://x"}).status_code, 400)
        d = post({"tavily_api_key": "", "date_order": "auto", "tokenfactory_base_url": ""}).json()
        self.assertFalse(d["secrets"]["TAVILY_API_KEY"]["set"])
        self.assertEqual(d["tokenfactory_base_url"], "https://api.tokenfactory.nebius.com/v1")

    def test_meaning_search_api(self):
        r = self.get("/api/search", params={"q": "jogger in a downpour", "limit": 3}).json()
        self.assertTrue(r["results"])
        self.assertEqual(r["results"][0]["name"], "runner_in_rain_vertical.mp4")
        self.assertLessEqual(len(r["results"]), 3)

    def test_search_and_media(self):
        r = self.get("/api/search", params={"q": "green screen fire"}).json()
        top = r["results"][0]
        self.assertEqual(top["name"], "GreenScreen_Fire_01.mp4")
        self.assertEqual(self.get(top["thumb"]).headers["content-type"], "image/jpeg")
        m = self.get(top["media_url"], headers={"Range": "bytes=10-19"})
        self.assertEqual(m.status_code, 206)
        self.assertEqual(len(m.content), 10)
        self.assertEqual(self.get(top["media_url"], headers={"Range": "bytes=999999999-"}).status_code, 416)

    def test_bad_inputs(self):
        self.assertEqual(self.requests.post(self.base + "/api/folders", json={"path": str(self.tmp / "missing")}).status_code, 400)
        self.assertEqual(self.requests.post(self.base + "/api/feedback", json={"action": "hack"}).status_code, 400)
        self.assertEqual(self.requests.post(self.base + "/api/settings", json={"privacy_mode": "cloud"}).status_code, 400)
        self.assertEqual(self.get("/api/assets/99999").status_code, 404)
        self.assertEqual(self.get("/api/status", headers={"Host": "evil.example"}).status_code, 400)

    def test_watcher_adds_and_removes(self):
        if self.svc.watcher is None or self.svc.watcher.state != "watching":
            self.skipTest("watchdog not installed")
        new = self.tmp / "lib" / "Footage" / "copy_of_fire.mp4"
        shutil.copy(self.files["green"], new)
        for _ in range(60):
            if self.svc.db.asset_by_path(str(new)) and self.svc.db.asset_by_path(str(new))["status"] == "indexed":
                break
            time.sleep(0.25)
        self.assertEqual(self.svc.db.asset_by_path(str(new))["status"], "indexed")
        new.unlink()
        for _ in range(40):
            if not self.svc.db.asset_by_path(str(new)):
                break
            time.sleep(0.25)
        self.assertIsNone(self.svc.db.asset_by_path(str(new)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
