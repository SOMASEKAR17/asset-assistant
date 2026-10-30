"""One uploaded file per bounded process; stdout/stderr never reach visitors."""
import json
import math
import os
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor' / 'engine'))
from PIL import Image
from cloud import ServerSettings
from caa.services import Services


def validate(path):
    ext = path.suffix.lower()
    if ext in {'.jpg', '.jpeg', '.png', '.webp'}:
        Image.MAX_IMAGE_PIXELS = 20_000_000
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                expected = {'.jpg':'JPEG', '.jpeg':'JPEG', '.png':'PNG', '.webp':'WEBP'}[ext]
                if image.format != expected or image.width * image.height > 20_000_000 or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Unsupported image')
                image.verify()
        return
    with path.open('rb') as stream:
        head = stream.read(16)
    magic = {'.mp4': head[4:8] == b'ftyp', '.webm': head[:4] == b'\x1aE\xdf\xa3',
             '.wav': head[:4] == b'RIFF' and head[8:12] == b'WAVE',
             '.mp3': head[:3] == b'ID3' or (len(head)>1 and head[0] == 255 and head[1] & 224 == 224)}
    if not magic.get(ext):
        raise ValueError('Unsupported media')
    result = subprocess.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe', '-show_format',
                             '-show_streams', '-of', 'json', str(path)], capture_output=True, timeout=20, check=True)
    info = json.loads(result.stdout)
    duration = float(info.get('format', {}).get('duration', 0))
    if not math.isfinite(duration) or not 0 < duration <= 120:
        raise ValueError('Limit clips to two minutes')
    formats = set(info.get('format', {}).get('format_name', '').split(','))
    allowed = {'.mp4': {'mov','mp4'}, '.webm': {'matroska','webm'}, '.mp3': {'mp3'}, '.wav': {'wav'}}
    if not formats.intersection(allowed[ext]):
        raise ValueError('Invalid media container')
    if any(int(s.get('width', 0)) * int(s.get('height', 0)) > 3840*2160 for s in info.get('streams', [])):
        raise ValueError('Limit videos to 4K')


def main():
    home, path = map(Path, sys.argv[1:3])
    validate(path)
    ml = os.environ.get('DEMO_ML', '1') == '1'
    settings = ServerSettings(home=home, privacy_mode='standard', asr_enabled=ml,
                              embed_backend='auto' if ml else 'fallback', semantic_search=ml,
                              max_captioned_shots=2, caption_workers=1, index_workers=1)
    settings.ensure_dirs()
    service = Services(settings, start_worker=False, watch=False)
    try:
        if service.tf.available:
            settings.models.update(service.tf.resolve_models(apply=False))
        service.embedder.wait()
        service.text_embedder.wait()
        service.db.add_folder(str(path.parent))
        service.indexer.index_file(str(path))
        service.semantic.sync()
        asset = service.db.asset_by_path(str(path))
        if not asset or asset['status'] != 'indexed':
            raise RuntimeError('Indexing failed')
        service.db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    finally:
        service.db.close()


if __name__ == '__main__':
    main()
