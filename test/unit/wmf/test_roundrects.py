import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import round_rect_figure


@pytest.mark.parametrize(
    "null_pen,expected",
    (
        (False, ((1904, 486), (1904, 359), (1844, 256), (1769, 256))),
        (True, ((1892, 480), (1892, 355), (1833, 252), (1758, 252))),
    ),
)
def test_native_round_rect_first_corner(null_pen, expected):
    # Native controls distinguish null-pen and outlined rectangle bounds.
    path = round_rect_figure(8, 16, 120, 112, 17, 29, null_pen=null_pen)
    assert path.commands[0] == expected


def test_native_corner_radius_half_tie_rounds_up():
    path = round_rect_figure(8, 16, 120, 112, 21, 22)
    assert path.commands[0][-1] == (1737, 256)  # Radius 166.5 becomes 167.


def test_round_rect_preserves_current_position():
    context = RasterContext(128, 128)
    context.move_to(4, 4)
    context.round_rect(32, 32, 112, 112, 17, 29)
    context.line_to(12, 4)
    assert context.image.getpixel((8, 4)) == (0, 0, 0)


@pytest.mark.parametrize("box", ((8, 8, 8, 64), (8, 8, 64, 8)))
def test_empty_round_rect_bounds_draw_nothing(box):
    context = RasterContext(128, 128)
    before = context.image.tobytes()
    context.round_rect(*box, 17, 29)
    assert context.image.tobytes() == before
