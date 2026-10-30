import io
import os
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import server
from cloud import ServerSettings
from uploads import COOKIE, UploadStore
from upload_worker import validate
from caa.config import Settings
from caa.services import Services
from caa.embed import FallbackEmbedder
from caa.textembed import TextEmbedder
from caa.asr import Transcriber
from caa.db import Database
from PIL import Image
from starlette.testclient import TestClient
from starlette.exceptions import HTTPException


class UploadTests(unittest.TestCase):
    def setUp(self):
        (ROOT / '.preview').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / '.preview')
        self.root = Path(self.temp.name)
        settings = Settings(home=self.root / 'data', privacy_mode='local', asr_enabled=False, semantic_search=False)
        settings.ensure_dirs()
        self.s = Services(settings, embedder=FallbackEmbedder(), text_embedder=TextEmbedder(), transcriber=Transcriber(), start_worker=False, watch=False)
        self.app = server.create_app(self.s, self.root/'library', settings.home, run_jobs=False)
        self.client = TestClient(self.app, base_url='https://testserver')
        self.client.__enter__()
        self.headers = {'X-Upload-Intent':'1', 'Origin':'https://testserver'}
        image = io.BytesIO(); Image.new('RGB',(10,10),'orange').save(image, format='PNG')
        self.image = image.getvalue()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.s.db.close()
        self.temp.cleanup()

    def start(self):
        response = self.client.post('/api/private/session', headers=self.headers)
        self.assertEqual(response.status_code,200)
        return self.client.cookies.get(COOKIE)

    def upload(self, **kwargs):
        return self.client.post('/api/private/upload?folder=My%20folder', headers={**self.headers,'X-File-Name':'sample.png'}, content=kwargs.get('content', self.image))

    def test_secure_cookie_and_upload_folder(self):
        response = self.client.post('/api/private/session',headers=self.headers)
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie); self.assertIn('secure',cookie); self.assertIn('samesite=strict',cookie)
        response = self.upload()
        self.assertEqual(response.status_code,202)
        self.assertNotIn(str(self.root),response.text)
        listing = self.client.get('/api/private/jobs')
        self.assertEqual(listing.json()['files'][0]['folder'],'My folder')
        self.assertEqual(listing.headers['cache-control'],'private, no-store')

    def test_no_upload_without_session_or_intent(self):
        self.assertEqual(self.upload().status_code,401)
        self.assertEqual(self.client.post('/api/private/session').status_code,403)
        self.assertEqual(self.client.post('/api/private/session',headers={**self.headers,'Origin':'https://evil.example'}).status_code,403)

    def test_oversize_stream_and_cleanup(self):
        self.start()
        with patch('private_api.MAX_FILE', 8), patch('uploads.MAX_FILE', 8):
            response = self.upload(content=iter([b'12345',b'67890']))
        self.assertEqual(response.status_code,413)
        self.assertEqual(self.client.get('/api/private/jobs').json()['files'],[])
        self.assertFalse(list((self.root/'uploads').glob('*/files/*/*/*.png')))

    def test_filename_and_extension_validation(self):
        self.start()
        for name in ('../secret.png','..%2Fsecret.png','script.html','attack.exe'):
            response = self.client.post('/api/private/upload', headers={**self.headers,'X-File-Name':name}, content=b'abc')
            self.assertIn(response.status_code,(400,415))

    def seed_private(self, token, name):
        store = self.app.state.uploads
        owner = store.resolve(token)
        home = store.directory(owner['id'])/'data'
        home.mkdir(parents=True,exist_ok=True)
        path = store.directory(owner['id'])/'files'/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(self.image)
        db = Database(home/'library.db')
        aid = db.upsert_asset({'path':str(path),'name':name,'kind':'image','ext':'.png','status':'indexed','caption':name})
        sid = db.add_segment(aid,0,0,0,caption=name)
        db.put_fts(sid,name,name,'','','')
        db.close()
        return aid, owner

    def test_sessions_cannot_read_each_others_assets(self):
        token_a = self.start()
        aid, _ = self.seed_private(token_a,'private-alpha.png')
        self.assertEqual(self.client.get(f'/api/private/media/{aid}').status_code,200)
        self.client.cookies.clear()
        token_b = self.start()
        self.assertNotEqual(token_a,token_b)
        self.assertEqual(self.client.get(f'/api/private/assets/{aid}').status_code,404)
        self.assertEqual(self.client.get(f'/api/private/media/{aid}').status_code,404)
        self.assertEqual(self.client.get('/api/private/search?q=alpha').json()['results'],[])
        self.assertEqual(self.client.get('/api/assets').json()['results'],[])
        self.assertEqual(self.client.get('/api/private/jobs').json()['files'],[])

    def test_expiry_denies_access_and_deletes_files(self):
        token = self.start(); aid, owner = self.seed_private(token,'expired.png')
        store = self.app.state.uploads
        store.db.execute('UPDATE sessions SET expires=? WHERE id=?',(time.time()-1,owner['id'])); store.db.commit()
        self.assertEqual(self.client.get(f'/api/private/media/{aid}').status_code,401)
        store.cleanup()
        self.assertFalse(store.directory(owner['id']).exists())

    def test_cloud_key_stays_server_side_and_errors_are_generic(self):
        self.start()
        key = self.root/'key.txt'; key.write_text('secret-test-sentinel',encoding='utf8')
        with patch.dict(os.environ,{'TAVILY_API_KEY_FILE':str(key),'NEBIUS_API_KEY_FILE':str(key)}):
            self.assertEqual(ServerSettings().tavily_api_key,'secret-test-sentinel')
            for path in ('/api/status','/api/private/jobs','/config.json','/api/settings','/secrets/tavily_api_key.txt'):
                self.assertNotIn('secret-test-sentinel',self.client.get(path).text)
            with patch('caa.tavily.Tavily.search',side_effect=RuntimeError('secret-test-sentinel')):
                response = self.client.post('/api/cloud/search',headers=self.headers,json={'query':'sunset'})
                self.assertEqual(response.status_code,502)
                self.assertNotIn('secret-test-sentinel',response.text)

    def test_budget_persists_across_restart(self):
        store = self.app.state.uploads
        for _ in range(10): store.cloud_budget('same-session')
        with self.assertRaises(HTTPException): store.cloud_budget('same-session')
        other = UploadStore(store.root,run_jobs=False)
        try:
            with self.assertRaises(HTTPException): other.cloud_budget('same-session')
        finally: other.close()

    def test_real_file_validation(self):
        valid = self.root/'valid.png'; valid.write_bytes(self.image)
        validate(valid)
        bad = self.root/'fake.png'; bad.write_bytes(b'<html>not an image</html>')
        with self.assertRaises(Exception): validate(bad)
        bad_video = self.root/'fake.mp4'; bad_video.write_bytes(b'#EXTM3U\nhttp://internal/secret')
        with self.assertRaises(ValueError): validate(bad_video)

    def test_worker_indexes_real_upload_without_paid_calls(self):
        token = self.start()
        self.assertEqual(self.upload().status_code,202)
        store = self.app.state.uploads
        owner = store.resolve(token)
        job = store.db.execute('SELECT * FROM jobs WHERE sid=?',(owner['id'],)).fetchone()
        home = store.directory(owner['id'])/'data'
        env = {**os.environ,'DEMO_ML':'0','NEBIUS_API_KEY':'','TAVILY_API_KEY':'',
               'NEBIUS_API_KEY_FILE':'','TAVILY_API_KEY_FILE':''}
        result = subprocess.run([sys.executable,str(ROOT/'upload_worker.py'),str(home),job['path']],
                                env=env,capture_output=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
        assets = self.client.get('/api/private/assets').json()['results']
        self.assertEqual(len(assets),1)
        self.assertTrue(assets[0]['thumb'].startswith('/api/private/thumb/'))
        self.assertEqual(self.client.get(assets[0]['thumb']).status_code,200)
        self.assertEqual(self.client.get(assets[0]['media_url']).status_code,200)


if __name__ == '__main__': unittest.main()
