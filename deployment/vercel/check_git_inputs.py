"""Verify Vercel's complete source inputs are Git-visible, and private data is ignored."""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'deployment'
required = [BASE / name for name in (
    'vercel.json', '.vercelignore', '.gitignore', 'export_static.py',
    'vercel/build.mjs', 'vercel/sandbox.html', 'vercel/static-sandbox.mjs',
    'vercel/search.mjs', 'vercel/catalog/index.json', 'site/index.html',
    'site/styles.css', 'site/site.js', 'site/config.json',
    'site/media/demo.mp4', 'site/media/demo-poster.jpg')]
required.extend(p for p in (BASE / 'site/fonts').rglob('*') if p.is_file())
catalog = json.loads((BASE / 'vercel/catalog/index.json').read_text(encoding='utf-8'))
for asset in catalog['assets']:
    for ref in [asset['media'], asset.get('thumb'), *[s.get('thumb') for s in asset['segments']]]:
        if ref:
            required.append(BASE / 'vercel' / ref)
required = sorted(set(required))
missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
if missing:
    raise SystemExit('Missing deployment inputs: ' + ', '.join(missing))
paths = [p.relative_to(ROOT).as_posix() for p in required]
result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=ROOT,
                        input=('\0'.join(paths) + '\0').encode(), capture_output=True)
if result.returncode not in (0, 1):
    raise SystemExit(result.stderr)
if result.stdout.strip():
    raise SystemExit('Required deployment files are ignored:\n' + result.stdout.decode().replace('\0', '\n'))
private = ['deployment/secrets/test.txt', 'deployment/.env.local', 'deployment/seed/library.db',
           'deployment/uploads/test.mp4', 'deployment/models/test.onnx',
           'deployment/vercel/public/index.html', 'deployment/.vercel/project.json']
result = subprocess.run(['git', 'check-ignore', '--no-index', '-z', '--stdin'], cwd=ROOT,
                        input=('\0'.join(private) + '\0').encode(), capture_output=True)
if set(result.stdout.decode().rstrip('\0').split('\0')) != set(private):
    raise SystemExit('A private/generated path is no longer ignored.')
print(f'PASS: all {len(required)} Vercel source inputs exist and are Git-visible; private/generated paths remain ignored.')
