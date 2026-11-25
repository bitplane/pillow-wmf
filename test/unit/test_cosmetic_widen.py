"""WidenPath with styled CreatePen pens and cosmetic ExtCreatePen pens.

``cosmetic_widen.json`` holds native WidenPath outlines, read back with
GetPath in 28.4 device units, keyed by world transform, pen kind
(``create`` for CreatePen, ``cosmetic`` for a PS_COSMETIC ExtCreatePen
pen), line style, width and figure. CreatePen styles are ignored: a styled
pen widens exactly as the solid pen of its width. A cosmetic ExtCreatePen
pen fails to widen (null entries) and leaves the path unchanged.
"""

import json
from pathlib import Path

import pytest

from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("cosmetic_widen.json").read_text())
STYLES = {"solid": 0, "dash": 1, "dot": 2, "dashdot": 3, "dashdotdot": 4, "user": 7, "alternate": 8}
TRANSFORMS = {
    "identity": (1, 0, 0, 1, 0, 0),
    "scale2": (2, 0, 0, 2, 0, 0),
    "r25": (0.9063, 0.4226, -0.4226, 0.9063, 8, 0),
}
FIGURES = {"line": ((2, 3), (44, 12)), "vee": ((2, 2), (14, 20), (26, 2)), "closed": ((2, 2), (30, 4), (12, 22))}


def path(transform, kind, style, width, figure, *, widen):
    context = RasterContext(16, 16, trace_calls=False)
    context.set_graphics_mode(2)
    context.set_world_transform(*TRANSFORMS[transform])
    if kind == "create":
        context.select_object(context.create_pen(STYLES[style], width, 0xFF))
    else:
        entries = (3, 2, 1, 2) if style == "user" else ()
        context.select_object(context.ext_create_pen(STYLES[style], width, 0xFF, entries=entries))
    first, *rest = FIGURES[figure]
    context.begin_path()
    context.move_to(*first)
    context.polyline_to(rest)
    if figure == "closed":
        context.close_figure()
    context.end_path()
    if widen:
        context.widen_path()
    return context._state.path


@pytest.mark.parametrize("key", sorted(NATIVE))
def test_widen_path_matches_native(key):
    transform, kind, style, width, figure = key.split()
    widened = path(transform, kind, style, int(width), figure, widen=True)
    if NATIVE[key] is None:
        assert widened == path(transform, kind, style, int(width), figure, widen=False)
    else:
        # GetPath lists every closed figure's points in turn.
        assert all(closed for _, closed in widened)
        assert [list(command[0]) for commands, _ in widened for command in commands] == NATIVE[key]
