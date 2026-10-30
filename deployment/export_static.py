"""Export only the prepared public sample library; never publish the raw SQLite DB."""
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MEDIA = {'.mp4', '.webm', '.jpg', '.jpeg', '.png', '.webp', '.mp3', '.wav'}


def mapped_file(raw, root, prefix):
    raw = str(raw).replace('\\', '/')
    if raw.startswith(prefix + '/'):
        candidate = root / raw[len(prefix) + 1:]
    else:
        candidate = Path(raw)
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root.resolve()) or not candidate.is_file():
        raise ValueError('Missing or out-of-library file: ' + raw)
    return candidate


def tags(raw):
    try:
        values = json.loads(raw or '[]')
        return [x for x in values if isinstance(x, str)] if isinstance(values, list) else []
    except (ValueError, TypeError):
        return []


def export(db_path, library, seed, output):
    output.mkdir(parents=True, exist_ok=True)
    media = output / 'media'
    media.mkdir(exist_ok=True)

    def copy_file(source):
        if source.suffix.lower() not in MEDIA:
            raise ValueError('Unsupported browser media: ' + source.name)
        if source.stat().st_size >= 95 * 1024 * 1024:
            raise ValueError('Compress or split this file below 95 MiB: ' + source.name)
        name = hashlib.sha256(source.read_bytes()).hexdigest()[:24] + source.suffix.lower()
        target = media / name
        if not target.exists():
            shutil.copyfile(source, target)
        return 'catalog/media/' + name

    conn = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    assets = []
    try:
        for row in conn.execute("SELECT * FROM assets WHERE status='indexed' ORDER BY id"):
            if row['kind'] not in {'video', 'image', 'audio'}:
                continue
            source = mapped_file(row['path'], library, '/library')
            item = {k: row[k] for k in ('id', 'kind', 'name', 'caption', 'transcript', 'duration')}
            item['tags'] = tags(row['tags'])
            item['media'] = copy_file(source)
            item['segments'] = []
            for shot in conn.execute('SELECT * FROM segments WHERE asset_id=? ORDER BY start, id', (row['id'],)):
                segment = {k: shot[k] for k in ('id', 'start', 'end', 'caption', 'transcript')}
                segment['tags'] = tags(shot['tags'])
                if shot['thumb']:
                    segment['thumb'] = copy_file(mapped_file(shot['thumb'], seed, '/data'))
                item['segments'].append(segment)
            item['thumb'] = next((x['thumb'] for x in item['segments'] if x.get('thumb')), None)
            if not item['thumb'] and item['kind'] == 'image':
                item['thumb'] = item['media']
            # Explicit public licence allowlist: no arbitrary nested metadata or source URLs.
            try:
                licence = json.loads(row['license'] or '{}')
            except (ValueError, TypeError):
                licence = {}
            item['license'] = {k: licence[k] for k in ('name', 'status', 'credit', 'attribution', 'commercial')
                               if isinstance(licence, dict) and isinstance(licence.get(k), (str, bool))}
            assets.append(item)
    finally:
        conn.close()
    if not assets:
        raise ValueError('No indexed video, image or audio samples found; prepare the library first.')
    (output / 'index.json').write_text(json.dumps({'version': 1, 'assets': assets}, ensure_ascii=False), encoding='utf-8')
    print(f'Exported {len(assets)} assets and {sum(len(a["segments"]) for a in assets)} segments to {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, default=ROOT / 'seed/library.db')
    parser.add_argument('--library', type=Path, default=ROOT / 'library')
    parser.add_argument('--seed', type=Path, default=ROOT / 'seed')
    parser.add_argument('--output', type=Path, default=ROOT / 'vercel/catalog')
    args = parser.parse_args()
    export(args.db, args.library, args.seed, args.output)
