from struct import pack

import pytest

from pillow_wmf import FormatError
from pillow_wmf.bitmap import RGBBitmap, decode_dib, encode_dib
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
