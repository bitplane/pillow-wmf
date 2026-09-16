import pytest

from pillow_wmf.ellipse import arc_cubics
from pillow_wmf.raster import RasterContext


def test_arc_native_controls_distinguish_terminal_and_intermediate_quadrants():
    # Run 35099322489: GetPath reads the original device path, not a drawing
    # enlarged to 16x. The one-unit difference survives in wide raster output.
    assert arc_cubics(6, 70, 26, 92, (17, 81), (15, 82)) == (
        ((400, 1288), (400, 1195), (332, 1120), (248, 1120)),
        ((248, 1120), (164, 1120), (96, 1196), (96, 1288)),
        ((96, 1288), (96, 1330), (110, 1370), (136, 1401)),
    )


def test_arc_native_cardinal_boundary_piece_is_retained():
    assert arc_cubics(8, 8, 56, 56, (32, 31), (31, 32)) == (
        ((504, 128), (504, 128), (504, 128), (504, 128)),
        ((504, 128), (296, 128), (128, 296), (128, 504)),
    )


@pytest.mark.parametrize("style", (0, 1, 3, 5))
@pytest.mark.parametrize("change_start", (False, True))
@pytest.mark.parametrize("direction", ((1, -1), (-1, -1), (1, 0), (0, -1)))
def test_radial_distance_does_not_change_arc(style, change_start, direction):
    images = []
    for distance in (1, 10, 100):
        context = RasterContext(64, 64)
        context.select_object(context.create_pen(style, 1, 0))
        radial = tuple(32 + distance * component for component in direction)
        start, end = (radial, (8, 40)) if change_start else ((56, 40), radial)
        context.arc(8, 8, 56, 56, *start, *end)
        images.append(context.image.tobytes())
    assert images[0] == images[1] == images[2]
