"""AngleArc paths for sweeps of a full turn or more.

``angle_arc_turns.json`` holds native paths, read back with GetPath in 28.4
device units under GM_ADVANCED, of MoveToEx(5, 5) then AngleArc centred on
(40, 40). Keys give the radius, start angle and sweep; each point is
``[type, x16, y16]``.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("angle_arc_turns.json").read_text())


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_angle_arc_paths_match_native(key):
    radius, start, sweep = key.split()
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.begin_path()
    context.move_to(5, 5)
    context.angle_arc(40, 40, int(radius), float(start), float(sweep))
    context.end_path()
    points = []
    for commands, _ in context._state.path:
        for command in commands:
            points.extend(tuple(map(int, point)) for point in (command if not points else command[1:]))
    assert points == [(x, y) for _, x, y in NATIVE[key]]
