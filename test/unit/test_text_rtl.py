"""Native RTL layout keeps glyphs readable while mirroring reference edges."""

import runpy
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FontCollection, FontFace, Metafile, RasterContext, play

PROBE = runpy.run_path(str(Path(__file__).parents[2] / "scripts/text_option_cases.py"))


@pytest.mark.parametrize(
    "name,position",
    [
        ("left", (104, 65)),
        ("right", (-14, 65)),
        ("center", (45, 65)),
        ("opaque", (104, 65)),
        ("quarter", (45, 6)),
        ("angle", (97, 35)),
        ("fractional", (104, 64)),
        ("pdy", (104, 78)),
        ("pdy-right", (-14, 52)),
        ("pdy-center", (45, 65)),
    ],
)
def test_native_rtl_current_position(name, position):
    recorder = dict(PROBE["rtl_cases"]())[f"rtl-{name}"]
    metafile = Metafile.from_bytes(recorder.to_bytes())
    # Omit the following LineTo and marker to inspect the text's own update.
    metafile = replace(metafile, records=metafile.records[:-3])
    fonts = FontCollection([FontFace.from_path(PROBE["FONT_PATH"])])
    dc = RasterContext(*PROBE["SIZE"], fonts=fonts)
    assert play(metafile, dc, strict=True) == ()
    # GetCurrentPositionEx exposes integer logical coordinates. The renderer
    # retains the fractional inverse mapping for subsequent device placement.
    assert tuple(int(value) for value in dc._position) == position
