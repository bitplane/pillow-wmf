"""The current position across transform changes, and paths after a failed PolyDraw.

``current_position.json`` holds what ``probe-windows-current-position.py``
observed natively: pixels of LineTo, ArcTo, AngleArc and PolylineTo drawn
after a world transform change, of call sequences around such changes, of
clip regions and drawing after a failed PolyDraw, and the paths GetPath
returned after one.

ArcTo starts from the DC's cached device position: the device origin on a
fresh DC, the device end point after LineTo and the other *To calls, and
recomputed from the logical position after MoveTo or any other drawing. A
world transform change leaves it as it was.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf import InvalidOperation, RasterContext

DATA = json.loads(Path(__file__).with_name("current_position.json").read_text())
ROTATE = (0.866, 0.5, -0.5, 0.866, 20.0, 0.0)
SHIFT = (1.0, 0.0, 0.0, 1.0, 7.0, 3.0)
SCALE = (2.0, 0.0, 0.0, 1.5, 0.0, 0.0)
TRANSFORMS = {"rotate": ROTATE, "shift": SHIFT, "scale": SCALE}
ARC_TO = ("arc_to", (20, 20, 40, 34, 40, 27, 20, 20))
SEQUENCES = {
    "move-rectangle-transform-arcto": [("move_to", (10, 12)), ("rectangle", (30, 30, 40, 40)), ROTATE, ARC_TO],
    "rectangle-transform-arcto": [("rectangle", (30, 30, 40, 40)), ROTATE, ARC_TO],
    "transform-rectangle-arcto": [ROTATE, ("rectangle", (30, 30, 40, 40)), ARC_TO],
    "transform-transform-arcto": [SHIFT, ROTATE, ARC_TO],
    "move-line-transform-arcto": [("move_to", (10, 12)), ("line_to", (15, 15)), ROTATE, ARC_TO],
    "line-transform-arcto": [("line_to", (30, 30)), ROTATE, ARC_TO],
    "anglearc-transform-arcto": [("angle_arc", (30, 30, 8, 30.0, 120.0)), ROTATE, ARC_TO],
    "arcto-transform-arcto": [ARC_TO, ROTATE, ARC_TO],
    "arc-transform-arcto": [("arc", (20, 20, 40, 34, 40, 27, 20, 20)), ROTATE, ARC_TO],
    "move-transform-lineto": [("move_to", (10, 12)), ("rectangle", (30, 30, 40, 40)), ROTATE, ("line_to", (40, 30))],
}
INVALID_TYPES = {"lone-bezier": (2, 4, 3), "undefined": (2, 2, 9), "short-bezier": (2, 4, 4)}
POLY_DRAW = ((30, 5), (40, 20), (10, 30))


def drawn(dc):
    image = dc.image
    return {
        (x, y) for y in range(image.height) for x in range(image.width) if image.getpixel((x, y)) != (255, 255, 255)
    }


def expected(rows):
    return {(x0 + i, y) for y, x0, row in rows for i, value in enumerate(row) if value == "#"}


def run(dc, steps):
    dc.set_graphics_mode(2)
    for step in steps:
        if len(step) == 6:
            dc.set_world_transform(*step)
        else:
            getattr(dc, step[0])(*step[1])


@pytest.mark.parametrize("case", DATA["cases"])
def test_drawing_after_a_transform_change(case):
    start, transform, draw = case.split("-")
    steps = [("move_to", (10, 12))] if start == "moved" else []
    steps.append(TRANSFORMS[transform])
    steps.append(
        {
            "line_to": ("line_to", (40, 30)),
            "arc_to": ARC_TO,
            "angle_arc": ("angle_arc", (30, 30, 8, 30.0, 120.0)),
            "polyline_to": ("polyline_to", (((40, 30), (30, 40)),)),
        }[draw]
    )
    dc = RasterContext(64, 64)
    run(dc, steps)
    assert drawn(dc) == expected(DATA["cases"][case])


@pytest.mark.parametrize("sequence", DATA["sequences"])
def test_arc_to_starts_from_the_cached_device_position(sequence):
    dc = RasterContext(64, 64)
    run(dc, SEQUENCES[sequence])
    assert drawn(dc) == expected(DATA["sequences"][sequence])


def build_path(dc, types, tail):
    dc.begin_path()
    dc.move_to(5, 5)
    dc.poly_draw(POLY_DRAW, bytes(types))
    if tail != "alone":
        dc.line_to(50, 10)
    if tail == "line-ellipse":
        dc.ellipse(10, 20, 40, 50)
    dc.end_path()


@pytest.mark.parametrize("case", DATA["paths"])
def test_a_failed_poly_draw_keeps_its_valid_prefix_in_the_path(case):
    name, tail = next((n, case[len(n) + 1 :]) for n in INVALID_TYPES if case.startswith(n + "-"))
    dc = RasterContext(64, 64)
    build_path(dc, INVALID_TYPES[name], tail)
    figures = []
    for path in dc._path_figures(close=False):
        points = [point for command in path.commands for point in command]
        figure = [points[0]] + [p for i, p in enumerate(points[1:], 1) if p != points[i - 1]]
        figures.append([(x // 16, y // 16) for x, y in figure])
    native, figure = [], None
    for x, y, kind in DATA["paths"][case]["points"]:
        if kind & ~1 == 6:
            figure = []
            native.append(figure)
        figure.append((x, y))
    # The ellipse's cubics are compared by their end points only.
    assert figures[: 2 if tail != "alone" else 1] == native[: 2 if tail != "alone" else 1]


@pytest.mark.parametrize("case", DATA["regions"])
def test_clip_regions_and_drawing_after_a_failed_poly_draw(case):
    name, clip = case.split("/")
    dc = RasterContext(64, 64)
    if clip == "true":
        build_path(dc, INVALID_TYPES[name], "line-ellipse")
        dc.select_clip_path(5)
        dc.pat_blt(0, 0, 64, 64, 0x00000042)
    else:
        dc.move_to(5, 5)
        with pytest.raises(InvalidOperation):
            dc.poly_draw(POLY_DRAW, bytes(INVALID_TYPES[name]))
        dc.line_to(50, 60)
    assert drawn(dc) == expected(DATA["regions"][case])
