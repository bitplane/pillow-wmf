import pytest

from pillow_wmf.raster import RasterContext


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
