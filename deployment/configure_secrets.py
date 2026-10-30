"""Copy the owner's existing keys without printing them. Run only on owner's PC."""
import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'vendor' / 'engine'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--from-desktop', action='store_true', required=True)
    parser.parse_args()
    from dotenv import load_dotenv
    from caa.config import _secret, default_home
    for source in (ROOT.parent / '.env', default_home() / '.env'):
        if source.is_file():
            load_dotenv(source, override=False)
    target = ROOT / 'secrets'
    target.mkdir(mode=0o700, exist_ok=True)
    for name in ('NEBIUS_API_KEY', 'TAVILY_API_KEY'):
        value = _secret(name)
        path = target / (name.lower() + '.txt')
        if value:
            path.write_text(value, encoding='utf-8')
            if os.name != 'nt':
                path.chmod(0o600)
            print(name + ': configured (value hidden)')
        elif not path.exists():
            path.write_text('', encoding='utf-8')
            print(name + ': not found; add it to the secret file on the server')


if __name__ == '__main__':
    main()
