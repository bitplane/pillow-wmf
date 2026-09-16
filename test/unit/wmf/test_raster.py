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


def test_zero_length_wide_line_draws_the_native_pen_footprint() -> None:
    context = RasterContext(16, 16)
    context.select_object(context.create_pen(0, 3, 0))
    context.move_to(8, 8)
    context.line_to(8, 8)
    pixels = {(x, y) for y in range(16) for x in range(16) if context.image.getpixel((x, y)) == (0, 0, 0)}
    assert pixels == {(8, 8), (7, 8), (9, 8), (8, 7), (8, 9)}


def test_save_restore_keeps_device_clip_without_copying_or_trimming_it() -> None:
    context = RasterContext(16, 16)
    context.intersect_clip_rect(32, 32, 40, 40)
    context.save_dc()
    context.offset_clip_region(-32, -32)
    context.set_pixel(4, 4, 0)
    context.restore_dc(-1)
    context.set_pixel(5, 5, 0)
    assert context.image.getpixel((4, 4)) == (0, 0, 0)
    assert context.image.getpixel((5, 5)) == (255, 255, 255)
