from struct import pack, pack_into

import pytest

from pillow_wmf import FormatError, RasterContext
from pillow_wmf.bitmap import RGBBitmap, decode_dib, encode_dib, field_color, read_dib
from pillow_wmf.dib_rle import decode_rle
from pillow_wmf.halftone import HalftoneContent, classify_content
from pillow_wmf.halftone_fixup import fixup_bitmap
from pillow_wmf.wmf.objects import BitmapData


def test_indexed_writer_has_independent_known_bytes():
    source = encode_dib(3, 1, (1, 0, 1), depth=1, colors=((11, 22, 33), (44, 55, 66)))
    assert source.data == (
        pack("<IiiHHIIiiII", 40, 3, 1, 1, 1, 0, 4, 0, 0, 2, 0) + bytes((33, 22, 11, 0, 66, 55, 44, 0, 0xA0, 0, 0, 0))
    )


@pytest.mark.parametrize("header", (12, 40, 108, 124))
@pytest.mark.parametrize("depth,payload", ((1, b"\xa0\0\0\0"), (4, b"\x10\x10\0\0"), (8, b"\1\0\1\0")))
def test_known_indexed_pixels_use_rgb_table_not_dc_colours(header, depth, payload):
    colors = ((11, 22, 33), (44, 55, 66)) + ((0, 0, 0),) * ((1 << depth) - 2)
    prefix = (
        pack("<IHHHH", 12, 3, 1, 1, depth)
        if header == 12
        else pack("<IiiHHIIiiII", header, 3, 1, 1, depth, 0, 0, 0, 0, 0, 0) + bytes(header - 40)
    )
    table = bytes(v for r, g, b in colors for v in ((b, g, r) if header == 12 else (b, g, r, 0)))
    assert decode_dib(BitmapData("dib", prefix + table + payload)) == RGBBitmap(
        3, 1, bytes((44, 55, 66, 11, 22, 33, 44, 55, 66))
    )


@pytest.mark.parametrize("depth", (1, 4, 8))
@pytest.mark.parametrize("top_down", (False, True))
@pytest.mark.parametrize("width", (1, 3, 7, 8, 9, 31, 33))
def test_indexed_roundtrip_packing_padding_and_orientation(depth, top_down, width):
    colors = tuple((i % 256, i * 31 % 256, i * 17 % 256) for i in range(1 << depth))
    samples = tuple(i % len(colors) for i in range(width * 3))
    source = encode_dib(width, 3, samples, depth=depth, colors=colors, top_down=top_down)
    assert decode_dib(source).pixels == bytes(v for sample in samples for v in colors[sample])


@pytest.mark.parametrize("header", (40, 108, 124))
def test_32bit_high_byte_is_not_alpha(header):
    source = encode_dib(3, 1, (0x00112233, 0x80112233, 0xFF112233), depth=32, header_size=header)
    assert decode_dib(source).pixels == bytes((0x11, 0x22, 0x33)) * 3


def test_short_indexed_table_rejects_out_of_range_pixels():
    source = encode_dib(1, 1, (0,), depth=8, colors=((1, 2, 3),))
    with pytest.raises(FormatError, match="index"):
        decode_dib(BitmapData("dib", source.data[:-4] + bytes((1, 0, 0, 0))))


@pytest.mark.parametrize("bits", (1, 2, 3, 4, 5, 6, 7, 8, 10))
def test_bitfields_duplicate_source_bits_once_not_linear_scale(bits):
    mask = (1 << bits) - 1
    for value in range(1 << bits):
        repeated = (format(value, f"0{bits}b") * 2)[:8].ljust(8, "0")
        assert field_color(value << 3, mask << 3) == int(repeated, 2)
        assert field_color(value << 3, mask << 3, replicate=False) == (value << 8) >> bits


@pytest.mark.parametrize("mask,expected", ((1, 192), (3, 240), (7, 252), (15, 255), (31, 255), (63, 255)))
def test_bitfield_maximum_matches_native_channel_ramps(mask, expected):
    assert field_color(mask, mask) == expected


@pytest.mark.parametrize("masks", ((0, 0x7E0, 31), (0xF800, 0x7E0, 0x7E0), (0xF801, 0x7E0, 30), (0x10000, 0x7E0, 31)))
def test_invalid_bitfields_are_rejected(masks):
    source = bytearray(encode_dib(1, 1, (0,), depth=16, masks=(0xF800, 0x7E0, 31)).data)
    pack_into("<III", source, 40, *masks)
    with pytest.raises(FormatError, match="mask"):
        decode_dib(BitmapData("dib", bytes(source)))


@pytest.mark.parametrize("depth", (4, 8))
def test_rle_command_stream_and_coverage_have_independent_expected_values(depth):
    data = (
        bytes((3, 2, 0, 5, 1, 3, 5, 7, 9, 0, 0, 0, 0, 2, 2, 1, 4, 6, 0, 1))
        if depth == 8
        else bytes((3, 0x23, 0, 5, 0x13, 0x57, 0x90, 0, 0, 0, 0, 2, 2, 1, 4, 0x68, 0, 1))
    )
    indexes, coverage = decode_rle(data, 13, 7, depth)
    assert indexes[:13] == bytes((2, 2 if depth == 8 else 3, 2, 1, 3, 5, 7, 9, 0, 0, 0, 0, 0))
    assert indexes[26:39] == bytes((0, 0, 6, 6 if depth == 8 else 8, 6, 6 if depth == 8 else 8, 0, 0, 0, 0, 0, 0, 0))
    assert coverage == b"\1" * 8 + bytes(20) + b"\1" * 4 + bytes(59)


@pytest.mark.parametrize("left", range(6))
@pytest.mark.parametrize("encoded", (False, True))
def test_rle4_clipping_restarts_only_encoded_pairs(left, encoded):
    data = bytes((8, 0x12, 0, 1)) if encoded else bytes((0, 8, 0x12, 0x12, 0x12, 0x12, 0, 1))
    indexes, coverage = decode_rle(data, 8, 1, 4, clip_spans=lambda y: ((left, 7),))
    phase = 0 if encoded else left
    assert indexes == bytes(left) + bytes(1 + (phase + i) % 2 for i in range(7 - left)) + b"\0"
    assert coverage == bytes(left) + b"\1" * (7 - left) + b"\0"


def test_rle4_each_clipped_span_restarts_at_the_encoded_high_nibble():
    indexes, coverage = decode_rle(bytes((9, 0x12, 0, 1)), 9, 1, 4, clip_spans=lambda y: ((1, 4), (5, 8)))
    assert indexes == bytes((0, 1, 2, 1, 0, 1, 2, 1, 0))
    assert coverage == bytes((0, 1, 1, 1, 0, 1, 1, 1, 0))


def test_clipped_rle_still_validates_the_entire_stream():
    with pytest.raises(FormatError, match="outside bitmap"):
        decode_rle(bytes((9, 0x12, 0, 1)), 8, 1, 4, clip_spans=lambda y: ())


@pytest.mark.parametrize("depth", (4, 8))
@pytest.mark.parametrize("width", (1, 3, 7, 256, 513))
def test_rle_writer_roundtrip_runs_cross_255_boundary(depth, width):
    colors = tuple((i * 11, i * 7, i * 5) for i in range(16))
    values = (3,) * width + tuple(x % 16 for x in range(width))
    source = encode_dib(width, 2, values, depth=depth, colors=colors, rle=True)
    assert decode_dib(source).pixels == bytes(v for i in values for v in colors[i])


@pytest.mark.parametrize("data", (b"", b"\1", b"\0\2\1", b"\0\5\1", b"\4\2\0\1", b"\0\2\4\0", b"\0\0\1\0", b"\1\2"))
def test_rle_truncation_and_bounds_are_rejected(data):
    with pytest.raises(FormatError):
        decode_rle(data, 3, 1, 8)


def test_rle_size_is_bounded_by_payload_not_an_allocation_request():
    data = bytearray(encode_dib(3, 1, (0, 1, 0), depth=4, colors=((0, 0, 0), (255, 255, 255)), rle=True).data)
    pack_into("<I", data, 20, 0xFFFFFFFF)
    with pytest.raises(FormatError, match="Truncated"):
        decode_dib(BitmapData("dib", bytes(data)))


@pytest.mark.parametrize("depth", (1, 4, 8, 16, 24, 32))
def test_all_depths_preserve_partial_band_storage_order(depth):
    colors = ((11, 22, 33), (44, 55, 66)) if depth <= 8 else ()
    source = encode_dib(1, 4, (0, 1, 0, 1), depth=depth, colors=colors)
    layout = read_dib(source)
    full = layout.decode()
    assert layout.decode(2).pixels == full.pixels[-6:]


@pytest.mark.parametrize("header", (12, 40, 108, 124))
def test_all_headers_check_pixel_budget_before_allocation(header):
    source = encode_dib(3, 2, (0,) * 6, depth=4, colors=((0, 0, 0),), header_size=header)
    with pytest.raises(FormatError, match="limit"):
        decode_dib(source, max_pixels=5)


@pytest.mark.parametrize("stretch_mode", (3, 4))
def test_rle_device_transfer_preserves_gaps_but_bitmap_realization_fills_them(stretch_mode):
    colors = ((11, 22, 33), (44, 55, 66))
    header = pack("<IiiHHIIiiII", 40, 3, 2, 1, 8, 1, 4, 0, 0, 2, 0)
    source = BitmapData("dib", header + bytes((33, 22, 11, 0, 66, 55, 44, 0, 1, 1, 0, 1)))
    context = RasterContext(6, 2, background=(0, 0, 255))
    context.set_stretch_mode(stretch_mode)
    context.set_dib_to_device(0, 0, 3, 2, 0, 0, 1, 1, 0, source)
    context.dib_bit_blt(3, 0, 3, 2, 0, 0, 0xCC0020, source)
    assert context.image.getpixel((0, 0)) == (0, 0, 255)
    assert context.image.getpixel((0, 1)) == colors[1]
    assert context.image.getpixel((1, 1)) == (0, 0, 255)
    gap_color = (0, 0, 255) if stretch_mode == 3 else colors[0]
    assert context.image.getpixel((3, 0)) == gap_color
    assert context.image.getpixel((3, 1)) == colors[1]
    assert context.image.getpixel((4, 1)) == gap_color


def test_fixup_scan_order_and_reflected_boundary_values_match_native_diagonal():
    bitmap = RGBBitmap(13, 7, bytes(v for y in range(7) for x in range(13) for v in (255 if x == y else 0,) * 3))
    result = fixup_bitmap(bitmap)
    assert [result.pixel(i, i)[0] for i in range(7)] == [191, 167, 143, 143, 143, 159, 191]
    assert all(result.pixel(x, y) == (0, 0, 0) for y in range(7) for x in range(13) if x != y)
    assert bitmap.pixel(0, 0) == (255, 255, 255)  # Original decision samples are immutable.


@pytest.mark.parametrize("width,height", ((1, 1), (1, 7), (7, 1)))
def test_fixup_does_not_invent_diagonals_in_one_dimensional_sources(width, height):
    bitmap = RGBBitmap(width, height, bytes((17, 31, 73)) * width * height)
    assert fixup_bitmap(bitmap) == bitmap


@pytest.mark.parametrize("operation", ("dib_bit_blt", "dib_stretch_blt", "stretch_dib"))
@pytest.mark.parametrize("canonical", (False, True))
def test_monochrome_realization_and_copy_dispatch_match_native(operation, canonical):
    colors = ((0, 0, 0), (255, 255, 255)) if canonical else ((1, 1, 1), (254, 254, 254))
    source = encode_dib(3, 3, (0, 1, 0, 1, 0, 1, 0, 1, 0), depth=1, colors=colors)
    context = RasterContext(3, 3)
    context.set_text_color(0x371953)
    context.set_background_color(0xB7D3E1)
    context.set_stretch_mode(4)
    if operation == "dib_bit_blt":
        context.dib_bit_blt(0, 0, 3, 3, 0, 0, 0xCC0020, source)
    else:
        args = {"source": source} | ({"color_usage": 0} if operation == "stretch_dib" else {})
        getattr(context, operation)(0, 0, 3, 3, 0, 0, 3, 3, 0xCC0020, **args)
    if canonical and operation == "dib_bit_blt":
        assert context.image.getpixel((0, 0)) == (83, 25, 55)
        assert context.image.getpixel((1, 0)) == (225, 211, 183)
    else:
        expected = (154, 118, 119) if canonical and operation == "dib_stretch_blt" else (128, 128, 128)
        assert set(context.image.get_flattened_data()) == {expected}


@pytest.mark.parametrize("depth", (1, 4, 8, 24))
@pytest.mark.parametrize("size", (7, 49))
def test_source_fixup_and_replication_are_separate_native_decisions(depth, size):
    colors = ((19, 59, 97), (90, 96, 210))
    bitmap = RGBBitmap(size, size, bytes(c for y in range(size) for x in range(size) for c in colors[(x + y) % 2]))
    assert classify_content(bitmap, 0, 0, size, size, depth=depth) == HalftoneContent(
        fixup=depth in (1, 4) or size == 7, replicate=True
    )
