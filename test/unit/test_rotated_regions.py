"""Clipping and region painting under rotating transforms.

``rotated_regions.json`` holds the pixels native GDI changed for each case
(rows of ``[y, x0, mask]``), read back from a 64x64 DIB.
"""

import json
import math
from pathlib import Path

import pytest

from pillow_wmf.objects import RegionGeometry
from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("rotated_regions.json").read_text())
ANGLE = math.radians(25)
TRANSFORMS = {
    "r25": (math.cos(ANGLE), math.sin(ANGLE), -math.sin(ANGLE), math.cos(ANGLE), 30.0, 5.0),
    "general": (0.9, 0.35, -0.2, 1.1, 20.0, 8.0),
}
RECTANGLE = RegionGeometry(((5, 5, 35, 25),))
COMPOUND = RegionGeometry(((5, 5, 25, 15), (5, 15, 40, 20), (15, 20, 40, 35)))
CASES = {
    "clip-intersect": lambda c: c.intersect_clip_rect(5, 5, 35, 25),
    "clip-exclude": lambda c: c.exclude_clip_rect(5, 5, 35, 25),
    "clip-intersect-twice": lambda c: (c.intersect_clip_rect(5, 5, 35, 25), c.intersect_clip_rect(15, 0, 50, 20)),
    "clip-intersect-offset": lambda c: (c.intersect_clip_rect(5, 5, 35, 25), c.offset_clip_region(6, 3)),
    "clip-select-region": lambda c: c.select_clip_region(c.create_region(RECTANGLE)),
    "clip-thin": lambda c: c.intersect_clip_rect(10, 10, 11, 40),
    "fill-rect": lambda c: c.fill_region(c.create_region(RECTANGLE), c.get_stock_object(4)),
    "fill-compound": lambda c: c.fill_region(c.create_region(COMPOUND), c.get_stock_object(4)),
    "paint-rect": lambda c: (c.select_object(c.get_stock_object(2)), c.paint_region(c.create_region(RECTANGLE))),
    "invert-compound": lambda c: c.invert_region(c.create_region(COMPOUND)),
}


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_rotated_clips_and_regions_match_native_pixels(key):
    transform, case = key.split()
    context = RasterContext(64, 64, background=(255, 255, 255), trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    CASES[case](context)
    if case.startswith("clip"):
        # Fill the whole surface through the clip, without the transform.
        context.set_world_transform(1, 0, 0, 1, 0, 0)
        context.select_object(context.get_stock_object(4))
        context.pat_blt(0, 0, 64, 64, 0x00F00021)
    image = context.image.convert("RGB")
    ours = {(x, y) for y in range(64) for x in range(64) if image.getpixel((x, y)) != (255, 255, 255)}
    native = {(x0 + i, y) for y, x0, mask in NATIVE[key] for i, mark in enumerate(mask) if mark != "."}
    assert ours == native
