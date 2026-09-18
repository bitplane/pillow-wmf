"""Fixed-point pen construction, guarded end-to-end by native pen-radius probes."""

from fractions import Fraction

import pytest

from pillow_wmf.geometry import StrokeSegment
from pillow_wmf.stroke import realize_pen, widen_segment


@pytest.mark.parametrize("sign", (1, -1))
@pytest.mark.parametrize("width", (511, 512, 513))
def test_native_thin_pen_size_limit(width, sign):
    # Native pen thickening rejects half-basis components
    # >=4096 fixed units before testing the collapsed minor axis.
    pen = realize_pen(width, sign, Fraction(1, 1024))
    outline = widen_segment(StrokeSegment.line((0, 0), (0, 0)), pen)
    if width == 511:
        assert outline == [(0, -8), (-4087, 0), (0, 8), (0, 8), (4087, 0), (0, -8)]
    else:
        expected = {
            (512, 1): [(4072, 0), (4095, 0), (4074, 0), (4012, 0), (3911, 0), (3773, 0), (3601, -1)],
            (512, -1): [(-4072, 0), (-4095, 0), (-4074, 0), (-4012, 0), (-3911, 0), (-3773, 1), (-3601, 1)],
            (513, 1): [(4080, 0), (4103, 0), (4082, 0), (4020, 0), (3919, 0), (3781, 0), (3608, -1)],
            (513, -1): [(-4080, 0), (-4103, 0), (-4082, 0), (-4020, 0), (-3918, 0), (-3780, 1), (-3608, 1)],
        }
        assert outline[:7] == expected[width, sign]
        assert len(outline) == 62
        assert (0, -3) in outline and (0, 3) in outline


@pytest.mark.parametrize(
    "width,scale_x,scale_y,radii",
    (
        (176, Fraction(128, 8118), Fraction(128, 8035), (22, 23)),
        (6, Fraction(128, 412), Fraction(128, 1915), (15, 8)),
        (8, Fraction(128, 412), Fraction(128, 1915), (20, 5)),
        (6, Fraction(128, 412), Fraction(128, 1536), (15, 8)),
        (6, Fraction(128, 412), Fraction(128, 1535), (15, 8)),
        (6, Fraction(128, 412), Fraction(128, 1280), (15, 5)),
        (1, Fraction(3, 2), Fraction(3, 4), (12, 6)),
        (4, Fraction(2224, 3200), Fraction(2300, 3200), (22, 23)),
        (4, Fraction(2226, 3200), Fraction(2300, 3200), (23, 23)),
        (4, Fraction(2220, 3200), Fraction(324, 3200), (22, 8)),
        (4, Fraction(2220, 3200), Fraction(326, 3200), (22, 8)),
    ),
)
@pytest.mark.parametrize("x_sign,y_sign", ((1, 1), (-1, 1), (1, -1), (-1, -1)))
def test_diameter_rounding_and_collapsed_axis(width, scale_x, scale_y, radii, x_sign, y_sign):
    pen = realize_pen(width, scale_x * x_sign, scale_y * y_sign)
    assert not pen.cosmetic
    assert pen.vertices[0] == (radii[0] * x_sign, 0)
    assert (0, -radii[1] * x_sign) in pen.vertices
    assert max(abs(x) for x, _ in pen.vertices) == radii[0]
    assert max(abs(y) for _, y in pen.vertices) == radii[1]


def test_minor_axis_minimum_does_not_enlarge_cosmetic_pen():
    assert realize_pen(1, Fraction(1, 4), 20) == realize_pen(0)


def test_geometric_frame_pen_keeps_subpixel_minor_axis():
    pen = realize_pen(6, Fraction(128, 412), Fraction(128, 1915), geometric=True)
    assert max(abs(y) for _, y in pen.vertices) == 3


@pytest.mark.parametrize("window", ((2232, 2218), (2213, 2223)))
def test_circular_table_selection_uses_fixed_diameters(window):
    # Both native coin pens have the width-3 contour despite unequal scales.
    pen = realize_pen(48, Fraction(128, window[0]), Fraction(128, window[1]))
    assert pen == realize_pen(3)
    assert widen_segment(StrokeSegment.line((1024, 1024), (1024, 1024)), pen) == [
        (1032, 1000),
        (1017, 1001),
        (1001, 1017),
        (1001, 1031),
        (1016, 1048),
        (1016, 1048),
        (1031, 1047),
        (1047, 1031),
        (1047, 1017),
        (1032, 1000),
    ]


def test_fractional_pen_matches_native_widened_contour():
    # Exact device sixteenths measured from the widened path, not inferred
    # from the final raster pixels. No unrounded logical tangent is needed.
    pen = realize_pen(176, Fraction(128, 8118), Fraction(128, 8035))
    assert widen_segment(StrokeSegment.line((1024, 1024), (1200, 592)), pen) == [
        (1008, 1008),
        (1003, 1024),
        (1009, 1039),
        (1024, 1046),
        (1040, 1040),
        (1216, 608),
        (1221, 592),
        (1215, 577),
        (1200, 570),
        (1184, 576),
    ]


@pytest.mark.parametrize("window_y,end_y,cap_y", ((1915, 2096, 7), (1536, 2352, 7), (1535, 2352, 7), (1280, 2624, 4)))
def test_subpixel_axis_matches_native_vertical_caps(window_y, end_y, cap_y):
    pen = realize_pen(6, Fraction(128, 412), Fraction(128, window_y))
    assert widen_segment(StrokeSegment.line((1024, 1024), (1024, end_y)), pen) == [
        (1040, 1024),
        (1024, 1024 - cap_y),
        (1008, 1024),
        (1008, end_y),
        (1024, end_y + cap_y),
        (1040, end_y),
    ]


@pytest.mark.parametrize("window_x,cap_x", ((324, 25), (128, 63), (32, 255), (-128, 63)))
@pytest.mark.parametrize("window_y", (8192, 4096, 2048))
def test_collapsed_pen_axis_has_native_diamond_contour(window_x, cap_x, window_y):
    # Run 35321454120: shoulders disappear across aspect ratios and reflection.
    pen = realize_pen(8, Fraction(128, window_x), Fraction(128, window_y))
    assert widen_segment(StrokeSegment.line((0, 0), (0, 0)), pen) == [
        (0, -8),
        (-cap_x, 0),
        (0, 8),
        (0, 8),
        (cap_x, 0),
        (0, -8),
    ]


def test_collapsed_pen_matches_native_shallow_segment():
    # Run 35321235589, with the original corpus mapping and mapped endpoints.
    pen = realize_pen(8, Fraction(128, 324), Fraction(128, 2038))
    assert widen_segment(StrokeSegment.line((1648, 944), (1744, 960)), pen) == [
        (1648, 936),
        (1623, 944),
        (1648, 952),
        (1744, 968),
        (1769, 960),
        (1744, 952),
    ]


@pytest.mark.parametrize(
    "window_x,half",
    (
        (324, ((0, -8), (-18, -2), (-25, 0), (-18, 2), (0, 8))),
        (128, ((0, -8), (-44, -2), (-63, 0), (-45, 2), (0, 8))),
        (-128, ((0, -8), (-44, -3), (-63, 0), (-44, 3), (0, 8))),
        (32, ((0, -8), (-99, -3), (-180, -2), (-235, -1), (-255, 0), (-235, 1), (-180, 2), (-99, 3), (0, 8))),
    ),
)
def test_adjacent_noncollapsed_pen_retains_native_shoulders(window_x, half):
    # The same run measures the adjacent cubic contours, including reflection.
    pen = realize_pen(8, Fraction(128, window_x), Fraction(128, 1920))
    assert widen_segment(StrokeSegment.line((0, 0), (0, 0)), pen) == [*half, *((-x, -y) for x, y in half)]
