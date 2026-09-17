from struct import unpack_from

import pytest

from pillow_wmf.bitmap import RGBBitmap, encode_dib24


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
