"""Transfers, gradients and arcs under rotating transforms.

``rotated_transfers.json`` holds the pixels native GDI changed for each case
on a 64x64 DIB cleared to light grey, as rows of ``[y, x0, "RRGGBB ..."]``
with ``-`` for unchanged pixels.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf.objects import BitmapData
from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("rotated_transfers.json").read_text())
TRANSFORMS = {"shear": (1.0, 0.0, 0.4, 1.0, 10.0, 10.0), "general": (0.9, 0.35, -0.2, 1.1, 20.0, 8.0)}
GREY = (192, 192, 192)


def header(width, height, depth):
    return struct.pack("<IiiHHIIiiII", 40, width, height, 1, depth, 0, 0, 0, 0, 0, 0)


# Each source pixel's colour names its position.
SOURCE = BitmapData(
    "dib",
    header(8, -6, 32)
    + b"".join(bytes(((x * 30) % 256, (y * 40) % 256, (x * 13 + y * 29) % 256, 0)) for y in range(6) for x in range(8)),
)
MASK = BitmapData("dib", header(8, -6, 1) + b"".join(bytes((v, 0, 0, 0)) for v in (0xF0, 0x0F) * 3))
PACKED = BitmapData("dib", header(4, 3, 24) + bytes((i * 23 + 5) % 256 for i in range(36)))
VERTICES = ((4, 4, 0xF000, 0x1000, 0, 0), (36, 24, 0x1000, 0xE000, 0xF000, 0), (8, 30, 0, 0, 0xF000, 0))


def pat_blt(rop, brush):
    def draw(context):
        context.select_object(brush(context))
        context.pat_blt(5, 5, 30, 20, rop)

    return draw


CASES = {
    "patblt-copy": pat_blt(0x00F00021, lambda c: c.create_brush(0, 0x204080, 0)),
    "patblt-hatch": pat_blt(0x00F00021, lambda c: c.create_brush(2, 0x0000FF, 5)),
    "patblt-invert": pat_blt(0x00550009, lambda c: c.get_stock_object(0)),
    "patblt-patinvert": pat_blt(0x005A0049, lambda c: c.create_brush(0, 0x00FF00, 0)),
    "bitblt-copy": lambda c: c.dib_bit_blt(5, 5, 8, 6, 0, 0, 0x00CC0020, SOURCE),
    "bitblt-srcinvert": lambda c: c.dib_bit_blt(5, 5, 8, 6, 0, 0, 0x00660046, SOURCE),
    "bitblt-srcand": lambda c: c.dib_bit_blt(5, 5, 8, 6, 0, 0, 0x008800C6, SOURCE),
    "stretchblt-copy": lambda c: c.dib_stretch_blt(5, 5, 24, 15, 0, 0, 8, 6, 0x00CC0020, SOURCE),
    "stretchblt-srcpaint": lambda c: c.dib_stretch_blt(5, 5, 24, 15, 0, 0, 8, 6, 0x00EE0086, SOURCE),
    "maskblt": lambda c: c.mask_blt(5, 5, 8, 6, 0, 0, 0xAACC0020, SOURCE, MASK, 0, 0, 2),
    "stretchdib-copy": lambda c: c.stretch_dib(5, 5, 20, 15, 0, 0, 4, 3, 0x00CC0020, 0, PACKED),
    "stretchdib-srcinvert": lambda c: c.stretch_dib(5, 5, 20, 15, 0, 0, 4, 3, 0x00660046, 0, PACKED),
    "setdibits": lambda c: c.set_dib_to_device(5, 5, 4, 3, 0, 0, 0, 3, 0, PACKED),
    "gradient-h": lambda c: c.gradient_fill(0, VERTICES[:2], ((0, 1),)),
    "gradient-triangle": lambda c: c.gradient_fill(2, VERTICES, ((0, 1, 2),)),
    "anglearc": lambda c: (c.move_to(2, 2), c.angle_arc(20, 20, 12, 30.0, 200.0)),
    "arcto": lambda c: (c.set_arc_direction(1), c.move_to(2, 2), c.arc_to(5, 5, 35, 25, 35, 15, 5, 5)),
    "arcto-clockwise": lambda c: (c.set_arc_direction(2), c.move_to(2, 2), c.arc_to(5, 5, 35, 25, 35, 15, 5, 5)),
}


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_rotated_transfers_match_native_pixels(key):
    transform, case = key.split()
    context = RasterContext(64, 64, background=GREY, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    CASES[case](context)
    image = context.image.convert("RGB")
    ours = {(x, y): image.getpixel((x, y)) for y in range(64) for x in range(64) if image.getpixel((x, y)) != GREY}
    native = {
        (x0 + i, y): tuple(int(text[j : j + 2], 16) for j in (0, 2, 4))
        for y, x0, row in NATIVE[key]
        for i, text in enumerate(row.split())
        if text != "-"
    }
    assert ours == native
