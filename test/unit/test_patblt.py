import pytest

from pillow_wmf import RasterContext
from pillow_wmf.mapping import Mapping


def test_driver_translation_is_quantized_before_point_conversion():
    mapping = Mapping(
        window_extent=(128, 127), viewport_extent=(43, -64), window_origin=(9, 8), viewport_origin=(64, 64)
    )
    # X: translation 60.9765625 -> 61; product -24.5234375 -> -24.5.
    # Rounding only the combined value (36.453125) would select pixel 36.
    assert mapping.point(-73, 19) == (36, 58)
    assert mapping.device_point(-73, 19) == (37, 59)
    assert mapping.clip_point(-73, 19) == (37, 59)


@pytest.mark.parametrize("width,height", ((4, 3), (-4, 3), (4, -3), (-4, -3), (0, 3), (4, 0)))
def test_signed_rectangle_is_half_open_without_pen(width, height):
    context = RasterContext(16, 16)
    context.select_object(context.create_pen(0, 7, 0))
    context.select_object(context.create_brush(0, 0x123456, 0))
    context.pat_blt(8, 8, width, height, 0x00F00021)
    for y in range(16):
        for x in range(16):
            inside = min(8, 8 + width) <= x < max(8, 8 + width) and min(8, 8 + height) <= y < max(8, 8 + height)
            assert context.image.getpixel((x, y)) == ((0x56, 0x34, 0x12) if inside else (255, 255, 255))


def test_source_dependent_operation_is_native_noop():
    context = RasterContext(8, 8)
    context.select_object(context.create_brush(0, 0, 0))
    context.pat_blt(0, 0, 8, 8, 0x00CC0020)  # SRCCOPY has no source here.
    assert context.image.getbbox() == (0, 0, 8, 8)
    assert set(context.image.get_flattened_data()) == {(255, 255, 255)}


def test_hatch_is_opaque_without_mutating_dc_background_or_rop():
    context = RasterContext(8, 8)
    context.select_object(context.create_brush(2, 0x123456, 0))
    context.set_background_mode(1)
    context.set_background_color(0xABCDEF)
    context.set_rop2(7)
    context.move_to(5, 6)
    context.pat_blt(0, 0, 8, 8, 0x00F00021)
    assert context.image.getpixel((0, 0)) == (0xEF, 0xCD, 0xAB)
    assert context.image.getpixel((0, 3)) == (0x56, 0x34, 0x12)
    assert context._background_mode == 1
    assert context._rop2 == 7
    assert context._position == (5, 6)


@pytest.mark.parametrize("rop,color", ((0x00000042, (0, 0, 0)), (0x00550009, (0, 0, 0)), (0x00FF0062, (255, 255, 255))))
def test_pattern_independent_rop_does_not_require_a_brush(rop, color):
    context = RasterContext(8, 8)
    context.select_object(context.create_brush(1, 0, 0))
    context.pat_blt(0, 0, 8, 8, rop)
    assert set(context.image.get_flattened_data()) == {color}
