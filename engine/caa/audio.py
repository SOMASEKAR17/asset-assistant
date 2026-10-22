from __future__ import annotations

import numpy as np


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


def features(samples: np.ndarray, sr: int = 16000) -> dict:
    n = len(samples)
    if n == 0:
        return {"duration": 0.0, "rms_db": -120.0, "peak_db": -120.0}
    x = samples.astype(np.float32)
    duration = n / sr
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt(np.mean(x ** 2)))
    hop = max(1, int(sr * 0.01))
    frames = n // hop
    env = np.sqrt(np.mean(x[: frames * hop].reshape(frames, hop) ** 2, axis=1)) if frames else np.array([rms])
    peak_i = int(np.argmax(env)) if len(env) else 0
    attack_ms = peak_i * 10.0
    thresh = max(env.max() * 0.1, 1e-4) if len(env) else 1e-4
    active = env > thresh
    silence_ratio = float(1 - active.mean()) if len(env) else 1.0
    after = env[peak_i:]
    decay_ms = float(np.argmax(after < env.max() * 0.25) * 10.0) if len(after) and (after < env.max() * 0.25).any() else duration * 1000 - attack_ms
    win = min(n, 4096)
    spec_frames = max(1, min(64, n // win))
    centroids, flat = [], []
    freqs = np.fft.rfftfreq(win, 1 / sr)
    for i in np.linspace(0, n - win, spec_frames).astype(int):
        seg = x[i : i + win] * np.hanning(win)
        mag = np.abs(np.fft.rfft(seg)) + 1e-9
        centroids.append(float(np.sum(freqs * mag) / np.sum(mag)))
        flat.append(float(np.exp(np.mean(np.log(mag))) / np.mean(mag)))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x).astype(np.int8))))) if n > 1 else 0.0
    onset = np.maximum(0, np.diff(env)) if len(env) > 1 else np.array([0.0])
    onsets = int(np.sum(onset > (onset.mean() + 2.5 * onset.std()))) if onset.std() > 0 else 0
    tempo = None
    if duration >= 6 and len(onset) > 200:
        ac = np.correlate(onset - onset.mean(), onset - onset.mean(), mode="full")[len(onset) - 1 :]
        lo, hi = int(60 / 180 * 100), int(60 / 60 * 100)
        if hi < len(ac):
            lag = lo + int(np.argmax(ac[lo:hi]))
            if ac[lag] > 0.1 * ac[0]:
                tempo = round(6000 / lag, 1)
    third = max(1, len(env) // 3)
    trend = float(np.mean(env[-third:]) - np.mean(env[:third])) / (env.max() + 1e-9) if len(env) >= 3 else 0.0
    return {
        "duration": round(duration, 3),
        "rms_db": round(_db(rms), 1),
        "peak_db": round(_db(peak), 1),
        "attack_ms": round(attack_ms, 1),
        "decay_ms": round(float(decay_ms), 1),
        "silence_ratio": round(silence_ratio, 3),
        "centroid_hz": round(float(np.mean(centroids)), 1),
        "flatness": round(float(np.mean(flat)), 3),
        "zcr": round(zcr, 4),
        "onsets_per_s": round(onsets / duration, 2) if duration else 0.0,
        "tempo_bpm": tempo,
        "trend": round(trend, 3),
    }


def tags_for(f: dict) -> list[str]:
    tags: list[str] = []
    d = f.get("duration", 0)
    if d < 2.5:
        tags += ["short", "one-shot", "sfx"]
    elif d < 15:
        tags += ["sfx"]
    elif d >= 30:
        tags += ["long"]
    if f.get("attack_ms", 999) <= 40 and d < 4:
        tags += ["punchy", "hit"]
    if f.get("trend", 0) > 0.35 and d >= 1.5:
        tags += ["riser", "build-up"]
    if f.get("trend", 0) < -0.35 and f.get("attack_ms", 999) <= 80:
        tags += ["impact", "decay"]
    if f.get("flatness", 0) > 0.3:
        tags += ["noisy", "texture"]
        if d < 3:
            tags += ["whoosh", "swoosh", "transition"]
    elif f.get("flatness", 1) < 0.05:
        tags += ["tonal"]
    c = f.get("centroid_hz", 0)
    if c > 3500:
        tags += ["bright"]
    elif c and c < 900:
        tags += ["dark", "low", "bass"]
    if f.get("rms_db", -99) > -14:
        tags += ["loud"]
    elif f.get("rms_db", 0) < -32:
        tags += ["quiet", "soft"]
    if f.get("tempo_bpm"):
        tags += ["rhythmic", "music"]
        bpm = f["tempo_bpm"]
        tags += ["fast" if bpm >= 125 else "slow" if bpm < 90 else "mid-tempo"]
    if f.get("silence_ratio", 0) > 0.6 and d > 5:
        tags += ["sparse"]
    return list(dict.fromkeys(tags))
