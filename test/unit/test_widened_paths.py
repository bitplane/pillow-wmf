"""Native WidenPath outlines of geometric pens, read back with GetPath in 28.4.

``widened_paths.json`` holds, per case, the world transform, the
ExtCreatePen style bits, width and user-style entries, the figure's
logical points (a polygon when ``closed``), and the native path's figures.
``rotpen`` cases are flat-capped, bevel-joined pens of several widths under
rotating, scaling and shearing transforms; ``style`` cases cover caps,
joins and line styles. Together they cover the pen perpendicular's
rounding at every segment direction tested natively.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("widened_paths.json").read_text())


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_widened_paths_match_native(key):
    case = NATIVE[key]
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*case["transform"])
    context.select_object(context.ext_create_pen(case["style"], case["width"], 0, entries=tuple(case["entries"])))
    context.begin_path()
    points = [tuple(point) for point in case["points"]]
    (context.polygon if case["closed"] else context.polyline)(points)
    context.end_path()
    context.widen_path()
    figures = [[list(map(int, command[0])) for command in commands] for commands, _ in context._state.path]
    assert figures == case["path"]
