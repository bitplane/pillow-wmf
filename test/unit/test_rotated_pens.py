"""Pens widened under rotating, shearing and scaling world transforms.

``rotated_pens.json`` holds native WidenPath outlines, read back with
GetPath in 28.4 device units, of a line from (-12, -3) to (14, 5) or a vee
through (-12, -8), (0, 10) and (12, -8). Keys name the transform, the pen
(``create`` for CreatePen, ``geo-round`` and ``geo-flat`` for solid
geometric pens with round caps and joins, or flat caps and bevel joins),
the logical width and the figure.

The cases cover small table pens under a uniform rotation, cubic ellipses
on the transformed radius vectors for wide pens and non-uniform transforms,
the CreatePen hairline rule under a shear, and support ties on the opposite
side of a figure.

``strokes`` holds the pixels native GDI drew for figures stroked with a
black pen and the null brush on a white 64x64 DIB (rows of ``[y, x0,
mask]``); ``closed`` holds the two native outlines of a widened closed
triangle.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("rotated_pens.json").read_text())
FIGURES = {"line": ((-12, -3), (14, 5)), "vee": ((-12, -8), (0, 10), (12, -8))}
STYLES = {"geo-round": 0x00010000, "geo-flat": 0x00010000 | 0x0200 | 0x1000}
TRANSFORMS = {
    "identity": (1.0, 0.0, 0.0, 1.0, 16.0, 16.0),
    "r25": (0.9063077870366499, 0.42261826174069944, -0.42261826174069944, 0.9063077870366499, 30.0, 5.0),
    "shear": (1.0, 0.0, 0.4, 1.0, 10.0, 10.0),
    "general": (0.9, 0.35, -0.2, 1.1, 20.0, 8.0),
}
TRIANGLE = ((4, 4), (28, 8), (12, 24))
SHAPES = {
    "vee": lambda c: c.polyline(((4, 4), (16, 24), (28, 6))),
    "triangle": lambda c: c.polygon(TRIANGLE),
    "rectangle": lambda c: c.rectangle(4, 4, 28, 20),
    "ellipse": lambda c: c.ellipse(4, 4, 28, 20),
}


def select_pen(context, pen, width):
    if pen == "create":
        context.select_object(context.create_pen(0, width, 0))
    else:
        context.select_object(context.ext_create_pen(STYLES[pen], width, 0))


@pytest.mark.parametrize("key", sorted(NATIVE["outlines"]))
def test_widened_outlines_match_native_paths(key):
    transform, pen, width, figure = key.split()
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*NATIVE["transforms"][transform])
    select_pen(context, pen, int(width))
    context.begin_path()
    context.polyline(FIGURES[figure])
    context.end_path()
    context.widen_path()
    ((commands, closed),) = context._state.path
    assert closed and [list(command[0]) for command in commands] == NATIVE["outlines"][key]


@pytest.mark.parametrize("key", sorted(NATIVE["strokes"]))
def test_strokes_match_native_pixels(key):
    transform, pen, width, shape = key.split()
    context = RasterContext(64, 64, background=(255, 255, 255), trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    select_pen(context, pen, int(width))
    context.select_object(context.get_stock_object(5))  # NULL_BRUSH
    SHAPES[shape](context)
    image = context.image.convert("RGB")
    ours = {(x, y) for y in range(64) for x in range(64) if image.getpixel((x, y)) != (255, 255, 255)}
    native = {(x0 + i, y) for y, x0, mask in NATIVE["strokes"][key] for i, mark in enumerate(mask) if mark == "#"}
    assert ours == native


@pytest.mark.parametrize("key", sorted(NATIVE["closed"]))
def test_widened_closed_figures_match_native_paths(key):
    transform, pen, width = key.split()
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    select_pen(context, pen, int(width))
    context.begin_path()
    context.polygon(TRIANGLE)
    context.end_path()
    context.widen_path()
    figures = [[list(command[0]) for command in commands] for commands, _ in context._state.path]
    assert figures == NATIVE["closed"][key]


CAPS = {"round": 0x0000, "square": 0x0100, "flat": 0x0200}
JOINS = {"round": 0x0000, "bevel": 0x1000, "miter": 0x2000}


@pytest.mark.parametrize("key", sorted(NATIVE["styles"]))
def test_geometric_caps_and_joins_match_native_paths(key):
    """``styles``: native WidenPath outlines of solid geometric pens by cap and join."""
    transform, cap, join, _, width, shape = key.split()
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    context.select_object(context.ext_create_pen(0x00010000 | CAPS[cap] | JOINS[join], int(width), 0))
    context.begin_path()
    SHAPES[shape](context)
    context.end_path()
    context.widen_path()
    figures = [[list(command[0]) for command in commands] for commands, _ in context._state.path]
    assert figures == NATIVE["styles"][key]
