"""Native-confirmed clipping behaviour for connected styled paths.

All 32 crop pairs were rendered independently by Windows GDI.
See scripts/probe-windows-edge-cases.py for the oracle check.
"""

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.geometry import StrokeSegment, contains
from pillow_wmf.stroke import join_outline, realize_pen, widen_segment


def test_cosmetic_xor_retracing_preserves_repeated_pixel_visits():
    context = RasterContext(128, 128)
    context.select_object(context.create_pen(0, 1, 0x00FFFFFF))
    context.set_rop2(7)
    context.polyline(((8, 16), (80, 16), (8, 16)))
    assert context.image.getpixel((32, 16)) == (255, 255, 255)
    assert context.image.getpixel((8, 16)) == (0, 0, 0)


def test_opaque_style_foreground_has_priority_over_retraced_gap():
    context = RasterContext(128, 128)
    context.select_object(context.create_pen(4, 1, 0))
    context.set_background_color(0x000000FF)
    context.polyline(((8, 16), (80, 16), (8, 16)))
    # Forward phase 8 is foreground, return phase 64 is a gap.
    assert context.image.getpixel((16, 16)) == (0, 0, 0)


@pytest.mark.parametrize("direction", (-1, 1))
def test_round_join_distinguishes_reversal_from_straight_continuation(direction):
    first = StrokeSegment.line((1024 - 256 * direction, 1024), (1024, 1024))
    reverse = StrokeSegment.line(first.end, first.start)
    straight = StrokeSegment.line(first.end, (1024 + 256 * direction, 1024))
    pen = realize_pen(7)
    assert join_outline(first, straight, pen) == []
    assert contains((join_outline(first, reverse, pen),), 64 + 2 * direction, 64)


@pytest.mark.parametrize(
    "width,delta,expected",
    (
        (2, (-64, 128), (1032, 1040)),
        (7, (-128, 312), (1064, 1064)),
        (8, (-152, 360), (1072, 1072)),
        (8, (152, -360), (960, 1024)),
    ),
)
def test_native_support_at_half_contour_seams(width, delta, expected):
    # First widened-path vertex in original 28.4 device coordinates.
    # Support ties must select the same half-contour as the native traversal.
    start = (1024, 1024)
    end = (start[0] + delta[0], start[1] + delta[1])
    assert widen_segment(StrokeSegment.line(start, end), realize_pen(width))[0] == expected


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
