"""Curved shapes whose logical box has no width or height, as native GDI draws them.

``degenerate_shapes.json`` holds the pixels ``probe-windows-degenerate-shapes.py``
observed: a one-pixel black pen and the gray stock brush, a move to (5, 60),
the shape, then a line to (60, 60). In GM_ADVANCED an arc, chord, pie or
ArcTo of such a box sweeps its whole degenerate ellipse from its zero-angle
point, and a RoundRect draws as its box; GM_COMPATIBLE draws nothing.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf import InvalidOperation, RasterContext
from pillow_wmf.emf import Metafile
from pillow_wmf.emf.recorder import Recorder

CASES = json.loads(Path(__file__).with_name("degenerate_shapes.json").read_text())
BOXES = {"w0": (20, 10, 20, 40), "h0": (10, 20, 40, 20), "both0": (20, 20, 20, 20), "w1": (20, 10, 21, 40)}
MODES = {
    "compatible": None,
    "identity": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    "rotated": (0.866, 0.5, -0.5, 0.866, 20.0, 0.0),
    "scaled": (1.5, 0.0, 0.0, 0.5, 0.0, 10.0),
}


@pytest.mark.parametrize("case", CASES)
def test_degenerate_boxes_draw_as_natively(case):
    mode, box_name, call = case.split("/")
    dc = RasterContext(64, 64)
    dc.select_object(dc.get_stock_object(2))  # GRAY_BRUSH
    if MODES[mode] is not None:
        dc.set_graphics_mode(2)
        dc.set_world_transform(*MODES[mode])
    dc.move_to(5, 60)
    box = BOXES[box_name]
    if call == "round_rect":
        dc.round_rect(*box, 8, 8)
    elif call == "ellipse":
        dc.ellipse(*box)
    elif call == "angle_arc":
        dc.angle_arc(box[0], box[1], 0, 30.0, 120.0)
    else:
        getattr(dc, call)(*box, 50, 5, 5, 50)
    dc.line_to(60, 60)
    image = dc.image
    drawn = {(x, y) for y in range(64) for x in range(64) if image.getpixel((x, y)) != (255, 255, 255)}
    expected = {(x0 + i, y) for y, x0, row in CASES[case] for i, value in enumerate(row) if value == "#"}
    assert drawn == expected


@pytest.mark.parametrize("widen", [False, True])
def test_clip_path_after_a_failed_poly_draw_is_recorded(widen):
    # PolyDraw with an invalid point type fails without touching the path,
    # but is still recorded; the clip path is built from the rest.
    recorder = Recorder()
    if widen:
        recorder.select_object(recorder.ext_create_pen(0x10000, 6, 0))
    recorder.begin_path()
    recorder.move_to(5, 5)
    recorder.poly_draw(((30, 5), (40, 20), (10, 30)), bytes((2, 4, 3)))
    recorder.line_to(50, 10)
    recorder.ellipse(10, 20, 40, 50)
    recorder.end_path()
    if widen:
        recorder.widen_path()
    recorder.select_clip_path(1 if widen else 5)
    recorder.rectangle(0, 0, 60, 60)
    names = [type(record).__name__ for record in Metafile.from_bytes(recorder.to_bytes()).records]
    path = ["BeginPath", "MoveToEx", "PolyDraw16", "LineTo", "Ellipse", "EndPath"]
    tail = ["WidenPath"] if widen else []
    expected = (
        (["ExtCreatePen", "SelectObject"] if widen else []) + path + tail + ["SelectClipPath", "Rectangle", "Eof"]
    )
    assert names == expected


def test_failed_poly_draw_keeps_the_raster_path():
    dc = RasterContext(64, 64)
    dc.begin_path()
    dc.move_to(5, 5)
    with pytest.raises(InvalidOperation):
        dc.poly_draw(((30, 5), (40, 20), (10, 30)), bytes((2, 4, 3)))
    dc.line_to(50, 10)
    dc.end_path()
    dc.stroke_path()
    assert dc.image.getpixel((5, 5)) == (0, 0, 0)
