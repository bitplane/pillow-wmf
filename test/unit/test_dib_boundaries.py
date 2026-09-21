"""Extended formats have codec boundaries distinct from RGB-device acceptance."""

import runpy
from dataclasses import replace
from pathlib import Path
from struct import pack_into

import pytest
from PIL import Image

from pillow_wmf import FormatError, Metafile, RasterContext, Recorder, UnsupportedOperation, play
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


@pytest.mark.parametrize("name", BITMAPS)
@pytest.mark.parametrize("operation", ["stretch", "bitblt", "dibstretchblt", "device", "brush"])
def test_rgb_device_acceptance_and_following_drawing(name, operation):
    bitmap = BITMAPS[name]
    recorder = Recorder()
    recorder.select_object(recorder.create_brush(0, 0x0099CC, 0))
    if operation == "stretch":
        recorder.stretch_dib(1, 1, 3, 2, 0, 0, 3, 2, 0xCC0020, 0, bitmap)
    elif operation == "bitblt":
        recorder.dib_bit_blt(1, 1, 3, 2, 0, 0, 0xCC0020, bitmap)
    elif operation == "dibstretchblt":
        recorder.dib_stretch_blt(1, 1, 3, 2, 0, 0, 3, 2, 0xCC0020, bitmap)
    elif operation == "device":
        recorder.set_dib_to_device(1, 1, 3, 2, 0, 0, 0, 2, 0, bitmap)
    else:
        handle = recorder.create_dib_pattern_brush(5, 0, bitmap)
        recorder.select_object(handle)
        recorder.pat_blt(1, 1, 3, 2, 0xF00021)
        recorder.delete_object(handle)
        recorder.select_object(recorder.create_brush(0, 0xCC00CC, 0))
        recorder.pat_blt(1, 4, 3, 1, 0xF00021)
    recorder.set_pixel(7, 5, 0x00FF00)
    source = recorder.to_bytes()
    assert Metafile.from_bytes(source).to_bytes() == source
    background = (204, 153, 0)
    context = RasterContext(8, 6, background=background)
    assert play(recorder.metafile(), context, strict=True) == ()
    expected = Image.new("RGB", (8, 6), background)
    if not name.startswith(("jpeg", "png", "cmyk-")):
        rgb = read_dib(BITMAPS["rgb"]).decode()
        for y in range(1, 3):
            for x in range(1, 4):
                pixel = rgb.pixel(x % 3, y % 2) if operation == "brush" else rgb.pixel(x - 1, y - 1)
                expected.putpixel((x, y), pixel)
    if operation == "brush":
        expected.paste((204, 0, 204), (1, 4, 4, 5))
    expected.putpixel((7, 5), (0, 255, 0))
    assert context.image.tobytes() == expected.tobytes()


def test_extended_format_pixel_budget_remains_fatal():
    from pillow_wmf.wmf.binary import ResourceLimitError

    layout = read_dib(BITMAPS["png"])
    with pytest.raises(ResourceLimitError):
        read_dib(BitmapData("dib", layout.data), max_pixels=1)
    assert not replace(layout, data=layout.data[:40]).complete
