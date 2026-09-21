from fractions import Fraction

import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_figure, ellipse_cubics
from pillow_wmf.geometry import StrokeSegment
from pillow_wmf.stroke import join_outline, realize_pen


@pytest.mark.parametrize("width", (0, 1, 3, 7))
def test_insideframe_is_solid_for_unbounded_primitives(width):
    images = []
    for style in (0, 6):
        context = RasterContext(24, 24)
        context.select_object(context.create_pen(style, width, 0))
        context.polyline(((4, 4), (20, 6), (4, 9)))
        context.polygon(((4, 14), (20, 16), (12, 20)))
        images.append(context.image.tobytes())
    assert images[0] == images[1]


def test_insideframe_ellipse_preserves_half_pixel_inset():
    # Native GetPath, PS_INSIDEFRAME width 3; coordinates in device sixteenths.
    curves = ellipse_cubics(5, 6, 26, 43, drawing_bounds=(104, 120, 392, 664))
    assert curves == (
        ((392, 392), (392, 242), (328, 120), (248, 120)),
        ((248, 120), (168, 120), (104, 242), (104, 392)),
        ((104, 392), (104, 542), (168, 664), (248, 664)),
        ((248, 664), (328, 664), (392, 542), (392, 392)),
    )


def test_insideframe_arc_normalizes_radials_against_original_box():
    # Native GetPath, width 7. Insetting the radial reference box changes angles.
    path = arc_figure(5, 6, 26, 43, (35, 16), (-5, 34), drawing_bounds=(136, 152, 360, 632))
    assert path.commands == (
        ((357, 334), (344, 227), (299, 152), (248, 152)),
        ((248, 152), (186, 152), (136, 260), (136, 392)),
        ((136, 392), (136, 413), (137, 433), (140, 453)),
    )


@pytest.mark.parametrize("operation", ("rectangle", "ellipse", "round_rect", "chord", "pie"))
def test_collapsed_closed_figure_retains_pen_footprint(operation):
    context = RasterContext(128, 128)
    context.select_object(context.create_pen(6, 21, 0))
    args = (5, 6, 26, 27)
    if operation == "round_rect":
        args += (13, 19)
    elif operation in ("chord", "pie"):
        args += (35, 16, -5, 34)
    getattr(context, operation)(*args)
    # Windows draws the same realized pen at the collapsed centre.
    assert sum(pixel == (0, 0, 0) for pixel in context.image.get_flattened_data()) == 332


def test_logical_collapse_can_invert_quantized_device_bounds(monkeypatch):
    paths = []
    context = RasterContext(128, 128)
    context.set_viewport_extent(192, 96)
    context.select_object(context.create_pen(6, 21, 0))
    monkeypatch.setattr(context, "_stroke_path", lambda path: paths.append(path))
    context.arc(5, 6, 26, 43, 35, 16, -5, 34)
    # Native accepts logical equality even though mapping inverts x by 8/16.
    assert paths[0].commands == (
        ((372, 274), (373, 234), (374, 206), (376, 206)),
        ((376, 206), (378, 206), (380, 247), (380, 296)),
        ((380, 296), (380, 304), (380, 311), (380, 319)),
    )


def test_fractional_roundrect_uses_logical_corner_proportions(monkeypatch):
    paths = []
    context = RasterContext(128, 128)
    context.set_viewport_extent(192, 96)
    context.select_object(context.create_pen(6, 0, 0))
    monkeypatch.setattr(context, "_paint_polygons", lambda figures, **kwargs: paths.extend(figures))
    context.round_rect(5, 6, 26, 43, 13, 19)
    assert paths[0].commands[0] == ((608, 187), (608, 128), (542, 80), (459, 80))


def test_round_join_retains_native_half_contour_seam():
    # Native WidenPath: the unrounded seam (122,225) lies between the
    # rounded support (118,225) and the next ordinary pen vertex.
    first = StrokeSegment((372, 274), (374, 225), (1, -40))
    second = StrokeSegment((374, 225), (376, 206), (2, 0))
    pen = realize_pen(21, Fraction(3, 2), Fraction(3, 4))
    assert join_outline(first, second, pen) == [
        (374, 225),
        (118, 225),
        (122, 225),
        (142, 176),
        (196, 136),
        (276, 109),
        (374, 97),
    ]
