"""Run inside the index container, using stable /library and /data paths."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor' / 'engine'))
from cloud import ServerSettings as Settings, secret
from caa.services import Services


def main():
    library = Path('/library')
    if not library.exists() or not any(p.is_file() for p in library.rglob('*')):
        raise SystemExit('Add your cleared media to deployment/library first.')
    if any(p.is_symlink() for p in library.rglob('*')):
        raise SystemExit('Use real files, not symbolic links, in the sample library.')
    settings = Settings(home=Path('/data'), privacy_mode='standard' if secret('NEBIUS_API_KEY') else 'local',
                        tokenfactory_base_url=os.environ.get('CAA_TOKENFACTORY_BASE_URL', 'https://api.tokenfactory.nebius.com/v1'),
                        embed_backend='siglip', semantic_search=True, asr_enabled=True)
    settings.ensure_dirs()
    s = Services(settings, start_worker=False, watch=False)
    if s.tf.available:
        settings.models.update(s.tf.resolve_models(apply=False))
    s.embedder.wait()
    s.text_embedder.wait()
    if not s.embedder.supports_text or not s.text_embedder.available:
        raise SystemExit('Models failed to load. Check network/model access, then rerun indexing.')
    s.db.add_folder(str(library))
    # Remove stale index entries when the operator removes sample files.
    for row in s.db.query('SELECT id,path FROM assets'):
        if not Path(row['path']).is_file():
            s.indexer.remove_asset(row['id'])
    s.indexer.scan(retry_errors=True)
    errors = []
    while not s.indexer.q.empty():
        path = s.indexer.q.get()
        try:
            s.indexer.index_file(path)
            print('Indexed:', Path(path).name, flush=True)
        except Exception as exc:
            errors.append(Path(path).name)
            print('Failed:', Path(path).name, type(exc).__name__, flush=True)
        finally:
            s.indexer.release(path)
    s.semantic.sync()
    # Feedback is never shared with the public demo; seed only contains library content.
    s.db.execute('DELETE FROM feedback')
    s.db.execute('DELETE FROM cache')
    failed = s.db.query("SELECT id FROM assets WHERE status != 'indexed'")
    count = s.db.query_one("SELECT count(*) AS n FROM assets WHERE status = 'indexed'")['n']
    s.db.conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    s.db.close()
    print(f'Prepared {count} sample assets; {len(failed)} incomplete.', flush=True)
    if errors or failed or count == 0:
        raise SystemExit('Fix failed or unsupported samples before publishing.')


if __name__ == '__main__':
    main()
