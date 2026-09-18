"""Pinned, openly licensed real-font inputs for a small native text probe."""

import hashlib
from pathlib import Path
from urllib.request import urlopen

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

BASE = "https://raw.githubusercontent.com/notofonts/noto-fonts/ffebf8c1ee449e544955a7e813c54f9b73848eac/"
FONTS = (
    ("NotoSans", "Noto Sans", "b85c38ecea8a7cfb39c24e395a4007474fa5a4fc864f6ee33309eb4948d232d5"),
    ("NotoSerif", "Noto Serif", "c8f669ceb2c9c60ccf55198b305e08a997ffca79a38cc7eeb551e643cbe66505"),
)
SIZE = (640, 180)
SAMPLES = (b"Hamburgefontsiv AVTo fi fl", b"Il1 O0 rn m 0123456789", b".,:;!? ()[] /\\ +-=")


def fetch_fonts(directory):
    """Cache verified source bytes; never silently accept a different revision."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    sources = [(f"hinted/ttf/{name}/{name}-Regular.ttf", digest) for name, _, digest in FONTS]
    sources.append(("LICENSE", "0dab92d0544f7b233403f14b84a663bdbfa746982eda629e7f4f9ffe1b036feb"))
    paths = []
    for source, digest in sources:
        path = directory / Path(source).name
        if path.exists():
            data = path.read_bytes()
        else:
            with urlopen(BASE + source, timeout=60) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Font input checksum mismatch: {path.name}")
        if not path.exists():
            path.write_bytes(data)
        paths.append(path)
    return paths[:-1]


def cases():
    for name, family, _ in FONTS:
        for size in (8, 11, 12, 16, 20, 32):
            recorder = Recorder()
            recorder.set_window_extent(*SIZE)
            recorder.set_viewport_extent(*SIZE)
            handle = recorder.create_font(
                Font(height=-size, weight=400, quality=3, face_name=family.encode().ljust(32, b"\0"))
            )
            recorder.select_object(handle)
            recorder.set_background_mode(1)
            recorder.set_text_alignment(24)
            for y, sample in zip((40, 85, 130), SAMPLES, strict=True):
                recorder.text_out(12, y, sample)
            yield f"{name}-{size}", family, recorder
