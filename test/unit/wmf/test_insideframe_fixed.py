"""Exact device-path measurements from Windows runs 35317428796 and 35319631193."""

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import box_axes, box_corners


def capture(monkeypatch, operation, *, width=45, window=(2048, 2048), origin=(0, 0), box=(256, 256, 1792, 1792)):
    context = RasterContext(128, 128)
    context.set_map_mode(8)
    context.set_window_origin(*origin)
    context.set_window_extent(*window)
    context.select_object(context.create_pen(6, width, 0))
    paths = []
    monkeypatch.setattr(context, "_paint_polygons", lambda figures, **kwargs: paths.extend(figures))
    monkeypatch.setattr(context, "_stroke_path", lambda path, **kwargs: paths.append(path))
    args = box
    if operation == "round_rect":
        args += (768, 1024)
    elif operation in ("arc", "chord", "pie"):
        args += (1792, 512, 0, 1792)
    getattr(context, operation)(*args)
    return paths[0]


def test_odd_box_keeps_reflected_corner_and_half_edge_rounding():
    bounds = (279, 279, 1770, 1769)
    assert box_corners(bounds) == ((1770, 279), (279, 279), (278, 1769), (1769, 1769))
    assert box_axes(bounds) == ((1025, 1024), (746, 0), (1, -745))


@pytest.mark.parametrize(
    "width,window,origin,box,first,second",
    (
        (
            48,
            (2232, 2218),
            (-1114, -917),
            (-1058, -877, 1092, 1279),
            ((2010, 1032), (2010, 492), (1576, 54), (1040, 54)),
            ((1040, 54), (504, 54), (70, 492), (70, 1032)),
        ),
        (
            48,
            (2203, 2218),
            (-1099, -917),
            (-1065, -873, 1079, 1277),
            ((2010, 1040), (2010, 505), (1573, 70), (1032, 70)),
            ((1032, 70), (492, 70), (55, 505), (54, 1040)),
        ),
        (
            80,
            (2299, 2299),
            (-1147, -955),
            (-1104, -889, 1106, 1299),
            ((1965, 1040), (1965, 521), (1541, 100), (1016, 100)),
            ((1016, 100), (492, 100), (68, 521), (67, 1040)),
        ),
        (
            96,
            (2021, 2092),
            (-1008, -854),
            (-905, -726, 921, 1111),
            ((1904, 1024), (1904, 556), (1514, 175), (1032, 175)),
            ((1032, 175), (551, 175), (161, 556), (160, 1024)),
        ),
        (
            79,
            (1987, 2078),
            (-1003, -931),
            (-961, -889, 940, 1107),
            ((1960, 1032), (1960, 511), (1541, 87), (1024, 87)),
            ((1024, 87), (508, 87), (89, 511), (88, 1032)),
        ),
    ),
)
def test_native_ellipse_controls(monkeypatch, width, window, origin, box, first, second):
    path = capture(monkeypatch, "ellipse", width=width, window=window, origin=origin, box=box)
    assert path.commands[:2] == (first, second)
    cx, cy = first[-1][0], first[0][1]
    assert path.commands[2:] == tuple(tuple((2 * cx - x, 2 * cy - y) for x, y in curve) for curve in (first, second))


def test_native_odd_roundrect_corner(monkeypatch):
    path = capture(monkeypatch, "round_rect")
    assert path.commands[0] == ((1769, 776), (1770, 502), (1604, 279), (1397, 279))
    assert path.commands[2] == ((652, 279), (445, 279), (279, 502), (278, 776))


@pytest.mark.parametrize("operation", ("arc", "chord", "pie"))
def test_native_odd_arc_uses_box_axes_and_connected_cubics(monkeypatch, operation):
    path = capture(monkeypatch, operation)
    assert path.commands[:3] == (
        ((1646, 611), (1508, 404), (1275, 279), (1026, 279)),
        ((1026, 279), (612, 279), (279, 613), (278, 1024)),
        ((278, 1024), (279, 1185), (331, 1342), (428, 1471)),
    )
    if operation == "pie":
        assert path.commands[3][-1] == (1025, 1024)
