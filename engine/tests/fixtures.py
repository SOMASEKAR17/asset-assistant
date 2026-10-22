from __future__ import annotations

import io
import re
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from caa.nemotron import TokenFactory, clean_audio, clean_caption, clean_plan
from caa.textembed import TextEmbedder
from caa.vectors import normalize

CONCEPTS = {
    "run": {"run", "running", "runner", "jogger", "jogging", "sprint"},
    "rain": {"rain", "rainy", "storm", "downpour", "wet", "drizzle"},
    "fire": {"fire", "flames", "flame", "burning", "blaze", "inferno"},
    "key": {"green", "chroma", "keying", "keyable"},
    "city": {"city", "street", "urban", "traffic", "downtown"},
    "music": {"music", "lofi", "chill", "beats", "mellow", "relaxing", "loop"},
    "beach": {"beach", "sunset", "ocean", "sea", "shore", "coast"},
    "impact": {"impact", "hit", "boom", "thud"},
    "whoosh": {"whoosh", "swoosh", "sweep", "swish"},
}


class FakeTextEmbedder(TextEmbedder):
    available = True
    name = "text:fake-concepts"
    dim = 16
    state = "ready"

    def embed(self, texts):
        out = []
        for t in texts:
            v = np.zeros(self.dim, dtype=np.float32)
            for w in re.findall(r"[a-z\-]+", (t or "").lower()):
                for i, words in enumerate(CONCEPTS.values()):
                    if w in words:
                        v[i] += 1.0
            out.append(v)
        return normalize(np.vstack(out)) if out else np.zeros((0, self.dim), dtype=np.float32)


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def make_library(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "Footage").mkdir(exist_ok=True)
    (root / "SFX").mkdir(exist_ok=True)
    (root / "Music").mkdir(exist_ok=True)
    (root / "Stills").mkdir(exist_ok=True)
    (root / "Templates").mkdir(exist_ok=True)
    files = {
        "two_shots": root / "Footage" / "city_street_two_shots.mp4",
        "green": root / "Footage" / "GreenScreen_Fire_01.mp4",
        "vertical": root / "Footage" / "runner_in_rain_vertical.mp4",
        "whoosh": root / "SFX" / "whoosh_fast_01.wav",
        "impact": root / "SFX" / "deep_impact_hit.wav",
        "music": root / "Music" / "lofi_chill_loop.mp3",
        "photo": root / "Stills" / "sunset_beach.jpg",
        "logo": root / "Stills" / "logo_overlay.png",
        "template": root / "Templates" / "Modern_Lower_Third.mogrt",
        "dated": root / "Phone" / "VID_20260906_115320856.mp4",
    }
    (root / "Phone").mkdir(exist_ok=True)
    _ff("-f", "lavfi", "-i", "testsrc2=s=160x90:d=65:r=5", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-shortest",
        "-metadata", "creation_time=2026-09-06T11:54:25.000000Z", "-metadata", "location=+12.9692+079.1559/",
        "-metadata", "com.android.manufacturer=samsung", "-metadata", "com.android.model=SM-S918B",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "use_metadata_tags", str(files["dated"]))
    _ff("-f", "lavfi", "-i", "color=c=0xC0392B:s=640x360:d=3:r=25", "-f", "lavfi", "-i", "color=c=0x1F4E9C:s=640x360:d=3:r=25",
        "-f", "lavfi", "-i", "sine=f=440:d=6", "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]",
        "-map", "[v]", "-map", "2:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(files["two_shots"]))
    _ff("-f", "lavfi", "-i", "color=c=0x00B140:s=640x360:d=4:r=25", "-vf",
        "drawbox=x=260+40*sin(t*3):y=120:w=120:h=140:color=0xFF6A00@1:t=fill", "-c:v", "libx264", "-pix_fmt", "yuv420p",
        str(files["green"]))
    _ff("-f", "lavfi", "-i", "testsrc2=s=360x640:d=4:r=25", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(files["vertical"]))
    _ff("-f", "lavfi", "-i", "anoisesrc=d=0.7:c=pink:a=0.6", "-af", "afade=t=in:d=0.25,afade=t=out:st=0.35:d=0.35",
        "-ar", "44100", str(files["whoosh"]))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.9*exp(-6*t)*sin(2*PI*55*t):d=1.5:s=44100", str(files["impact"]))
    _ff("-f", "lavfi", "-i", "aevalsrc=0.6*sin(2*PI*220*t)*lt(mod(t\\,0.5)\\,0.12)+0.2*sin(2*PI*330*t):d=20:s=44100",
        "-c:a", "libmp3lame", "-b:a", "128k", str(files["music"]))
    img = Image.new("RGB", (1280, 720))
    d = ImageDraw.Draw(img)
    for y in range(720):
        r = int(250 - y * 0.12)
        g = int(140 - y * 0.15)
        b = int(60 + y * 0.18)
        d.line([(0, y), (1280, y)], fill=(r, max(0, g), min(255, b)))
    d.ellipse([560, 300, 720, 460], fill=(255, 210, 90))
    img.save(files["photo"], quality=90)
    logo = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(logo).ellipse([64, 64, 448, 448], fill=(255, 255, 255, 255))
    logo.save(files["logo"])
    thumb = Image.new("RGB", (480, 270), (30, 30, 34))
    ImageDraw.Draw(thumb).rectangle([40, 190, 360, 230], fill=(255, 176, 59))
    buf = io.BytesIO()
    thumb.save(buf, "PNG")
    with zipfile.ZipFile(files["template"], "w") as z:
        z.writestr("thumb.png", buf.getvalue())
        z.writestr("definition.json", "{}")
    return files


CANNED = {
    "city_street": {"description": "A busy city street with traffic at dusk", "subjects": ["cars", "street"], "setting": "city",
                    "shot_type": "wide", "camera_motion": "static", "mood": ["urban"], "tags": ["city", "street", "traffic", "urban", "downtown"],
                    "background": "normal"},
    "greenscreen": {"description": "Flames burning against a green screen background", "subjects": ["fire", "flames"],
                    "setting": "studio", "shot_type": "medium", "camera_motion": "static", "mood": ["intense"],
                    "tags": ["fire", "flames", "burning", "green screen", "vfx", "overlay"], "background": "green screen"},
    "runner": {"description": "A man running through heavy rain at night", "subjects": ["man", "runner"], "setting": "street",
               "shot_type": "medium", "camera_motion": "tracking", "mood": ["dramatic"], "tags": ["running", "rain", "runner", "night", "storm"],
               "background": "normal"},
    "sunset": {"description": "Golden sunset over a calm beach", "subjects": ["sun", "sea"], "setting": "beach", "shot_type": "wide",
               "mood": ["calm", "warm"], "tags": ["sunset", "beach", "golden hour", "ocean"], "background": "normal"},
    "logo": {"description": "A white circular logo on a transparent background", "subjects": ["logo"], "setting": "graphic",
             "shot_type": "graphic", "mood": ["clean"], "tags": ["logo", "overlay", "circle", "brand"], "background": "transparent"},
    "lower_third": {"description": "A modern orange lower third title bar", "subjects": ["title bar"], "setting": "graphic",
                    "shot_type": "graphic", "mood": ["modern"], "tags": ["lower third", "title", "name tag", "orange"], "background": "solid color"},
}

AUDIO = {
    "whoosh": {"kind": "sfx", "description": "A short fast whoosh sweep", "mood": ["energetic"], "energy": "high",
               "tags": ["whoosh", "swoosh", "transition", "fast", "air"], "good_for": ["transition", "jump cut"]},
    "impact": {"kind": "sfx", "description": "A deep low impact hit", "mood": ["dramatic"], "energy": "high",
               "tags": ["impact", "hit", "boom", "bass", "cinematic"], "good_for": ["reveal", "title"]},
    "lofi": {"kind": "music", "description": "A mellow lo-fi chill loop", "mood": ["calm", "chill"], "energy": "low",
             "instruments": ["keys"], "tags": ["lofi", "chill", "loop", "background music", "relaxed"], "good_for": ["b-roll bed", "vlog"]},
}


class FakeTokenFactory(TokenFactory):
    def __init__(self, settings, db=None):
        super().__init__(settings, db)
        self.calls = {"vision": 0, "omni": 0, "fast": 0}

    @property
    def available(self) -> bool:
        return True

    def caption_frames(self, images, name, start=0.0, end=0.0, what=None):
        self.calls["vision"] += 1
        key = name.lower().replace("_", "").replace(" ", "")
        for k, v in CANNED.items():
            if k.replace("_", "") in key:
                return clean_caption(v)
        return None

    def describe_audio(self, wav, name, excerpt_s, full_s, feat, folder="", local_tags=None):
        self.calls["omni"] += 1
        for k, v in AUDIO.items():
            if k in name.lower():
                return clean_audio(v)
        return None

    def rewrite_query(self, q):
        self.calls["fast"] += 1
        ql = q.lower()
        if "whoosh" in ql:
            return clean_plan({"visual": "", "keywords": ["whoosh", "swoosh", "transition"], "kind": "audio", "audio_kind": "sfx", "max_duration": 3})
        if "city" in ql or "trees" in ql:
            return clean_plan({"visual": q, "keywords": [ql], "kind": "image", "orientation": "portrait", "max_duration": 1})
        if "green screen" in ql:
            return clean_plan({"visual": "fire on green screen", "keywords": ["fire", "flames", "green screen"], "kind": "video", "green_screen": True})
        return clean_plan({"visual": q, "keywords": q.lower().split(), "kind": "any"})
