from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

FILENAME_PATTERNS = [
    re.compile(r"(?<!\d)(?P<y>20\d{2})(?P<mo>[01]\d)(?P<d>[0-3]\d)[_\-T ]?(?P<h>[0-2]\d)(?P<mi>[0-5]\d)(?P<s>[0-5]\d)(?P<ms>\d{3})?(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>20\d{2})[-_.](?P<mo>[01]?\d)[-_.](?P<d>[0-3]?\d)(?:[ _T]+(?:at[ _]+)?(?P<h>[0-2]?\d)[.:\-_](?P<mi>[0-5]\d)(?:[.:\-_](?P<s>[0-5]\d))?\s*(?P<ap>[AaPp][Mm])?)?"),
    re.compile(r"(?<!\d)(?P<y>20\d{2})(?P<mo>[01]\d)(?P<d>[0-3]\d)(?!\d)"),
]

QUICKTIME_ISO6709 = re.compile(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)")


def _mk_local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, s: int = 0, ms: int = 0) -> float | None:
    try:
        return datetime(y, mo, d, h, mi, s, ms * 1000).timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def from_filename(name: str) -> tuple[float, str] | None:
    stem = Path(name).stem
    for i, pat in enumerate(FILENAME_PATTERNS):
        m = pat.search(stem)
        if not m:
            continue
        g = m.groupdict()
        y, mo, d = int(g["y"]), int(g["mo"]), int(g["d"])
        if not (2000 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        h = int(g.get("h") or 0)
        mi = int(g.get("mi") or 0)
        s = int(g.get("s") or 0)
        ms = int(g.get("ms") or 0) if i == 0 else 0
        ap = (g.get("ap") or "").lower()
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        ts = _mk_local(y, mo, d, h, mi, s, ms)
        if ts is not None:
            precise = g.get("h") is not None
            return ts, "file name" if precise else "file name (date only)"
    return None


def _parse_iso(value: str) -> float | None:
    v = str(value).strip()
    if not v or v.startswith("0000") or v.startswith("1904-01-01") or v.startswith("1970-01-01"):
        return None
    v = v.replace("Z", "+00:00")
    v = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", v)
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        try:
            dt = datetime.strptime(v[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def from_container(tags: dict) -> tuple[float, str] | None:
    t = {k.lower(): v for k, v in (tags or {}).items()}
    for key in ("com.apple.quicktime.creationdate",):
        if t.get(key):
            ts = _parse_iso(t[key])
            if ts:
                return ts, "camera metadata"
    for key in ("creation_time", "date", "com.android.capture.time"):
        if t.get(key):
            ts = _parse_iso(t[key])
            if ts:
                return ts, "camera metadata"
    return None


def gps_from_tags(tags: dict) -> tuple[float, float] | None:
    t = {k.lower(): v for k, v in (tags or {}).items()}
    for key in ("com.apple.quicktime.location.iso6709", "location", "location-eng", "com.android.location"):
        if t.get(key):
            m = QUICKTIME_ISO6709.match(str(t[key]).strip())
            if m:
                lat, lon = float(m.group(1)), float(m.group(2))
                if -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0.0, 0.0):
                    return round(lat, 6), round(lon, 6)
    return None


def device_from_tags(tags: dict) -> str | None:
    t = {k.lower(): str(v).strip() for k, v in (tags or {}).items() if v}
    make = t.get("com.apple.quicktime.make") or t.get("com.android.manufacturer") or t.get("make")
    model = t.get("com.apple.quicktime.model") or t.get("com.android.model") or t.get("model")
    return _join_device(make, model)


def _join_device(make: str | None, model: str | None) -> str | None:
    make = (make or "").strip().strip("\x00")
    model = (model or "").strip().strip("\x00")
    if model and make and model.lower().startswith(make.lower()):
        return model
    out = " ".join(p for p in (make.title() if make.isupper() or make.islower() else make, model) if p)
    return out or None


def _rational(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        try:
            return x[0] / x[1]
        except Exception:
            return 0.0


def _dms(vals, ref) -> float | None:
    try:
        d, m, s = (_rational(v) for v in vals)
    except Exception:
        return None
    val = d + m / 60 + s / 3600
    if str(ref).upper().startswith(("S", "W")):
        val = -val
    return val


def from_exif(img: Image.Image) -> dict:
    out: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    if not exif:
        return out
    try:
        sub = exif.get_ifd(0x8769)
    except Exception:
        sub = {}
    raw = sub.get(36867) or sub.get(36868) or exif.get(306)
    offset = sub.get(36881) or sub.get(36880)
    if raw:
        try:
            dt = datetime.strptime(str(raw).strip("\x00 ")[:19], "%Y:%m:%d %H:%M:%S")
            if offset and re.match(r"^[+-]\d{2}:\d{2}$", str(offset)):
                sign = 1 if str(offset)[0] == "+" else -1
                hh, mm = str(offset)[1:].split(":")
                tz = timezone(sign * timedelta(hours=int(hh), minutes=int(mm)))
                out["captured_at"] = dt.replace(tzinfo=tz).timestamp()
            else:
                out["captured_at"] = dt.timestamp()
            out["captured_src"] = "photo EXIF"
        except ValueError:
            pass
    dev = _join_device(exif.get(271), exif.get(272))
    if dev:
        out["device"] = dev
    try:
        gps = exif.get_ifd(0x8825)
    except Exception:
        gps = {}
    if gps and 2 in gps and 4 in gps:
        lat = _dms(gps[2], gps.get(1, "N"))
        lon = _dms(gps[4], gps.get(3, "E"))
        if lat is not None and lon is not None and (lat, lon) != (0.0, 0.0):
            out["lat"], out["lon"] = round(lat, 6), round(lon, 6)
    return out


def collect(path: str, tags: dict | None = None, img: Image.Image | None = None) -> dict:
    out: dict = {"captured_at": None, "captured_src": None, "lat": None, "lon": None, "device": None}
    exif = from_exif(img) if img is not None else {}
    fn = from_filename(Path(path).name)
    cont = from_container(tags or {})
    if fn and fn[1] == "file name":
        out["captured_at"], out["captured_src"] = fn
    elif exif.get("captured_at"):
        out["captured_at"], out["captured_src"] = exif["captured_at"], exif["captured_src"]
    elif cont:
        out["captured_at"], out["captured_src"] = cont
    elif fn:
        out["captured_at"], out["captured_src"] = fn
    else:
        try:
            out["captured_at"], out["captured_src"] = os.stat(path).st_mtime, "file date"
        except OSError:
            pass
    gps = gps_from_tags(tags or {})
    if gps:
        out["lat"], out["lon"] = gps
    elif "lat" in exif:
        out["lat"], out["lon"] = exif["lat"], exif["lon"]
    out["device"] = device_from_tags(tags or {}) or exif.get("device")
    return out


def search_words(meta: dict) -> str:
    words = []
    ts = meta.get("captured_at")
    if ts and meta.get("captured_src") != "file date":
        dt = datetime.fromtimestamp(ts)
        words += [dt.strftime("%B").lower(), dt.strftime("%b").lower(), dt.strftime("%A").lower(), str(dt.year)]
        h = dt.hour
        words.append("morning" if 5 <= h < 12 else "afternoon" if 12 <= h < 17 else "evening" if 17 <= h < 21 else "night")
    if meta.get("device"):
        words.append(str(meta["device"]).lower())
    return " ".join(words)
