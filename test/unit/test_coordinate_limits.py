"""Native drawing with device coordinates near and past the 28.4 range.

``coordinate_limits.json`` holds what the ``coordinate-limits`` probe drew on
a 32x32 surface with the black stock brush and pen, for the cases modelled
exactly (see docs/emf.md for those that are not).
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

CASES = json.loads(Path(__file__).with_name("coordinate_limits.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["name"] + "-" + str(case["mode"]) for case in CASES])
def test_drawing_matches_native_past_the_fixed_point_range(case):
    dc = RasterContext(32, 32, trace_calls=False)
    dc.set_map_mode(8)
    dc.set_window_extent(32, 32)
    dc.set_viewport_extent(32, 32)
    dc.select_object(dc.get_stock_object(4))
    mode = case["mode"]
    if mode == "ADVANCED":
        dc.set_graphics_mode(2)
    elif isinstance(mode, list):
        dc.set_window_extent(1, 1)
        dc.set_viewport_extent(mode[1], mode[1])
    function, arguments = case["function"], case["arguments"]
    if function in ("Rectangle", "Ellipse"):
        getattr(dc, function.lower())(*arguments)
    elif function == "PatBlt":
        dc.pat_blt(*arguments, 0x00F00021)
    elif function == "LineTo":
        dc.move_to(*arguments[0])
        dc.line_to(*arguments[1])
    else:
        getattr(dc, function.lower())(tuple(map(tuple, arguments)))
    native = {(x0 + i, y) for y, x0, mask in case["rows"] for i, c in enumerate(mask) if c == "#"}
    image = dc.image
    assert {(x, y) for y in range(32) for x in range(32) if image.getpixel((x, y)) != (255, 255, 255)} == native
