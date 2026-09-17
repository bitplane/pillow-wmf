from struct import pack, pack_into, unpack_from

import pytest

from pillow_wmf import FormatError, RasterContext, UnsupportedOperation
from pillow_wmf.bitmap import RGBBitmap, decode_dib, encode_dib24
from pillow_wmf.wmf.objects import BitmapData


def test_encoder_has_independent_known_bytes():
    bitmap = RGBBitmap(1, 2, bytes((1, 2, 3, 4, 5, 6)))
    bottom = encode_dib24(bitmap).data
    top = encode_dib24(bitmap, top_down=True).data
    assert unpack_from("<IiiHHIIiiII", bottom) == (40, 1, 2, 1, 24, 0, 8, 0, 0, 0, 0)
    assert unpack_from("<i", top, 8)[0] == -2
    assert bottom[40:] == bytes((6, 5, 4, 0, 3, 2, 1, 0))
    assert top[40:] == bytes((3, 2, 1, 0, 6, 5, 4, 0))


@pytest.mark.parametrize("width", range(1, 9))
def test_encoder_row_alignment(width):
    bitmap = RGBBitmap(width, 3, bytes(range(width * 9)))
    assert len(encode_dib24(bitmap).data) == 40 + ((width * 3 + 3) & ~3) * 3


def test_bitmap_is_owned_immutable_and_bounded():
    with pytest.raises(TypeError):
        RGBBitmap(1, 1, bytearray(3))
    with pytest.raises(ValueError):
        RGBBitmap(0, 1, b"")
    with pytest.raises(ValueError):
        RGBBitmap(1, 1, b"")
    with pytest.raises(IndexError):
        RGBBitmap(1, 1, bytes(3)).pixel(-1, 0)


@pytest.mark.parametrize(
    "height,payload", ((2, bytes((6, 5, 4, 99, 3, 2, 1, 88))), (-2, bytes((3, 2, 1, 99, 6, 5, 4, 88))))
)
def test_decoder_known_bytes_not_encoder_roundtrip(height, payload):
    header = pack("<IiiHHIIiiII", 40, 1, height, 1, 24, 0, 0, 0, 0, 0, 0)
    decoded = decode_dib(BitmapData("dib", header + payload))
    assert decoded == RGBBitmap(1, 2, bytes((1, 2, 3, 4, 5, 6)))


@pytest.mark.parametrize("width", range(1, 9))
@pytest.mark.parametrize("top_down", (False, True))
def test_dib_roundtrip(width, top_down):
    bitmap = RGBBitmap(width, 3, bytes(range(width * 9)))
    assert decode_dib(encode_dib24(bitmap, top_down=top_down)) == bitmap


@pytest.mark.parametrize("length", (0, 3, 20, 39, 40, 43))
def test_truncated_header_or_pixels(length):
    source = encode_dib24(RGBBitmap(1, 1, bytes(3))).data
    with pytest.raises(FormatError):
        decode_dib(BitmapData("dib", source[:length]))


@pytest.mark.parametrize("offset,fmt,value", ((4, "i", 0), (4, "i", -1), (8, "i", 0), (12, "H", 0), (12, "H", 2)))
def test_invalid_header_fields(offset, fmt, value):
    data = bytearray(encode_dib24(RGBBitmap(1, 1, bytes(3))).data)
    pack_into("<" + fmt, data, offset, value)
    with pytest.raises(FormatError):
        decode_dib(BitmapData("dib", bytes(data)))


@pytest.mark.parametrize("offset,fmt,value", ((0, "I", 64), (14, "H", 2), (16, "I", 4), (16, "I", 5)))
def test_unimplemented_representations_are_not_approximated(offset, fmt, value):
    data = bytearray(encode_dib24(RGBBitmap(1, 1, bytes(3))).data)
    pack_into("<" + fmt, data, offset, value)
    with pytest.raises(UnsupportedOperation):
        decode_dib(BitmapData("dib", bytes(data)))


@pytest.mark.parametrize("offset,fmt,value", ((0, "I", 12), (0, "I", 108), (14, "H", 8), (16, "I", 1), (16, "I", 3)))
def test_header_mutations_without_required_format_data_are_malformed(offset, fmt, value):
    data = bytearray(encode_dib24(RGBBitmap(1, 1, bytes(3))).data)
    pack_into("<" + fmt, data, offset, value)
    with pytest.raises(FormatError):
        decode_dib(BitmapData("dib", bytes(data)))


def test_pixel_budget_checked_before_allocation_and_before_context_commit():
    bitmap = encode_dib24(RGBBitmap(3, 2, bytes(18)))
    with pytest.raises(FormatError, match="limit"):
        decode_dib(bitmap, max_pixels=5)
    context = RasterContext(16, 16, max_bitmap_pixels=5)
    with pytest.raises(FormatError, match="limit"):
        context.create_dib_pattern_brush(5, 0, bitmap)
    assert context.calls == []
    assert context._objects == {}


def test_optional_colour_table_is_skipped_not_decoded_as_pixels():
    data = bytearray(encode_dib24(RGBBitmap(1, 1, bytes((1, 2, 3)))).data)
    pack_into("<I", data, 32, 2)
    bitmap = BitmapData("dib", bytes(data[:40]) + bytes(8) + bytes(data[40:]))
    assert decode_dib(bitmap).pixel(0, 0) == (1, 2, 3)
    with pytest.raises(FormatError):
        decode_dib(BitmapData("dib", bytes(data)))


def test_unknown_palette_usage_and_legacy_bitmap_remain_unsupported():
    bitmap = encode_dib24(RGBBitmap(1, 1, bytes(3)))
    with pytest.raises(UnsupportedOperation):
        decode_dib(bitmap, color_usage=3)
    with pytest.raises(UnsupportedOperation):
        decode_dib(BitmapData("bitmap16", bytes(20)))


def test_rgb_to_mono_is_exact_colour_matching():
    values = bytes(channel for gray in range(256) for channel in (gray, gray, gray))
    result = RGBBitmap(256, 1, values).monochrome()
    assert result.pixels == bytes(255 * 3) + b"\xff\xff\xff"


def test_legacy_top_down_creation_is_null_and_selection_preserves_brush():
    context = RasterContext(8, 8)
    first = context.create_brush(0, 0x123456, 0)
    context.select_object(first)
    handle = context.create_dib_pattern_brush(3, 0, encode_dib24(RGBBitmap(1, 1, bytes(3)), top_down=True))
    assert context.is_null_object(handle)
    context.select_object(handle)
    context.pat_blt(0, 0, 8, 8, 0xF00021)
    assert set(context.image.get_flattened_data()) == {(0x56, 0x34, 0x12)}


def test_mono_brush_uses_live_colours_and_saved_text_state():
    context = RasterContext(4, 4)
    context.select_object(context.create_dib_pattern_brush(3, 0, encode_dib24(RGBBitmap(2, 1, b"\0\0\0\xff\xff\xff"))))
    context.set_background_mode(1)
    context.set_text_color(0x123456)
    context.set_background_color(0xABCDEF)
    context.save_dc()
    context.set_text_color(0)
    context.restore_dc(-1)
    context.pat_blt(0, 0, 4, 4, 0xF00021)
    assert context.image.getpixel((0, 0)) == (0x56, 0x34, 0x12)
    assert context.image.getpixel((1, 0)) == (0xEF, 0xCD, 0xAB)


def test_decoder_does_not_allocate_from_untrusted_size_image():
    data = bytearray(encode_dib24(RGBBitmap(1, 1, bytes(3))).data)
    pack_into("<I", data, 20, 0xFFFFFFFF)
    assert decode_dib(BitmapData("dib", bytes(data))).pixels == bytes(3)


def test_giant_dimensions_rejected_before_missing_pixel_check():
    header = pack("<IiiHHIIiiII", 40, 0x7FFFFFFF, -0x80000000, 1, 24, 0, 0, 0, 0, 0, 0)
    with pytest.raises(FormatError, match="limit"):
        decode_dib(BitmapData("dib", header))
