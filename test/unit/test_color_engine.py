"""Colourfulness, tint and illuminants in HALFTONE stretching.

``color_engine.json`` holds native output of ``probe-windows-color-engine.py``:

- ``colours``: the 32x32 ``colours`` source stretched 4x under each named
  COLORADJUSTMENT, as the RGB bytes of each source pixel's block, in
  source order. These enlargements replicate the mapped source.
- ``grey_cells``: rows of the red channel of the 256x256 ``grey-cells``
  source stretched 4x (and 2x, ``-x2``) under colourfulness 1, one byte
  per source pixel. These enlargements filter the mapped source; the
  first and last rows show the edge rows dithered as separate reads.
"""

import json
import struct
from pathlib import Path

import pytest

from pillow_wmf.color_engine import colour_map, cube_root, log10
from pillow_wmf.gdi import UnsupportedOperation
from pillow_wmf.objects import BitmapData
from pillow_wmf.raster import RasterContext

NATIVE = json.loads(Path(__file__).with_name("color_engine.json").read_text())
NEUTRAL = dict(flags=0, illuminant=0, rg=10000, gg=10000, bg=10000, black=0, white=10000)
NEUTRAL |= dict(contrast=0, brightness=0, colorfulness=0, tint=0)


@pytest.fixture
def probe(load_script):
    return load_script("probe-windows-color-engine.py")


def stretch(colours, side, scale, values):
    size = side * scale
    pixels = b"".join(bytes((b, g, r, 0)) for r, g, b in colours)
    info = struct.pack("<IiiHHIIiiII", 40, side, -side, 1, 32, 0, len(pixels), 0, 0, 0, 0)
    context = RasterContext(size, size, trace_calls=False)
    context.set_stretch_mode(4)
    v = values
    context.set_color_adjustment(
        v["flags"], v["illuminant"], v["rg"], v["gg"], v["bg"], v["black"], v["white"],
        v["contrast"], v["brightness"], v["colorfulness"], v["tint"],
    )  # fmt: skip
    context.stretch_dib(0, 0, size, size, 0, 0, side, side, 0xCC0020, 0, BitmapData("dib", info + pixels))
    image = context.image.convert("RGB")
    return lambda x, y: image.getpixel((x * scale + scale // 2, y * scale + scale // 2))


def cases(probe):
    return {name: values for source, name, values in probe["cases"]() if source in ("colours", "grey-cells")}


@pytest.mark.parametrize("name", sorted(NATIVE["colours"]))
def test_replicated_enlargements_match_native(probe, name):
    sample = stretch(probe["colours"](), 32, 4, cases(probe)[name])
    ours = bytes(v for i in range(1024) for v in sample(i % 32, i // 32))
    assert ours.hex() == NATIVE["colours"][name]


@pytest.mark.parametrize("name", sorted(NATIVE["grey_cells"]))
def test_filtered_enlargements_match_native(probe, name):
    scale = 2 if name.endswith("-x2") else 4
    sample = stretch(probe["grey_cells"](), 256, scale, cases(probe)[name])
    for row, expected in NATIVE["grey_cells"][name].items():
        assert bytes(sample(x, int(row))[0] for x in range(256)).hex() == expected, row


def test_fixed_point_logarithms_and_roots():
    assert log10(1_000_000) == 0 and log10(2_500_000) == 397_940 and log10(500_000) == -301_030
    assert cube_root(1_000_000) == 1_000_000 and cube_root(100_000) == 464_159 and cube_root(8857) == 206_901


def test_greys_keep_their_level_under_the_engine():
    table = colour_map(1, 0, 0)
    for level in range(32):
        entry = (level * (1 + 32 + 1024)) * 3
        assert table[entry : entry + 3] == bytes([round(level * 255 / 31)] * 3)


def test_reductions_under_the_engine_are_refused():
    info = struct.pack("<IiiHHIIiiII", 40, 4, -4, 1, 32, 0, 64, 0, 0, 0, 0)
    context = RasterContext(4, 4, trace_calls=False)
    context.set_stretch_mode(4)
    context.set_color_adjustment(0, 0, 10000, 10000, 10000, 0, 10000, 0, 0, 50, 0)
    with pytest.raises(UnsupportedOperation, match="colour engine"):
        context.stretch_dib(0, 0, 2, 2, 0, 0, 4, 4, 0xCC0020, 0, BitmapData("dib", info + bytes(64)))
