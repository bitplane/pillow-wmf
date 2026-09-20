"""Extended formats have codec boundaries distinct from RGB-device acceptance."""

import runpy
from dataclasses import replace
from pathlib import Path
from struct import pack_into

import pytest

from pillow_wmf import FormatError, Metafile, RasterContext, UnsupportedOperation, play
from pillow_wmf.bitmap import read_dib
from pillow_wmf.wmf.objects import BitmapData

CASES = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/dib_boundary_cases.py"))
BITMAPS = dict(CASES["bitmaps"]())


@pytest.mark.parametrize("name", ["jpeg", "png", "cmyk-32", "cmyk-8", "cmyk-4"])
def test_extended_compression_is_preserved_but_not_decoded_as_rgb(name):
    bitmap = BITMAPS[name]
    layout = read_dib(bitmap)
    assert layout.data == bitmap.data
    with pytest.raises(UnsupportedOperation, match="no RGB decoder"):
        layout.decode()


@pytest.mark.parametrize("compression", [4, 5])
def test_embedded_image_requires_the_documented_zero_bit_count(compression):
    data = bytearray(BITMAPS["rgb"].data)
    pack_into("<I", data, 16, compression)
    with pytest.raises(FormatError, match="depth/compression"):
        read_dib(BitmapData("dib", bytes(data)))


@pytest.mark.parametrize("name", ["srgb", "calibrated", "embedded", "linked"])
def test_icm_disabled_decode_never_follows_profile_fields(name):
    layout = read_dib(BITMAPS[name])
    assert layout.decode() == read_dib(BITMAPS["rgb"]).decode()
    data = bytearray(layout.data)
    pack_into("<II", data, 112, 0xFFFFFFFF, 0xFFFFFFFF)
    # These offsets cannot influence reads or allocations with ICM disabled.
    assert read_dib(BitmapData("dib", bytes(data))).decode() == layout.decode()


@pytest.mark.parametrize(
    "name,recorder", list(CASES["cases"]()), ids=lambda value: value if isinstance(value, str) else ""
)
def test_rgb_device_acceptance_and_following_drawing(name, recorder):
    source = recorder.to_bytes()
    assert Metafile.from_bytes(source).to_bytes() == source
    context = RasterContext(128, 128)
    assert play(recorder.metafile(), context, strict=True) == ()
    assert context.image.getpixel((120, 120)) == (0, 255, 0)
    if name.startswith(("jpeg-", "png-", "cmyk-")):
        assert context.image.getpixel((20, 20)) == (204, 153, 0)
    if name.endswith("brush"):
        assert context.image.getpixel((20, 95)) == (204, 0, 204)


def test_extended_format_pixel_budget_remains_fatal():
    from pillow_wmf.wmf.binary import ResourceLimitError

    layout = read_dib(BITMAPS["png"])
    with pytest.raises(ResourceLimitError):
        read_dib(BitmapData("dib", layout.data), max_pixels=1)
    assert not replace(layout, data=layout.data[:40]).complete
