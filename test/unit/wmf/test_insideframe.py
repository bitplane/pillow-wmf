import pytest

from pillow_wmf import RasterContext


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
