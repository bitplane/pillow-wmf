"""Native ArcTo and AngleArc pixels in both graphics modes under scaled page mappings.

``compatible_arcs.json`` holds the pixels the ``compatible-arcs`` probe read
back: a one-pixel pen moves to (5, 90), draws one call, then a line to
(90, 90), on a 96x96 surface whose viewport is 96x96 and whose window is
given.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

CASES = json.loads(Path(__file__).with_name("compatible_arcs.json").read_text())


@pytest.mark.parametrize(
    "case", CASES, ids=[f"{c['call']}-{c['mode']}-{c['window'][0]}-{c['direction']}-{c['arguments'][0]}" for c in CASES]
)
def test_arcs_match_native_pixels(case):
    dc = RasterContext(96, 96, trace_calls=False)
    dc.set_map_mode(8)
    dc.set_window_extent(*case["window"])
    dc.set_viewport_extent(96, 96)
    dc.set_graphics_mode(case["mode"])
    dc.set_arc_direction(case["direction"])
    dc.move_to(5, 90)
    getattr(dc, case["call"])(*case["arguments"])
    dc.line_to(90, 90)
    native = {(x0 + i, y) for y, x0, mask in case["rows"] for i, c in enumerate(mask) if c == "#"}
    image = dc.image
    assert {(x, y) for y in range(96) for x in range(96) if image.getpixel((x, y)) != (255, 255, 255)} == native
