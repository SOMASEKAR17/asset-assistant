import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from caa.config import Settings
from caa.embed import FallbackEmbedder
from caa.services import Services
from caa.asr import Transcriber
from caa.textembed import TextEmbedder
from PIL import Image
from starlette.testclient import TestClient


class SandboxTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.preview').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.preview')
        self.base = Path(self.temp.name)
        self.library = self.base / 'library'
        self.library.mkdir()
        settings = Settings(home=self.base / 'data', privacy_mode='local', asr_enabled=False, semantic_search=False)
        settings.ensure_dirs()
        self.s = Services(settings, embedder=FallbackEmbedder(), transcriber=Transcriber(),
                          text_embedder=TextEmbedder(), start_worker=False, watch=False)
        media = self.library / 'sunset.jpg'
        Image.new('RGB', (40, 30), 'orange').save(media)
        thumb = settings.thumbs_dir / '1.jpg'
        Image.new('RGB', (40, 30), 'orange').save(thumb)
        self.aid = self.s.db.upsert_asset({'path': str(media), 'kind': 'image', 'name': media.name, 'ext': '.jpg',
                                         'status': 'indexed', 'caption': 'Golden sunset over water', 'tags': ['sunset'],
                                         'lat': 12.0, 'lon': 77.0})
        self.sid = self.s.db.add_segment(self.aid, 0, 0, 0, caption='Golden sunset over water', thumb=str(thumb))
        self.s.db.put_fts(self.sid, media.name, 'Golden sunset over water', 'sunset', '', str(self.library))
        self.client = TestClient(server.create_app(self.s, self.library, settings.home, run_jobs=False))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.s.db.close()
        self.temp.cleanup()

    def test_search_is_real_and_private(self):
        response = self.client.get('/api/search?q=sunset&llm=1')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['asset_id'], self.aid)
        self.assertNotIn(str(self.library), response.text)
        self.assertNotIn('lat', response.json()['results'][0])
        self.assertFalse(self.s.tf.available)

    def test_desktop_mutations_are_blocked(self):
        for path in ['/api/folders', '/api/settings', '/api/rescan', '/api/web/save', '/api/broll', '/api/feedback', '/api/inbox']:
            self.assertEqual(self.client.post(path, json={}).status_code, 405, path)
        self.assertEqual(self.client.get('/api/settings').status_code, 404)
        self.assertEqual(self.client.delete('/api/folders/1').status_code, 405)

    def test_only_sample_media_is_served(self):
        self.assertEqual(self.client.get(f'/api/media/{self.aid}').status_code, 200)
        outside = self.base / 'private.jpg'
        outside.write_bytes(b'private')
        self.s.db.update_asset(self.aid, path=str(outside))
        self.assertEqual(self.client.get(f'/api/media/{self.aid}').status_code, 404)
        self.s.db.update_segment(self.sid, thumb=str(outside))
        self.assertEqual(self.client.get(f'/api/thumb/{self.sid}').status_code, 404)

    def test_preview_ranges_and_detail(self):
        response = self.client.get(f'/api/media/{self.aid}', headers={'Range': 'bytes=0-9'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(len(response.content), 10)
        self.assertNotIn(str(self.base), self.client.get(f'/api/assets/{self.aid}').text)

    def test_limits_and_headers(self):
        self.assertEqual(self.client.get('/api/search?q=' + 'a'*301).status_code, 400)
        self.assertEqual(self.client.get('/api/assets?kind=bad').status_code, 400)
        self.assertEqual(self.client.get('/healthz', headers={'host': 'evil.example'}).status_code, 400)
        self.assertIn("frame-ancestors 'none'", self.client.get('/').headers['content-security-policy'])
        with TestClient(server.create_app(self.s, self.library, self.s.settings.home, rate_limit=1, run_jobs=False)) as client:
            self.assertEqual(client.get('/api/assets').status_code, 200)
            self.assertEqual(client.get('/api/assets').status_code, 429)

    def test_pages_and_empty_library(self):
        for path in ['/', '/sandbox.html', '/styles.css', '/sandbox.js']:
            self.assertEqual(self.client.get(path).status_code, 200)
        self.s.db.delete_asset(self.aid)
        self.assertEqual(self.client.get('/api/assets').json()['results'], [])


if __name__ == '__main__':
    unittest.main()
