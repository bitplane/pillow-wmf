import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_cubics, ellipse_cubics
from pillow_wmf.geometry import DevicePath
from pillow_wmf.stroke import cosmetic_line


def test_equal_radials_keep_native_terminal_quadrant_arithmetic():
    # Identical radial points follow the same native path
    # construction as distinct points on the same ray, not Ellipse's shortcut.
    curves = arc_cubics(8, 16, 120, 112, (120, 64), (120, 64))
    assert curves == arc_cubics(8, 16, 120, 112, (120, 64), (176, 64))
    assert curves[0] == ((1904, 1016), (1904, 596), (1506, 256), (1016, 256))
    assert curves[-1] == ((1904, 1016),) * 4


def test_null_pen_native_curve_bounds():
    # Run 35115154670: same geometry for PS_NULL widths 0, 1 and 7,
    # measured independently with Arc, Chord and Ellipse.
    assert arc_cubics(5, 6, 28, 27, (36, 16), (36, -4), null_pen=True) == (
        ((420, 244), (419, 200), (397, 159), (361, 130)),
    )
    assert ellipse_cubics(25, 3, 78, 64, null_pen=True)[0] == ((1220, 520), (1220, 258), (1036, 44), (808, 44))


@pytest.mark.parametrize("operation", ("arc", "chord", "ellipse", "rectangle"))
def test_default_stock_pen_is_device_hairline(operation):
    # Native GetObject(BLACK_PEN) reports width zero, not logical width one.
    default, explicit = RasterContext(128, 128), RasterContext(128, 128)
    explicit.select_object(explicit.create_pen(0, 0, 0))
    for context in (default, explicit):
        context.set_map_mode(8)
        context.set_viewport_extent(256, 128)
        args = (8, 8, 56, 104)
        if operation in ("arc", "chord"):
            args += (56, 40, 17, 93)
        getattr(context, operation)(*args)
    assert default.image.tobytes() == explicit.image.tobytes()


def test_chord_preserves_current_position():
    context = RasterContext(128, 128)
    context.move_to(4, 4)
    context.chord(32, 32, 112, 112, 112, 72, 72, 32)
    context.line_to(12, 4)
    assert context.image.getpixel((8, 4)) == (0, 0, 0)


@pytest.mark.parametrize("closed", (False, True))
def test_fractional_figure_starts_at_dash_phase_zero(closed):
    # Independent native fractional-path probe, not a Chord-specific phase.
    points = ((513, 519), (1001, 287), (1389, 1271))
    context = RasterContext(128, 128)
    context.select_object(context.create_pen(1, 1, 0))
    foreground, gaps = context._stroke_fragments((DevicePath.polyline(points, closed=closed),))
    first_span = list(cosmetic_line(*points[:2], 128, 128))
    assert set(first_span[:18]) <= foreground
    assert set(first_span[18:24]) <= gaps
