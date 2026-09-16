import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_figure


@pytest.mark.parametrize(
    "null_pen,expected",
    (
        (False, (((432, 252), (431, 207), (409, 165), (371, 135)), ((371, 135), (256, 256)), ((256, 256), (432, 252)))),
        (True, (((420, 244), (419, 200), (397, 159), (361, 130)), ((361, 130), (248, 248)), ((248, 248), (420, 244)))),
    ),
)
def test_native_pie_control_points_and_closure(null_pen, expected):
    # GetPath captured before implementation, Windows run 35145099841.
    path = arc_figure(5, 6, 28, 27, (36, 16), (36, -4), closure="pie", null_pen=null_pen)
    assert path.closed
    assert path.commands == expected


def test_full_revolution_pie_keeps_both_radials():
    path = arc_figure(8, 16, 120, 112, (120, 64), (120, 64), closure="pie")
    assert path.commands[-2:] == (((1904, 1016), (1016, 1016)), ((1016, 1016), (1904, 1016)))


def test_pie_preserves_current_position():
    context = RasterContext(128, 128)
    context.move_to(4, 4)
    context.pie(32, 32, 112, 112, 112, 72, 72, 32)
    context.line_to(12, 4)
    assert context.image.getpixel((8, 4)) == (0, 0, 0)


@pytest.mark.parametrize("box", ((8, 8, 8, 64), (8, 8, 64, 8)))
def test_empty_pie_bounds_draw_nothing(box):
    context = RasterContext(128, 128)
    before = context.image.tobytes()
    context.pie(*box, 120, 64, 64, 8)
    assert context.image.tobytes() == before
