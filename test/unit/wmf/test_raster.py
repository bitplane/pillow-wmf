import pytest

from pillow_wmf import RasterContext, UnsupportedOperation


def test_raster_rejects_unimplemented_pen_style_before_changing_context() -> None:
    context = RasterContext(8, 8)
    with pytest.raises(UnsupportedOperation, match="solid"):
        context.create_pen(style=1, width=1, color=0)
    assert context.calls == []
    assert context.image.getpixel((0, 0)) == (255, 255, 255)


def test_raster_requires_positive_image_size() -> None:
    with pytest.raises(ValueError, match="positive"):
        RasterContext(0, 8)
