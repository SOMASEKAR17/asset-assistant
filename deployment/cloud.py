"""Server-only credentials. Never load browser-supplied settings or desktop keys."""
import os
from pathlib import Path
from caa.config import Settings


def secret(name):
    filename = os.environ.get(name + '_FILE')
    if filename:
        try:
            return Path(filename).read_text(encoding='utf-8').strip() or None
        except OSError:
            return None
    return os.environ.get(name) or None


class ServerSettings(Settings):
    @property
    def models_dir(self):
        return Path(os.environ.get('DEMO_ASR_MODELS', str(self.home / 'models')))

    @property
    def nebius_api_key(self):
        return secret('NEBIUS_API_KEY')

    @property
    def tavily_api_key(self):
        return secret('TAVILY_API_KEY')
