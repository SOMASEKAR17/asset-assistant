from __future__ import annotations

import logging
import os
import tempfile
import threading

import numpy as np

from .media import wav_bytes

log = logging.getLogger("caa.asr")


class Transcriber:
    name = "none"
    available = False

    def transcribe(self, samples: np.ndarray, sr: int = 16000) -> list[dict]:
        return []


class ParakeetTranscriber(Transcriber):
    def __init__(self, model_name: str = "nemo-parakeet-tdt-0.6b-v3", model_dir: str | os.PathLike | None = None,
                 quantization: str | None = None, chunk_s: float = 25.0):
        import onnx_asr

        kwargs = {"quantization": quantization} if quantization else {}
        if model_dir is not None:
            os.makedirs(os.path.dirname(os.fspath(model_dir)) or ".", exist_ok=True)
            self.model = onnx_asr.load_model(model_name, os.fspath(model_dir), **kwargs)
        else:
            self.model = onnx_asr.load_model(model_name, **kwargs)
        try:
            self.ts_model = self.model.with_timestamps()
        except Exception:
            self.ts_model = None
        self.name = f"parakeet:{model_name}"
        self.chunk_s = chunk_s
        self.available = True
        self._lock = threading.Lock()

    def _recognize(self, chunk: np.ndarray, sr: int):
        model = self.ts_model or self.model
        try:
            return model.recognize(chunk, sample_rate=sr)
        except TypeError:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                with open(path, "wb") as f:
                    f.write(wav_bytes(chunk, sr))
                return model.recognize(path)
            finally:
                os.unlink(path)

    def transcribe(self, samples: np.ndarray, sr: int = 16000) -> list[dict]:
        out: list[dict] = []
        step = int(self.chunk_s * sr)
        with self._lock:
            for off in range(0, len(samples), step):
                chunk = samples[off : off + step]
                if len(chunk) < sr * 0.5 or float(np.sqrt(np.mean(chunk ** 2))) < 0.003:
                    continue
                base = off / sr
                res = self._recognize(chunk, sr)
                text = getattr(res, "text", res if isinstance(res, str) else "")
                if not text or not str(text).strip():
                    continue
                tokens = getattr(res, "tokens", None)
                stamps = getattr(res, "timestamps", None)
                if tokens and stamps and len(tokens) == len(stamps):
                    out.extend(_group_words(tokens, stamps, base))
                else:
                    out.append({"start": round(base, 2), "end": round(base + len(chunk) / sr, 2), "text": str(text).strip()})
        return out


def _group_words(tokens, stamps, base: float, max_len: float = 6.0) -> list[dict]:
    segs: list[dict] = []
    cur_text, cur_start, cur_end = "", None, None
    for tok, t in zip(tokens, stamps):
        tok = str(tok).replace("▁", " ")
        t = float(t) + base
        if cur_start is None:
            cur_start = t
        cur_text += tok
        cur_end = t
        if (cur_end - cur_start >= max_len and tok.startswith(" ")) or tok.strip() in {".", "?", "!"}:
            if cur_text.strip():
                segs.append({"start": round(cur_start, 2), "end": round(cur_end + 0.3, 2), "text": cur_text.strip()})
            cur_text, cur_start = "", None
    if cur_text.strip() and cur_start is not None:
        segs.append({"start": round(cur_start, 2), "end": round((cur_end or cur_start) + 0.3, 2), "text": cur_text.strip()})
    return segs


_cached: dict[str, Transcriber] = {}


def get_transcriber(enabled: bool, model_name: str, model_dir: str | os.PathLike | None = None,
                    quantization: str | None = None) -> Transcriber:
    if not enabled:
        return Transcriber()
    if model_name in _cached:
        return _cached[model_name]
    try:
        t: Transcriber = ParakeetTranscriber(model_name, model_dir, quantization)
        log.info("Loaded %s", t.name)
    except Exception as exc:
        log.warning("Parakeet unavailable (%s). Transcripts disabled.", exc)
        t = Transcriber()
    _cached[model_name] = t
    return t
