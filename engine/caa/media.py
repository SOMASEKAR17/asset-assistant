from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import wave
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

try:
    import cv2
except ImportError:
    cv2 = None

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".mxf", ".mts", ".m2ts", ".wmv", ".flv", ".mpg", ".mpeg", ".3gp"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".psd", ".heic", ".avif"}
AUDIO_EXT = {".wav", ".mp3", ".aac", ".m4a", ".flac", ".ogg", ".aif", ".aiff", ".opus", ".wma"}
TEMPLATE_EXT = {".mogrt", ".aep", ".aet", ".prproj", ".drp", ".drfx", ".setting", ".motn", ".moti", ".moef", ".cube", ".look"}
ALPHA_PIX = ("yuva", "rgba", "bgra", "argb", "abgr", "gbrap", "ya8", "ya16", "rgba64", "bgra64")

_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


_FOUND: dict[str, str] = {}


def _registry_path_dirs() -> list[str]:
    if sys.platform != "win32":
        return []
    import winreg

    dirs: list[str] = []
    for root, sub in ((winreg.HKEY_CURRENT_USER, "Environment"),
                      (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")):
        try:
            with winreg.OpenKey(root, sub) as key:
                val, _ = winreg.QueryValueEx(key, "Path")
                dirs += [os.path.expandvars(d.strip()) for d in str(val).split(";") if d.strip()]
        except OSError:
            continue
    return dirs


def _windows_candidates(exe: str) -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    cands = [Path(d) / exe for d in _registry_path_dirs()]
    cands += [local / "Microsoft" / "WinGet" / "Links" / exe]
    pkgs = local / "Microsoft" / "WinGet" / "Packages"
    if pkgs.exists():
        for pkg in pkgs.glob("*FFmpeg*"):
            cands += sorted(pkg.glob(f"*/bin/{exe}"), reverse=True) + sorted(pkg.glob(f"bin/{exe}"))
    cands += [Path(r"C:\ffmpeg\bin") / exe, Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin" / exe,
              Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin" / exe,
              Path.home() / "scoop" / "shims" / exe]
    return cands


def _bin(name: str) -> str:
    cached = _FOUND.get(name)
    if cached and Path(cached).exists():
        return cached
    env = os.environ.get(f"CAA_{name.upper()}")
    if env and Path(env).exists():
        _FOUND[name] = env
        return env
    exe = name + (".exe" if sys.platform == "win32" else "")
    cands = [base / exe for base in (Path(getattr(sys, "_MEIPASS", "")) / "bin", Path(__file__).resolve().parents[2] / "bin")]
    found = next((str(c) for c in cands if c.is_file()), None) or shutil.which(name)
    if not found and sys.platform == "win32":
        found = next((str(c) for c in _windows_candidates(exe) if c.is_file()), None)
        if found:
            os.environ["PATH"] = str(Path(found).parent) + os.pathsep + os.environ.get("PATH", "")
    if not found:
        raise FileNotFoundError(f"{name} not found. Install FFmpeg (winget install Gyan.FFmpeg) and restart, or set CAA_{name.upper()}.")
    _FOUND[name] = found
    return found


_FROM_SETTINGS: set[str] = set()


def set_ffmpeg_dir(folder: str | None) -> None:
    for name in ("ffmpeg", "ffprobe"):
        _FOUND.pop(name, None)
        key = f"CAA_{name.upper()}"
        exe = Path(folder) / (name + (".exe" if sys.platform == "win32" else "")) if folder else None
        if exe is not None and exe.is_file():
            os.environ[key] = str(exe)
            _FROM_SETTINGS.add(key)
        elif key in _FROM_SETTINGS:
            os.environ.pop(key, None)
            _FROM_SETTINGS.discard(key)


def ffmpeg_available() -> bool:
    try:
        _bin("ffmpeg")
        _bin("ffprobe")
        return True
    except FileNotFoundError:
        return False


def ffmpeg_location() -> str | None:
    try:
        return _bin("ffmpeg")
    except FileNotFoundError:
        return None


def _run(args: list[str], timeout: float = 120) -> bytes:
    proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "ignore").strip()[-400:] or f"{args[0]} failed")
    return proc.stdout


def kind_for(path: str | Path) -> str | None:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in IMAGE_EXT:
        return "image"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in TEMPLATE_EXT:
        return "template"
    return None


def fingerprint(path: str | Path, chunk: int = 1 << 20) -> str:
    p = Path(path)
    size = p.stat().st_size
    h = hashlib.sha1(str(size).encode())
    with p.open("rb") as f:
        h.update(f.read(chunk))
        if size > 2 * chunk:
            f.seek(-chunk, os.SEEK_END)
            h.update(f.read(chunk))
    return h.hexdigest()


def probe(path: str | Path) -> dict:
    out = _run([_bin("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=60)
    data = json.loads(out.decode("utf-8", "ignore") or "{}")
    fmt = data.get("format", {})
    info = {"duration": None, "width": None, "height": None, "fps": None, "has_audio": False, "has_video": False,
            "has_alpha": False, "vcodec": None, "acodec": None, "pix_fmt": None, "bit_rate": None, "tags": {}}
    tags: dict = {}
    for s in data.get("streams", []):
        for k, v in (s.get("tags") or {}).items():
            tags.setdefault(k.lower(), v)
    for k, v in (fmt.get("tags") or {}).items():
        tags[k.lower()] = v
    info["tags"] = tags
    try:
        info["duration"] = float(fmt.get("duration")) if fmt.get("duration") not in (None, "N/A") else None
    except ValueError:
        pass
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not info["has_video"] and s.get("disposition", {}).get("attached_pic", 0) == 0:
            info["has_video"] = True
            w, h = s.get("width"), s.get("height")
            rot = 0
            for sd in s.get("side_data_list", []) or []:
                if "rotation" in sd:
                    rot = int(sd["rotation"])
            if "rotate" in (s.get("tags") or {}):
                rot = int(s["tags"]["rotate"])
            if abs(rot) in (90, 270) and w and h:
                w, h = h, w
            info["width"], info["height"] = w, h
            info["vcodec"] = s.get("codec_name")
            info["pix_fmt"] = s.get("pix_fmt")
            info["has_alpha"] = bool(s.get("pix_fmt") and s["pix_fmt"].startswith(ALPHA_PIX))
            rate = s.get("avg_frame_rate") or s.get("r_frame_rate") or "0/1"
            try:
                num, den = rate.split("/")
                info["fps"] = round(float(num) / float(den), 3) if float(den) else None
            except (ValueError, ZeroDivisionError):
                info["fps"] = None
            if info["duration"] is None and s.get("duration") not in (None, "N/A"):
                info["duration"] = float(s["duration"])
        elif s.get("codec_type") == "audio" and not info["has_audio"]:
            info["has_audio"] = True
            info["acodec"] = s.get("codec_name")
            if info["duration"] is None and s.get("duration") not in (None, "N/A"):
                info["duration"] = float(s["duration"])
    try:
        info["bit_rate"] = int(fmt.get("bit_rate")) if fmt.get("bit_rate") else None
    except ValueError:
        pass
    return info


def open_image(path: str | Path) -> Image.Image:
    img = Image.open(path)
    try:
        img.seek(0)
    except EOFError:
        pass
    img = ImageOps.exif_transpose(img)
    return img


def image_has_alpha(img: Image.Image) -> bool:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        alpha = img.convert("RGBA").getchannel("A")
        lo, _ = alpha.getextrema()
        return lo < 250
    return False


def to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "P"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (24, 24, 24))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return img.convert("RGB")


def _sample_fps(duration: float) -> float:
    if duration <= 300:
        return 2.0
    if duration <= 1800:
        return 1.0
    return 0.5


def low_res_frames(path: str | Path, duration: float, size: tuple[int, int] = (64, 36)) -> tuple[np.ndarray, float]:
    fps = _sample_fps(duration or 0)
    w, h = size
    tail = ["-skip_frame", "noref", "-i", str(path), "-an", "-sn", "-vf", f"fps={fps},scale={w}:{h}:flags=area",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    timeout = max(120, (duration or 60) * 2)
    try:
        raw = _run([_bin("ffmpeg"), "-v", "error", "-hwaccel", "auto"] + tail, timeout=timeout)
        if not raw:
            raise RuntimeError("no frames")
    except Exception:
        raw = _run([_bin("ffmpeg"), "-v", "error"] + tail, timeout=timeout)
    n = len(raw) // (w * h * 3)
    if n == 0:
        return np.zeros((0, h, w, 3), dtype=np.uint8), fps
    return np.frombuffer(raw[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3), fps


_PTS = re.compile(r"pts_time:\s*(-?[0-9.]+)")


def keyframe_samples(path: str | Path, duration: float, size: tuple[int, int] = (64, 36)) -> tuple[np.ndarray, np.ndarray]:
    w, h = size
    proc = subprocess.run([_bin("ffmpeg"), "-hide_banner", "-loglevel", "info", "-skip_frame", "nokey", "-i", str(path), "-an", "-sn",
                           "-vf", f"scale={w}:{h}:flags=area,showinfo", "-fps_mode", "passthrough", "-f", "rawvideo",
                           "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=max(60, (duration or 60)), creationflags=_NO_WINDOW)
    if proc.returncode != 0:
        raise RuntimeError("keyframe decode failed")
    times = [float(x) for x in _PTS.findall(proc.stderr.decode("utf-8", "ignore"))]
    n = min(len(proc.stdout) // (w * h * 3), len(times))
    if n < 2:
        raise RuntimeError("too few keyframes")
    t = np.asarray(times[:n], dtype=np.float64)
    t = t - t.min()
    return np.frombuffer(proc.stdout[: n * w * h * 3], dtype=np.uint8).reshape(n, h, w, 3), t


def sample_frames(path: str | Path, duration: float) -> tuple[np.ndarray, np.ndarray]:
    if duration and duration >= 8:
        try:
            frames, times = keyframe_samples(path, duration)
            gaps = np.diff(times)
            if len(times) >= duration / 1.5 and float(np.median(gaps)) <= 1.05 and float(gaps.max()) <= 3.0:
                return frames, times
        except Exception:
            pass
    frames, fps = low_res_frames(path, duration)
    return frames, np.arange(len(frames), dtype=np.float64) / fps


def _hist(frame: np.ndarray) -> np.ndarray:
    if cv2 is not None:
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256]).flatten()
    else:
        q = (frame // 64).reshape(-1, 3)
        idx = q[:, 0] * 16 + q[:, 1] * 4 + q[:, 2]
        hist = np.bincount(idx, minlength=64).astype(np.float32)
    s = hist.sum()
    return hist / s if s else hist


def _hist_dist(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(max(0.0, 1.0 - np.sum(np.sqrt(a * b)))))


def detect_shots(path: str | Path, duration: float, threshold: float = 0.42, min_shot: float = 1.0,
                 max_shot: float = 12.0, max_shots: int = 300) -> list[tuple[float, float]]:
    if not duration or duration <= 0:
        return [(0.0, 0.0)]
    try:
        frames, stamps = sample_frames(path, duration)
    except Exception:
        frames, stamps = np.zeros((0,)), np.zeros((0,))
    cuts = [0.0]
    if len(frames) > 1:
        prev = _hist(frames[0])
        for i in range(1, len(frames)):
            cur = _hist(frames[i])
            t = float(stamps[i])
            if _hist_dist(prev, cur) > threshold and t - cuts[-1] >= min_shot:
                cuts.append(round(t, 3))
            prev = cur
    bounds = cuts + [float(duration)]
    shots: list[tuple[float, float]] = []
    for s, e in zip(bounds[:-1], bounds[1:]):
        if e - s <= 0:
            continue
        if e - s > max_shot:
            n = int(np.ceil((e - s) / max_shot))
            step = (e - s) / n
            shots.extend((round(s + k * step, 3), round(s + (k + 1) * step, 3)) for k in range(n))
        else:
            shots.append((round(s, 3), round(e, 3)))
    if shots and len(shots) > 1 and shots[-1][1] - shots[-1][0] < min_shot * 0.5:
        last = shots.pop()
        shots[-1] = (shots[-1][0], last[1])
    while len(shots) > max_shots:
        i = min(range(len(shots) - 1), key=lambda k: (shots[k][1] - shots[k][0]) + (shots[k + 1][1] - shots[k + 1][0]))
        shots[i : i + 2] = [(shots[i][0], shots[i + 1][1])]
    return shots or [(0.0, float(duration))]


def _ffmpeg_frame(path: str | Path, t: float, max_side: int = 768) -> Image.Image | None:
    try:
        raw = _run([_bin("ffmpeg"), "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", str(path), "-frames:v", "1",
                    "-vf", f"scale='min({max_side},iw)':-2", "-f", "image2pipe", "-vcodec", "png", "-"], timeout=60)
        return Image.open(io.BytesIO(raw)).convert("RGB") if raw else None
    except Exception:
        return None


def extract_frames(path: str | Path, times: list[float], max_side: int = 768, workers: int = 1) -> list[Image.Image | None]:
    out: list[Image.Image | None] = [None] * len(times)
    if workers > 1 and len(times) > 1:
        def grab(t: float) -> Image.Image | None:
            img = _ffmpeg_frame(path, t, max_side)
            if img is not None and max(img.size) > max_side:
                img.thumbnail((max_side, max_side))
            return img
        with ThreadPoolExecutor(max_workers=min(workers, len(times))) as pool:
            out = list(pool.map(grab, times))
        if all(im is not None for im in out):
            return out
        missing = [i for i, im in enumerate(out) if im is None]
        rest = extract_frames(path, [times[i] for i in missing], max_side, 1)
        for i, im in zip(missing, rest):
            out[i] = im
        return out
    cap = None
    if cv2 is not None:
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            cap = None
    for i, t in enumerate(times):
        img = None
        if cap is not None:
            cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000.0)
            ok, frame = cap.read()
            if ok and frame is not None:
                img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if img is None:
            img = _ffmpeg_frame(path, t, max_side)
        if img is not None and max(img.size) > max_side:
            img.thumbnail((max_side, max_side))
        out[i] = img
    if cap is not None:
        cap.release()
    return out


def keyframe_times(start: float, end: float, n: int) -> list[float]:
    length = max(0.0, end - start)
    if length == 0:
        return [start]
    return [round(start + length * (k + 1) / (n + 1), 3) for k in range(n)]


def save_thumb(img: Image.Image, path: Path, size: int = 640) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    t = to_rgb(img).copy()
    t.thumbnail((size, size))
    t.save(path, "JPEG", quality=80)
    return str(path)


def chroma_ratios(img: Image.Image) -> dict:
    small = to_rgb(img).copy()
    small.thumbnail((160, 160))
    arr = np.asarray(small)
    if cv2 is not None:
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        h, s, v = hsv[..., 0].astype(np.float32), hsv[..., 1].astype(np.float32), hsv[..., 2].astype(np.float32)
        green = (h >= 35) & (h <= 85) & (s >= 90) & (v >= 70)
        blue = (h >= 95) & (h <= 130) & (s >= 110) & (v >= 60)
    else:
        r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), arr[..., 2].astype(int)
        green = (g > 110) & (g > r * 1.4) & (g > b * 1.4)
        blue = (b > 110) & (b > r * 1.4) & (b > g * 1.2)
        h = np.zeros(green.shape, np.float32)
        s = np.full(green.shape, 255.0, np.float32)
        v = arr.max(axis=2).astype(np.float32)
    hh, ww = green.shape
    bh, bw = max(1, hh // 7), max(1, ww // 7)
    border = np.zeros_like(green)
    border[:bh, :] = border[-bh:, :] = True
    border[:, :bw] = border[:, -bw:] = True
    lum = np.asarray(small.convert("L"), dtype=np.float32)
    edges = np.abs(np.diff(lum, axis=1))

    def texture(mask: np.ndarray) -> float:
        m = mask[:, 1:] & mask[:, :-1]
        return float(edges[m].mean()) if m.any() else 99.0

    return {
        "green": float(green.mean()),
        "blue": float(blue.mean()),
        "green_border": float(green[border].mean()),
        "blue_border": float(blue[border].mean()),
        "green_texture": texture(green),
        "blue_texture": texture(blue),
        "green_hue_std": float(h[green].std()) if green.any() else 99.0,
        "green_sat": float(s[green].mean()) if green.any() else 0.0,
    }


def is_chroma_key(r: dict) -> str | None:
    if (r["green"] >= 0.28 and r["green_border"] >= 0.45 and r.get("green_texture", 99.0) < 6.0
            and r.get("green_hue_std", 99.0) < 3.0 and r.get("green_sat", 0.0) >= 140):
        return "green"
    return None


def extract_audio(path: str | Path, start: float = 0.0, duration: float | None = None, sr: int = 16000) -> np.ndarray:
    args = [_bin("ffmpeg"), "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(path)]
    if duration:
        args += ["-t", f"{duration:.3f}"]
    args += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = _run(args, timeout=max(120, (duration or 600) * 0.5))
    return np.frombuffer(raw, dtype=np.float32).copy()


def wav_bytes(samples: np.ndarray, sr: int = 16000) -> bytes:
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def loudest_window(samples: np.ndarray, sr: int, seconds: float) -> tuple[int, int]:
    n = int(seconds * sr)
    if len(samples) <= n:
        return 0, len(samples)
    hop = sr // 4
    energy = np.convolve(samples.astype(np.float32) ** 2, np.ones(hop, dtype=np.float32), mode="valid")[::hop]
    win = max(1, n // hop)
    if len(energy) <= win:
        return 0, n
    sums = np.convolve(energy, np.ones(win), mode="valid")
    i = int(np.argmax(sums)) * hop
    return i, min(len(samples), i + n)


def waveform_image(samples: np.ndarray, path: Path, size: tuple[int, int] = (360, 120), color=(255, 176, 59)) -> str:
    w, h = size
    img = Image.new("RGB", size, (20, 20, 22))
    d = ImageDraw.Draw(img)
    if len(samples):
        cols = np.array_split(np.abs(samples), w // 3)
        peaks = np.array([c.max() if len(c) else 0 for c in cols])
        peaks = peaks / (peaks.max() or 1)
        mid = h / 2
        for i, p in enumerate(peaks):
            x = i * 3 + 1
            amp = max(1.0, p * (h * 0.42))
            d.rectangle([x, mid - amp, x + 1, mid + amp], fill=color)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=85)
    return str(path)


def template_preview(path: str | Path) -> tuple[Image.Image | None, str | None]:
    p = Path(path)
    if zipfile.is_zipfile(p):
        try:
            with zipfile.ZipFile(p) as z:
                names = [n for n in z.namelist() if Path(n).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}]
                names.sort(key=lambda n: (0 if "thumb" in n.lower() or "preview" in n.lower() else 1, -z.getinfo(n).file_size))
                for n in names:
                    try:
                        img = Image.open(io.BytesIO(z.read(n)))
                        img.load()
                        return to_rgb(img), f"{p.name}:{n}"
                    except Exception:
                        continue
        except zipfile.BadZipFile:
            pass
    for sib in sorted(p.parent.glob(p.stem + ".*")):
        if sib == p:
            continue
        k = kind_for(sib)
        if k == "image":
            try:
                return to_rgb(open_image(sib)), sib.name
            except Exception:
                continue
        if k == "video":
            frames = extract_frames(sib, [0.5])
            if frames and frames[0] is not None:
                return frames[0], sib.name
    for cand in ("preview.png", "preview.jpg", "thumb.png", "thumb.jpg", "thumbnail.png", "thumbnail.jpg"):
        q = p.parent / cand
        if q.exists():
            try:
                return to_rgb(open_image(q)), q.name
            except Exception:
                continue
    return None, None
