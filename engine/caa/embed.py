from __future__ import annotations

import hashlib
import logging
import threading

import numpy as np
from PIL import Image

from .media import to_rgb
from .vectors import normalize

log = logging.getLogger("caa.embed")


class Embedder:
    name = "base"
    dim = 0
    supports_text = False

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        raise NotImplementedError

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        raise NotImplementedError


class FallbackEmbedder(Embedder):
    name = "fallback-color-layout-v1"
    dim = 256
    supports_text = False

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        out = []
        for img in images:
            rgb = to_rgb(img).resize((16, 9))
            arr = np.asarray(rgb.convert("HSV"), dtype=np.float32) / 255.0
            layout = arr.reshape(-1, 3)[:, :2].reshape(-1)[:216]
            hist = np.histogram(arr[..., 0], bins=24, range=(0, 1), weights=arr[..., 1])[0]
            sat = np.histogram(arr[..., 2], bins=16, range=(0, 1))[0]
            v = np.concatenate([layout, hist / (hist.sum() or 1), sat / (sat.sum() or 1)])
            v = np.pad(v, (0, max(0, self.dim - len(v))))[: self.dim]
            out.append(v)
        return normalize(np.vstack(out)) if out else np.zeros((0, self.dim), dtype=np.float32)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        out = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            for tok in t.lower().split():
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0
            out.append(v)
        return normalize(np.vstack(out)) if out else np.zeros((0, self.dim), dtype=np.float32)


class SiglipEmbedder(Embedder):
    supports_text = True

    def __init__(self, model_id: str, device: str | None = None):
        import torch
        import transformers
        from transformers import AutoModel, AutoProcessor

        transformers.logging.set_verbosity_error()
        try:
            transformers.utils.logging.disable_progress_bar()
        except Exception:
            pass

        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype = torch.float16 if self.device == "cuda" else torch.float32
        major, minor = (int(p) for p in transformers.__version__.split(".")[:2])
        kw = {"dtype": dtype} if (major, minor) >= (4, 56) else {"torch_dtype": dtype}
        self.model = AutoModel.from_pretrained(model_id, **kw).to(self.device).eval()
        self.processor = AutoProcessor.from_pretrained(model_id)
        self.dtype = dtype
        self.name = f"siglip:{model_id}"
        self._lock = threading.Lock()
        with self._lock, torch.no_grad():
            probe = self._text_features(["test"])
        self.dim = int(probe.shape[-1])

    def _as_tensor(self, out):
        if hasattr(out, "pooler_output") and out.pooler_output is not None:
            return out.pooler_output
        if hasattr(out, "image_embeds") and out.image_embeds is not None:
            return out.image_embeds
        if hasattr(out, "text_embeds") and out.text_embeds is not None:
            return out.text_embeds
        if isinstance(out, (tuple, list)):
            return out[0]
        return out

    def _text_features(self, texts: list[str]):
        inputs = self.processor(text=[t.lower() for t in texts], padding="max_length", max_length=64, truncation=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        return self._as_tensor(self.model.get_text_features(**inputs))

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        with self._lock, self.torch.no_grad():
            feats = self._text_features(texts)
        return normalize(feats.float().cpu().numpy())

    def embed_images(self, images: list[Image.Image]) -> np.ndarray:
        if not images:
            return np.zeros((0, self.dim), dtype=np.float32)
        outs = []
        with self._lock, self.torch.no_grad():
            for i in range(0, len(images), 16):
                batch = [to_rgb(im) for im in images[i : i + 16]]
                inputs = self.processor(images=batch, return_tensors="pt")
                inputs = {k: (v.to(self.device, dtype=self.dtype) if v.is_floating_point() else v.to(self.device)) for k, v in inputs.items()}
                feats = self._as_tensor(self.model.get_image_features(**inputs))
                outs.append(feats.float().cpu().numpy())
        return normalize(np.vstack(outs))


_cached: dict[str, Embedder] = {}


def get_embedder(backend: str = "auto", model_id: str = "google/siglip2-base-patch16-224") -> Embedder:
    key = f"{backend}:{model_id}"
    if key in _cached:
        return _cached[key]
    emb: Embedder
    if backend == "fallback":
        emb = FallbackEmbedder()
    else:
        try:
            emb = SiglipEmbedder(model_id)
            log.info("Loaded %s (dim %s) on %s", emb.name, emb.dim, getattr(emb, "device", "?"))
        except Exception as exc:
            if backend == "siglip":
                raise
            log.warning("SigLIP unavailable (%s). Using fallback embedder: text-to-image search disabled.", exc)
            emb = FallbackEmbedder()
    _cached[key] = emb
    return emb
