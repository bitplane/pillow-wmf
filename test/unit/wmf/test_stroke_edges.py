"""Clipping must not change the phase of a connected styled path."""

import pytest

from pillow_wmf import RasterContext


@pytest.mark.parametrize("style", (1, 2, 3, 4))
@pytest.mark.parametrize("background", (1, 2))
@pytest.mark.parametrize("transpose", (False, True))
@pytest.mark.parametrize("reverse", (False, True))
def test_connected_dash_clipping_matches_larger_surface_crop(style, background, transpose, reverse):
    points = ((0, -20), (10, -10), (30, 10), (40, 20), (20, 40), (10, 20))
    if transpose:
        points = tuple((y, x) for x, y in points)
    if reverse:
        points = points[::-1]
    small, large = RasterContext(32, 32), RasterContext(96, 96)
    for context in (small, large):
        context.select_object(context.create_pen(style, 1, 0))
        context.set_background_mode(background)
        context.set_background_color(0x0000FF)
    small.polyline(points)
    large.polyline(tuple((x + 32, y + 32) for x, y in points))
    assert small.image.tobytes() == large.image.crop((32, 32, 64, 64)).tobytes()
