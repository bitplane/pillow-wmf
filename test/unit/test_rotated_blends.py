"""AlphaBlend, TransparentBlt and destination-source transfers under rotating transforms.

``rotated_blends.json`` holds the pixels native GDI changed for each case on
a 64x64 DIB starting from ``background(x, y)``, as rows of
``[y, x0, "RRGGBB ..."]`` with ``-`` for unchanged pixels. The ``identity``
cases are unrotated references for per-pixel alpha at partial constant alpha.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf.objects import BitmapData
from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("rotated_blends.json").read_text())
TRANSFORMS = {
    "identity": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    "shear": (1.0, 0.0, 0.4, 1.0, 10.0, 10.0),
    "general": (0.9, 0.35, -0.2, 1.1, 20.0, 8.0),
}


def header(width, height):
    return struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, 0, 0, 0, 0, 0)


def background(x, y):
    return (x * 4, y * 4, 0x80)


BACKGROUND = BitmapData(
    "dib", header(64, -64) + b"".join(bytes((0x80, y * 4, x * 4, 0)) for y in range(64) for x in range(64))
)


def source(alpha):
    """Each pixel's colour names its position; ``alpha`` premultiplies a coded alpha."""
    pixels = b""
    for y in range(6):
        for x in range(8):
            color = ((x * 30) % 256, (y * 40) % 256, (x * 13 + y * 29) % 256)
            if alpha:
                a = (x * 37 + y * 41) % 256
                pixels += bytes((*(c * a // 255 for c in color), a))
            else:
                pixels += bytes((*color, 0))
    return BitmapData("dib", header(8, -6) + pixels)


OPAQUE, ALPHA = source(False), source(True)


def blend(width, height, constant, per_pixel):
    bitmap = ALPHA if per_pixel else OPAQUE
    return lambda c: c.alpha_blend(5, 5, width, height, 0, 0, 8, 6, constant << 16 | per_pixel << 24, bitmap)


CASES = {
    "alpha-const": blend(8, 6, 128, 0),
    "alpha-const-stretch": blend(24, 15, 200, 0),
    "alpha-pixel": blend(8, 6, 255, 1),
    "alpha-pixel-stretch": blend(24, 15, 255, 1),
    "alpha-pixel-half": blend(8, 6, 128, 1),
    "alpha-pixel-half-stretch": blend(24, 15, 77, 1),
    "transparent": lambda c: c.transparent_blt(5, 5, 8, 6, 0, 0, 8, 6, 0x3C2837, OPAQUE),
    "transparent-stretch": lambda c: c.transparent_blt(5, 5, 24, 15, 0, 0, 8, 6, 0x3C2837, OPAQUE),
    # Native GDI rejects a source DC with a rotating transform: nothing is drawn.
    "bitblt-self": lambda c: c.bit_blt(5, 5, 12, 8, 20, 25, 0x00CC0020),
    "stretchblt-self": lambda c: c.stretch_blt(5, 5, 24, 15, 20, 25, 8, 6, 0x00CC0020),
    "bitblt-patcopy": lambda c: (
        c.select_object(c.create_brush(0, 0x204080, 0)),
        c.bit_blt(5, 5, 30, 20, 0, 0, 0x00F00021),
    ),
    "bitblt-dstinvert": lambda c: c.bit_blt(5, 5, 30, 20, 0, 0, 0x00550009),
}


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_rotated_blends_match_native_pixels(key):
    transform, case = key.split()
    context = RasterContext(64, 64, trace_calls=False)
    context.set_dib_to_device(0, 0, 64, 64, 0, 0, 0, 64, 0, BACKGROUND)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    CASES[case](context)
    image = context.image.convert("RGB")
    ours = {
        (x, y): image.getpixel((x, y))
        for y in range(64)
        for x in range(64)
        if image.getpixel((x, y)) != background(x, y)
    }
    native = {
        (x0 + i, y): tuple(int(text[j : j + 2], 16) for j in (0, 2, 4))
        for y, x0, row in NATIVE[key]
        for i, text in enumerate(row.split())
        if text != "-"
    }
    assert ours == native
