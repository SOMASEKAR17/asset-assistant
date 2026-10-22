from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, fields
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

PRIVACY_MODES = ("local", "standard")
DATE_ORDERS = ("auto", "DMY", "MDY", "YMD")
SECRET_NAMES = ("NEBIUS_API_KEY", "TAVILY_API_KEY")
KEYRING_SERVICE = "CreatorAssetAssistant"

DEFAULT_MODELS = {
    "vision": "nvidia/Nemotron-3.5-Super-VL",
    "omni": "nvidia/Nemotron-3-Nano-Omni",
    "agent": "nvidia/nemotron-3-super-120b-a12b",
    "fast": "nvidia/Nemotron-3-Nano-30B-A3B",
    "reasoning": "nvidia/Nemotron-3-Ultra-550b-a55b",
}

MODEL_HINTS = {
    "vision": ["super-vl", "super_vl", "-vl"],
    "omni": ["omni"],
    "agent": ["3-super", "super-120b"],
    "fast": ["3-nano-30b", "nano-30b", "lightning", "nano"],
    "reasoning": ["3-ultra", "ultra-550b", "ultra"],
}


def default_inbox() -> str:
    return str(Path.home() / "Videos" / "CreatorAssets" / "Inbox")


def default_home() -> Path:
    env = os.environ.get("CAA_HOME")
    if env:
        return Path(env).expanduser()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "CreatorAssetAssistant"
    return Path.home() / ".creator-asset-assistant"


_SAVED: dict[str, str | None] = {}


def _saved(name: str) -> str | None:
    if name not in _SAVED:
        try:
            import keyring

            val = keyring.get_password(KEYRING_SERVICE, name)
        except Exception:
            val = None
        _SAVED[name] = val.strip() if val and val.strip() else None
    return _SAVED[name]


def _secret(name: str) -> str | None:
    val = _saved(name) or os.environ.get(name)
    return val.strip() if val and val.strip() else None




@dataclass
class Settings:
    home: Path = field(default_factory=default_home)
    privacy_mode: str = "standard"
    tokenfactory_base_url: str = "https://api.tokenfactory.nebius.com/v1"
    models: dict = field(default_factory=lambda: dict(DEFAULT_MODELS))
    embed_backend: str = "auto"
    embed_model: str = "google/siglip2-base-patch16-224"
    asr_enabled: bool = True
    asr_model: str = "nemo-parakeet-tdt-0.6b-v3"
    asr_quantization: str | None = None
    max_captioned_shots: int = 12
    keyframes_per_shot: int = 3
    caption_image_size: int = 384
    video_audio_captions: bool = False
    request_timeout: float = 90.0
    search_budget: float = 6.0
    caption_workers: int = 8
    index_workers: int = 2
    top_results: int = 10
    semantic_search: bool = True
    text_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    nemotron_search: bool = False
    date_order: str = "auto"
    ffmpeg_dir: str = ""
    inbox_dir: str = field(default_factory=default_inbox)
    web_results: int = 8
    host: str = "127.0.0.1"
    port: int = 8765
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    @property
    def db_path(self) -> Path:
        return self.home / "library.db"

    @property
    def thumbs_dir(self) -> Path:
        return self.home / "thumbs"

    @property
    def cache_dir(self) -> Path:
        return self.home / "cache"

    @property
    def models_dir(self) -> Path:
        return self.home / "models"

    def asr_model_dir(self) -> Path:
        suffix = f"-{self.asr_quantization}" if self.asr_quantization else ""
        return self.models_dir / f"{self.asr_model}{suffix}"

    @property
    def settings_path(self) -> Path:
        return self.home / "settings.json"

    @property
    def nebius_api_key(self) -> str | None:
        return _secret("NEBIUS_API_KEY")

    @property
    def tavily_api_key(self) -> str | None:
        return _secret("TAVILY_API_KEY")

    @property
    def cloud_enabled(self) -> bool:
        return self.privacy_mode != "local" and bool(self.nebius_api_key)

    def ensure_dirs(self) -> None:
        for p in (self.home, self.thumbs_dir, self.cache_dir):
            p.mkdir(parents=True, exist_ok=True)

    def to_public(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self) if not f.name.startswith("_")}
        d["home"] = str(self.home)
        d["has_nebius_key"] = bool(self.nebius_api_key)
        d["has_tavily_key"] = bool(self.tavily_api_key)
        d["cloud_enabled"] = self.cloud_enabled
        d["secrets"] = {n: self.secret_info(n) for n in SECRET_NAMES}
        d["env_overrides"] = sorted(k for k in ("CAA_PRIVACY_MODE", "CAA_EMBED_BACKEND", "CAA_TOKENFACTORY_BASE_URL", "CAA_HOME")
                                    if os.environ.get(k))
        return d

    def secret_info(self, name: str) -> dict:
        saved = _saved(name)
        env = (os.environ.get(name) or "").strip()
        env_file = self.home / ".env"
        in_file = env_file.exists() and any(ln.startswith(f"{name}=") for ln in env_file.read_text(encoding="utf-8").splitlines())
        val = saved or env
        source = "app" if saved or (env and in_file) else ("environment" if env else None)
        return {"set": bool(val), "source": source, "hint": f"…{val[-4:]}" if val and len(val) > 8 else ("set" if val else "")}

    def set_secret(self, name: str, value: str | None) -> str:
        if name not in SECRET_NAMES:
            raise ValueError(f"Unknown key {name}")
        value = (value or "").strip()
        try:
            import keyring

            if value:
                keyring.set_password(KEYRING_SERVICE, name, value)
            else:
                try:
                    keyring.delete_password(KEYRING_SERVICE, name)
                except Exception:
                    pass
            _SAVED[name] = value or None
            return "app"
        except Exception:
            pass
        env_file = self.home / ".env"
        lines = [ln for ln in (env_file.read_text(encoding="utf-8").splitlines() if env_file.exists() else [])
                 if not ln.startswith(f"{name}=")]
        if value:
            lines.append(f"{name}={value}")
        env_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        if value:
            os.environ[name] = value
        else:
            os.environ.pop(name, None)
        _SAVED[name] = None
        return "file"

    def save(self) -> None:
        self.ensure_dirs()
        persist = {
            "privacy_mode": self.privacy_mode,
            "tokenfactory_base_url": self.tokenfactory_base_url,
            "models": self.models,
            "embed_backend": self.embed_backend,
            "embed_model": self.embed_model,
            "asr_enabled": self.asr_enabled,
            "asr_model": self.asr_model,
            "asr_quantization": self.asr_quantization,
            "max_captioned_shots": self.max_captioned_shots,
            "keyframes_per_shot": self.keyframes_per_shot,
            "caption_image_size": self.caption_image_size,
            "video_audio_captions": self.video_audio_captions,
            "caption_workers": self.caption_workers,
            "index_workers": self.index_workers,
            "top_results": self.top_results,
            "semantic_search": self.semantic_search,
            "text_model": self.text_model,
            "nemotron_search": self.nemotron_search,
            "date_order": self.date_order,
            "ffmpeg_dir": self.ffmpeg_dir,
            "inbox_dir": self.inbox_dir,
            "web_results": self.web_results,
            "port": self.port,
        }
        with self._lock:
            tmp = self.settings_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(persist, indent=2), encoding="utf-8")
            tmp.replace(self.settings_path)

    def update(self, data: dict) -> None:
        if "privacy_mode" in data:
            if data["privacy_mode"] not in PRIVACY_MODES:
                raise ValueError(f"privacy_mode must be one of {PRIVACY_MODES}")
            self.privacy_mode = data["privacy_mode"]
        if "models" in data and isinstance(data["models"], dict):
            for k, v in data["models"].items():
                if k in DEFAULT_MODELS and v is not None:
                    v = str(v).strip()
                    self.models[k] = v if v or k == "omni" else DEFAULT_MODELS[k]
        if "tokenfactory_base_url" in data:
            url = str(data["tokenfactory_base_url"] or "").strip().rstrip("/") or "https://api.tokenfactory.nebius.com/v1"
            if not url.startswith(("http://", "https://")):
                raise ValueError("The Token Factory URL must start with https://")
            self.tokenfactory_base_url = url
        if "date_order" in data:
            order = str(data["date_order"] or "auto")
            if order not in DATE_ORDERS:
                raise ValueError(f"date_order must be one of {DATE_ORDERS}")
            self.date_order = order
        if "ffmpeg_dir" in data:
            d = str(data["ffmpeg_dir"] or "").strip().strip('"')
            if d and not Path(d).is_dir():
                raise ValueError(f"Folder not found: {d}")
            self.ffmpeg_dir = d
        if "inbox_dir" in data:
            d = str(data["inbox_dir"] or "").strip().strip('"') or default_inbox()
            try:
                Path(d).expanduser().mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise ValueError(f"Cannot use this Inbox folder: {exc}") from exc
            self.inbox_dir = d
        for name in SECRET_NAMES:
            key = name.lower()
            if key in data and data[key] is not None:
                self.set_secret(name, str(data[key]))
        for key in ("asr_enabled", "video_audio_captions", "nemotron_search", "semantic_search"):
            if key in data:
                setattr(self, key, bool(data[key]))
        for key in ("max_captioned_shots", "keyframes_per_shot"):
            if key in data:
                setattr(self, key, max(1, int(data[key])))
        for key, hi in (("top_results", 200), ("caption_workers", 16), ("index_workers", 4), ("web_results", 20)):
            if key in data:
                setattr(self, key, min(hi, max(1, int(data[key]))))
        self.save()


def load_settings(home: str | Path | None = None) -> Settings:
    home_path = Path(home).expanduser() if home else default_home()
    if load_dotenv:
        for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env", home_path / ".env"):
            if candidate.exists():
                load_dotenv(candidate, override=False)
    s = Settings(home=home_path)
    s.ensure_dirs()
    if s.settings_path.exists():
        try:
            data = json.loads(s.settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        for k, v in data.items():
            if k == "models" and isinstance(v, dict):
                s.models.update(v)
            elif hasattr(s, k) and not k.startswith("_") and k != "home":
                setattr(s, k, v)
    if os.environ.get("CAA_PRIVACY_MODE") in PRIVACY_MODES:
        s.privacy_mode = os.environ["CAA_PRIVACY_MODE"]
    if os.environ.get("CAA_EMBED_BACKEND"):
        s.embed_backend = os.environ["CAA_EMBED_BACKEND"]
    if os.environ.get("CAA_TOKENFACTORY_BASE_URL"):
        s.tokenfactory_base_url = os.environ["CAA_TOKENFACTORY_BASE_URL"]
    return s
