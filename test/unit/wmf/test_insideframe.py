import pytest

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_figure, ellipse_cubics


@pytest.mark.parametrize("width", (0, 1, 3, 7))
def test_insideframe_is_solid_for_unbounded_primitives(width):
    images = []
    for style in (0, 6):
        context = RasterContext(128, 128)
        context.select_object(context.create_pen(style, width, 0))
        context.polyline(((8, 8), (112, 32), (8, 56)))
        context.polygon(((8, 72), (112, 80), (48, 112)))
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
