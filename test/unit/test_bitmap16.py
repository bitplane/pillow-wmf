from struct import pack, pack_into

import pytest

from pillow_wmf import FormatError, RasterContext, UnsupportedOperation
from pillow_wmf.bitmap16 import encode_bitmap16, read_bitmap16
from pillow_wmf.wmf.objects import BitmapData


@pytest.mark.parametrize("pattern", (False, True))
def test_known_monochrome_bytes_and_top_down_word_rows(pattern):
    values = (1, 0, 1, 0, 1, 0)
    source = encode_bitmap16(3, 2, values, pattern=pattern)
    assert source.data == pack("<hhhhBB", 0, 3, 2, 2, 1, 1) + (bytes(22) if pattern else b"") + b"\xa0\0\x40\0"
    assert read_bitmap16(source).decode().pixels == bytes(c for v in values for c in (255 * v,) * 3)


@pytest.mark.parametrize("depth", (1, 4, 8, 16, 24, 32))
@pytest.mark.parametrize("width", (1, 3, 7, 8, 9, 15, 16, 17))
def test_word_padding_and_depths(depth, width):
    source = encode_bitmap16(width, 3, (0,) * width * 3, depth=depth)
    layout = read_bitmap16(source)
    assert layout.stride == ((width * depth + 15) // 16) * 2
    assert layout.decode(
        colors=((0, 0, 0),) * (1 << depth) if depth <= 8 else None,
        masks=(0xF800, 0x7E0, 0x1F) if depth == 16 else None,
    ).pixels == bytes(width * 9)


def test_24bit_word_aligned_scanlines_are_not_dib_dword_scanlines():
    source = BitmapData("bitmap16", pack("<hhhhBB", 0, 2, 2, 6, 1, 24) + bytes((3, 2, 1, 6, 5, 4, 9, 8, 7, 12, 11, 10)))
    assert read_bitmap16(source).decode().pixels == bytes(range(1, 13))


def test_indexed_device_bitmap_has_no_implicit_dib_palette():
    source = encode_bitmap16(3, 1, (2, 1, 0), depth=4)
    with pytest.raises(UnsupportedOperation, match="device colour table"):
        read_bitmap16(source).decode()
    colors = ((7, 11, 13), (17, 23, 29), (31, 37, 41))
    assert read_bitmap16(source).decode(colors=colors).pixels == bytes(colors[2] + colors[1] + colors[0])


@pytest.mark.parametrize("pattern", (False, True))
def test_header_payload_truncation_and_pixel_budget(pattern):
    source = encode_bitmap16(9, 3, (0,) * 27, pattern=pattern)
    with pytest.raises(FormatError, match="limit"):
        read_bitmap16(source, max_pixels=26)
    for size in range(len(source.data)):
        with pytest.raises(FormatError):
            read_bitmap16(BitmapData(source.format, source.data[:size])).decode()


@pytest.mark.parametrize("field,value", ((2, 0), (4, -1), (8, 2)))
def test_invalid_geometry_and_planes(field, value):
    source = encode_bitmap16(1, 1, (0,))
    data = bytearray(source.data)
    pack_into("<B" if field == 8 else "<h", data, field, value)
    with pytest.raises(FormatError):
        read_bitmap16(BitmapData(source.format, bytes(data)))


def test_native_pattern_layout_is_explicit_not_guessed_from_length():
    source = encode_bitmap16(3, 2, (1, 0, 1, 0, 1, 0), pattern=True, native_pattern=True)
    assert source.data == pack("<hhhhBB", 0, 3, 2, 2, 1, 1) + bytes(26) + b"\xa0\0\x40\0"
    native = read_bitmap16(source, native_pattern=True)
    assert native.offset == 36
    assert native.decode().pixels == bytes((255, 255, 255, 0, 0, 0) * 3)
    assert read_bitmap16(source).decode().pixels == bytes(18)


def test_device_16bit_masks_are_not_assumed_to_be_dib_rgb555():
    source = encode_bitmap16(1, 1, (0x7E0,), depth=16)
    layout = read_bitmap16(source)
    with pytest.raises(UnsupportedOperation, match="device channel masks"):
        layout.decode()
    assert layout.decode(masks=(0xF800, 0x7E0, 0x1F)).pixels == b"\0\xff\0"


def test_pattern_pitch_is_honoured_but_transfer_pitch_is_derived():
    header = pack("<hhhhBB", 0, 1, 2, 4, 1, 1)
    bits = b"\x80\0\0\0\x80\0\0\0"
    pattern = read_bitmap16(BitmapData("pattern16", header + bytes(22) + bits))
    bitmap = read_bitmap16(BitmapData("bitmap16", header + bits))
    assert pattern.decode().pixels == b"\xff" * 6
    assert bitmap.decode().pixels == b"\xff" * 3 + b"\0" * 3


@pytest.mark.parametrize("stride", (0, 1, 3))
def test_invalid_pattern_pitch_is_rejected(stride):
    source = BitmapData("pattern16", pack("<hhhhBB", 0, 9, 1, stride, 1, 1) + bytes(24))
    with pytest.raises(FormatError, match="scanline"):
        read_bitmap16(source)


def test_incomplete_native_brush_is_null_but_incompatible_depth_is_not():
    dc = RasterContext(8, 8)
    short = dc.create_pattern_brush(encode_bitmap16(1, 1, (1,), pattern=True))
    incompatible = dc.create_pattern_brush(encode_bitmap16(1, 1, (1,), depth=4, pattern=True, native_pattern=True))
    assert dc.is_null_object(short)
    assert not dc.is_null_object(incompatible)
    dc.select_object(incompatible)
    dc.pat_blt(0, 0, 8, 8, 0xF00021)
    assert dc.image.getpixel((0, 0)) == (255, 255, 255)
    dc.pat_blt(0, 0, 8, 8, 0x550009)
    assert dc.image.getpixel((0, 0)) == (0, 0, 0)


def test_overlapping_source_free_copy_reads_original_pixels():
    dc = RasterContext(8, 1)
    for x in range(8):
        dc.set_pixel(x, 0, x)
    dc.bit_blt(2, 0, 6, 1, 0, 0, 0xCC0020)
    assert list(dc.image.get_flattened_data()) == [(x, 0, 0) for x in (0, 1, 0, 1, 2, 3, 4, 5)]


def test_bitmap_limit_failure_does_not_allocate_a_brush():
    dc = RasterContext(8, 8, max_bitmap_pixels=3)
    source = encode_bitmap16(2, 2, (0,) * 4, pattern=True, native_pattern=True)
    with pytest.raises(FormatError, match="limit"):
        dc.create_pattern_brush(source)
    assert not dc._objects


@pytest.mark.parametrize("depth", (1, 4, 8, 16, 24, 32))
def test_embedded_selection_result_controls_whether_pattern_rop_is_reached(depth):
    dc = RasterContext(4, 4)
    source = encode_bitmap16(1, 1, (0,), depth=depth)
    dc.bit_blt(0, 0, 4, 4, 0, 0, 0x000042, source)
    assert dc.image.getpixel((0, 0)) == ((255, 255, 255) if depth in (1, 32) else (0, 0, 0))


def test_short_embedded_bitmap_fails_before_pattern_rop_dispatch():
    dc = RasterContext(4, 4)
    source = encode_bitmap16(1, 1, (0,), depth=8)
    dc.bit_blt(0, 0, 4, 4, 0, 0, 0x000042, BitmapData("bitmap16", source.data[:10]))
    assert dc.image.getpixel((0, 0)) == (255, 255, 255)
