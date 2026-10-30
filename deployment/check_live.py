"""Read-only launch verification: python check_live.py https://your-domain"""
import argparse
import json
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    args = parser.parse_args()
    base = args.url.rstrip('/') + '/'
    if urlparse(base).scheme != 'https':
        parser.error('Use the public HTTPS URL')

    def fetch(path):
        with urllib.request.urlopen(urljoin(base, path), timeout=30) as response:
            return response.read()

    fetch('healthz')
    fetch('sandbox.html')
    config = json.loads(fetch('config.json'))
    if not config.get('downloadUrl') or not config.get('checksumUrl'):
        raise SystemExit('FAIL: Configure the installer and checksum release URLs first.')
    for field in ('downloadUrl', 'checksumUrl'):
        url = config[field]
        if urlparse(url).scheme != 'https':
            raise SystemExit(f'FAIL: {field} must use HTTPS.')
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=30) as response:
            print(field, response.status)
    data = json.loads(fetch('api/assets'))
    if not data.get('results'):
        raise SystemExit('FAIL: The sample library is empty. Prepare your cleared media first.')
    for path in ('api/settings', 'api/folders'):
        try:
            fetch(path)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        raise SystemExit(f'FAIL: Desktop route unexpectedly exposed: {path}')
    print('PASS: HTTPS, release links, populated library and private route restrictions.')
    print('Now manually check a search, video seeking, audio and mobile layout before launch.')


if __name__ == '__main__':
    main()
