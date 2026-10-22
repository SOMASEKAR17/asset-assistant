from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from caa.config import load_settings
from caa.db import Database
from caa.nemotron import TokenFactory

MODELS = ["nvidia/Nemotron-3.5-Super-VL", "nvidia/Nemotron-3-Nano-Omni", "nvidia/nemotron-3-super-120b-a12b",
          "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B", "nvidia/Nemotron-3-Ultra-550b-a55b", "meta-llama/Llama-3.3-70B"]


class Mock(BaseHTTPRequestHandler):
    log: list = []
    fail_json_once = True
    flaky = 0

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.endswith("/models"):
            return self._send(200, {"data": [{"id": m} for m in MODELS]})
        self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Mock.log.append({"auth": self.headers.get("Authorization"), "body": body})
        if Mock.flaky > 0:
            Mock.flaky -= 1
            return self._send(503, {"error": "busy"})
        content = body["messages"][-1]["content"]
        parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
        if any(p.get("type") == "input_audio" for p in parts):
            return self._send(400, {"error": "audio not supported"})
        if "response_format" in body and Mock.fail_json_once:
            Mock.fail_json_once = False
            return self._send(400, {"error": "response_format unsupported"})
        if any("cannot hear" in (p.get("text") or "") for p in parts):
            text = '{"kind": "sfx", "description": "A short airy whoosh", "tags": ["whoosh", "transition"], "energy": "high"}'
        elif any(p.get("type") == "image_url" for p in parts):
            text = '<think>looking</think>{"description": "Fire on green", "tags": ["Fire", "green screen"], "background": "green screen"}'
        else:
            text = 'Sure: {"visual": "", "keywords": ["whoosh"], "kind": "audio", "audio_kind": "sfx", "max_duration": 2}'
        self._send(200, {"choices": [{"message": {"content": text}}]})


class TokenFactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Mock)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["NEBIUS_API_KEY"] = "test-key"
        cls.s = load_settings(cls.tmp)
        cls.s.tokenfactory_base_url = f"http://127.0.0.1:{cls.server.server_address[1]}/v1"
        cls.db = Database(cls.s.db_path)
        cls.tf = TokenFactory(cls.s, cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.db.close()
        os.environ.pop("NEBIUS_API_KEY", None)
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_resolve_models(self):
        r = self.tf.resolve_models(apply=False)
        self.assertEqual(r["vision"], "nvidia/Nemotron-3.5-Super-VL")
        self.assertEqual(r["omni"], "nvidia/Nemotron-3-Nano-Omni")
        self.assertEqual(r["agent"], "nvidia/nemotron-3-super-120b-a12b")
        self.assertEqual(r["fast"], "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
        self.assertEqual(r["reasoning"], "nvidia/Nemotron-3-Ultra-550b-a55b")

    def test_caption_fallback_and_cache(self):
        Mock.log.clear()
        img = Image.new("RGB", (800, 450), (0, 177, 64))
        cap = self.tf.caption_frames([img, img], "fire.mp4", 0, 4)
        self.assertEqual(cap["description"], "Fire on green")
        self.assertEqual(cap["tags"], ["fire", "green screen"])
        self.assertEqual(Mock.log[0]["auth"], "Bearer test-key")
        first = Mock.log[0]["body"]
        self.assertEqual(first["model"], self.s.models["vision"])
        imgs = [p for p in first["messages"][-1]["content"] if p["type"] == "image_url"]
        self.assertEqual(len(imgs), 2)
        self.assertTrue(imgs[0]["image_url"]["url"].startswith("data:image/jpeg;base64,"))
        n = len(Mock.log)
        again = self.tf.caption_frames([img, img], "fire.mp4", 0, 4)
        self.assertEqual(again, cap)
        self.assertEqual(len(Mock.log), n)

    def test_audio_rejected_then_analysis_fallback(self):
        d = self.tf.describe_audio(b"RIFF....", "whoosh.wav", 0.5, 0.5, {"duration": 0.5})
        self.assertEqual(d["_source"], "analysis")
        Mock.log.clear()
        d2 = self.tf.describe_audio(b"RIFF....", "whoosh2.wav", 0.5, 0.5, {"duration": 0.5})
        self.assertEqual(d2["_source"], "analysis")
        self.assertTrue(all(not isinstance(e["body"]["messages"][-1]["content"], list) for e in Mock.log))

    def test_no_omni_falls_back_to_analysis(self):
        r = self.tf.resolve_models([m for m in MODELS if "Omni" not in m], apply=False)
        self.assertEqual(r["omni"], "")
        saved = dict(self.s.models)
        try:
            self.s.models["omni"] = ""
            Mock.log.clear()
            d = self.tf.describe_audio(b"RIFF", "whoosh_fast.wav", 0.5, 0.5, {"duration": 0.5, "attack_ms": 20}, folder="sfx", local_tags=["short"])
            self.assertEqual(d["description"], "A short airy whoosh")
            self.assertEqual(d["_source"], "analysis")
            self.assertEqual(d["_model"], self.s.models["fast"])
            self.assertEqual(Mock.log[-1]["body"]["model"], self.s.models["fast"])
            self.assertIsInstance(Mock.log[-1]["body"]["messages"][-1]["content"], str)
        finally:
            self.s.models.clear()
            self.s.models.update(saved)

    def test_rewrite_and_retry(self):
        Mock.flaky = 1
        plan = self.tf.rewrite_query("short whoosh")
        self.assertEqual(plan["kind"], "audio")
        self.assertEqual(plan["max_duration"], 2.0)

    def test_local_mode_blocks_calls(self):
        self.s.privacy_mode = "local"
        try:
            self.assertFalse(self.tf.available)
            self.assertIsNone(self.tf.rewrite_query("anything"))
        finally:
            self.s.privacy_mode = "standard"


if __name__ == "__main__":
    unittest.main(verbosity=2)
