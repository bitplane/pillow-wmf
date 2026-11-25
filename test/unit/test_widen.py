"""Geometric pen outlines. Expected 28.4 points were read back from native WidenPath."""

import pytest

from pillow_wmf.geometry import StrokeSegment
from pillow_wmf.stroke import realize_pen
from pillow_wmf.widen import (
    CAP_FLAT,
    CAP_ROUND,
    CAP_SQUARE,
    JOIN_BEVEL,
    JOIN_MITER,
    PenShape,
    dash_figures,
    outline,
    perpendicular,
    square_vector,
)


def shape(width, cap, join, limit=10.0):
    return PenShape(realize_pen(width, 1, 1), (8 * width, 8 * width), (1.0, 1.0), cap, join, limit)


def figure(*points):
    points = [(16 * x, 16 * y) for x, y in points]
    return tuple(StrokeSegment.line(a, b) for a, b in zip(points, points[1:], strict=False))


@pytest.mark.parametrize(
    ("width", "direction", "expected"),
    [
        # Pen edge midpoints for lines along an edge, vertices for lines along
        # the chord joining the vertex's neighbours, interpolated between.
        (6, (64, 0), (0, -48)),
        (6, (64, 10), (8, -48)),
        (6, (64, 26), (16, -48)),
        (6, (64, 36), (16, -40)),
        (6, (64, 64), (32, -32)),
        (9, (12, 22), (56, -32)),
        (9, (24, 20), (48, -56)),
        (200, (64, 14), (288, -1576)),
        (200, (64, 17), (344, -1560)),
    ],
)
def test_perpendicular_follows_the_pen_polygon(width, direction, expected):
    assert perpendicular(realize_pen(width, 1, 1), (16 * direction[0], 16 * direction[1])) == expected


def test_flat_bevel_vee_outline():
    assert outline(shape(5, CAP_FLAT, JOIN_BEVEL), figure((6, 6), (18, 28), (30, 6)), False) == [
        [(128, 80), (64, 112), (256, 464), (320, 464), (512, 112), (448, 80), (256, 432), (288, 448), (320, 432)]
    ]


def test_miter_tip_and_square_caps():
    (points,) = outline(shape(5, CAP_SQUARE, JOIN_MITER), figure((6, 6), (18, 28), (30, 6)), False)
    assert points == [
        (109, 45),
        (45, 77),
        (256, 464),
        (288, 523),
        (320, 464),
        (531, 77),
        (467, 45),
        (256, 432),
        (288, 448),
        (320, 432),
    ]
    # A miter limit of one bevels every join.
    (beveled,) = outline(shape(4, CAP_FLAT, JOIN_MITER, 1.0), figure((6, 6), (16, 20), (26, 6)), False)
    assert (256, 378) not in beveled and len(beveled) == 9


def test_round_caps_walk_half_the_pen_from_the_perpendicular():
    (points,) = outline(shape(9, CAP_ROUND, JOIN_BEVEL), figure((6, 6), (46, 6)), False)
    # The pen vertex in the perpendicular's own direction is included at the
    # start of each cap; the one at the cap's far side is not.
    assert points[:6] == [(96, 24), (96, 25), (46, 46), (25, 96), (46, 146), (96, 168)]


def test_dashes_are_logical_lengths_with_round_cap_ends_pulled_back():
    line = figure((6, 6), (46, 14))
    flat = dash_figures(line, (9, 3), (1, 1))
    assert [(dash[0].start, dash[-1].end) for dash in flat][:2] == [((96, 96), (237, 124)), ((284, 134), (425, 162))]
    rounded = dash_figures(line, (9, 3), (1, 1), shorten=3)
    assert rounded[0][-1].end == (190, 115)
    # Dots with extending caps become zero-length dashes.
    dots = dash_figures(figure((6, 6), (46, 6)), (3, 3), (1, 1), shorten=3)
    assert dots[1] == (StrokeSegment((192, 96), (192, 96), (640, 0)),)


def test_scaled_square_caps_round_twice():
    scale = (2.5092592239379883, 2.5098910331726074)
    scaled = PenShape(realize_pen(2, *scale), (16 * scale[0], 16 * scale[1]), scale, CAP_SQUARE, JOIN_BEVEL)
    # Native 28.4 extensions for these device directions of the 2.5x fixture.
    assert square_vector(scaled, (201, 362)) == (20, 35)
    assert square_vector(scaled, (200, 362)) == (19, 35)
    assert square_vector(scaled, (200, 321)) == (21, 34)


def drawn(**pen):
    from pillow_wmf.raster import RasterContext

    context = RasterContext(24, 12, background=(255, 255, 255), trace_calls=False)
    context.select_object(context.ext_create_pen(**pen))
    context.set_background_mode(1)
    context.polyline(((2, 6), (22, 6)))
    return context.image.convert("RGB")


def test_hatched_pens_fill_their_footprint_with_the_hatch():
    image = drawn(style=0x00010200, width=6, color=0x0000FF, brush_style=2, hatch=3)
    marks = {(x, y) for x in range(24) for y in range(12) if image.getpixel((x, y)) == (255, 0, 0)}
    # Backward diagonals at (x + y) % 8 == 7 within the flat-capped body.
    assert marks and all((x + y) % 8 == 7 and 2 <= x < 22 and 3 <= y < 9 for x, y in marks)


@pytest.mark.parametrize(
    ("pen", "error"),
    [
        ({"style": 0x00010000, "width": 6, "color": 0, "brush_style": 3}, "UnsupportedOperation"),
        ({"style": 0x00000000, "width": 1, "color": 0, "brush_style": 2, "hatch": 1}, "InvalidOperation"),
        ({"style": 0x00010008, "width": 3, "color": 0}, "InvalidOperation"),  # Geometric alternate.
        ({"style": 0x00000007, "width": 1, "color": 0}, "InvalidOperation"),  # User style without entries.
    ],
)
def test_extended_pens_that_cannot_be_created(pen, error):
    from pillow_wmf.raster import RasterContext

    with pytest.raises(Exception) as caught:
        RasterContext(4, 4).ext_create_pen(**pen)
    assert type(caught.value).__name__ == error
