"""EMF boundary cases found in external corpora, as native playback draws them.

``corpus_boundaries.json`` holds the EMFs ``scripts/corpus_emf_cases.py``
builds and what ``probe-windows-corpus-boundaries.py`` observed when
PlayEnhMetaFile played them onto a 64x64 reference surface: whether playback
succeeded and, for pens and invalid records, the pixels (palette indexes from
the first non-white pixel of each row to the last).
"""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf.emf import Metafile, bitmaps, loader, play
from pillow_wmf.raster import RasterContext

CASES = json.loads(Path(__file__).with_name("corpus_boundaries.json").read_text())
PIXEL_CASES = [name for name in CASES if "rows" in CASES[name]]
IGNORED_FLAGS = [name for name in CASES if name.startswith("alpha-blend-flags-") and "-01-" not in name]


def played(data):
    dc = RasterContext(64, 64, trace_calls=False)
    omissions = play(loader.read(data), dc, rect=(0, 0, 64, 64))
    return dc.image, omissions


@pytest.mark.parametrize("name", PIXEL_CASES)
def test_cases_draw_as_natively(name):
    case = CASES[name]
    image, omissions = played(bytes.fromhex(case["emf"]))
    expected = {(x, y): 0xFFFFFF for y in range(64) for x in range(64)}
    for y, x0, row in case["rows"]:
        for i, index in enumerate(row):
            expected[x0 + i, y] = int(case["palette"][int(index)], 16)
    pixels = {(x, y): image.getpixel((x, y)) for y in range(64) for x in range(64)}
    drawn = {point: red << 16 | green << 8 | blue for point, (red, green, blue) in pixels.items()}
    assert drawn == expected
    # Native playback reports failure for a pen that cannot be created and
    # for an invalid record; both are omissions here.
    assert bool(omissions) != case["played"]


def test_zero_width_geometric_pens_are_solid_only():
    assert CASES["zero-width-pen-solid"]["played"] and CASES["zero-width-pen-flat-miter"]["played"]
    _, omissions = played(bytes.fromhex(CASES["zero-width-pen-dash"]["emf"]))
    assert "positive width" in omissions[0].reason


def test_invalid_record_size_stops_playback():
    data = bytes.fromhex(CASES["bad-record-huge-size"]["emf"])
    metafile = loader.read(data)
    assert metafile.stopped_at == 132 and len(metafile.records) == 1  # the first Rectangle
    with pytest.raises(ValueError, match="EOF"):
        metafile.to_bytes()
    with pytest.raises(Exception, match="Invalid record size at byte 132"):
        Metafile.from_bytes(data)


def without_flags(data):
    metafile = loader.read(data)
    records = tuple(
        replace(record, blend=record.blend & ~0xFF00) if isinstance(record, bitmaps.AlphaBlend) else record
        for record in metafile.records
    )
    return replace(metafile, records=records).to_bytes()


@pytest.mark.parametrize("name", IGNORED_FLAGS)
def test_blend_flags_other_than_bit_0_are_ignored(name):
    # Natively these draw exactly as the same blend with no flags.
    data = bytes.fromhex(CASES[name]["emf"])
    image, omissions = played(data)
    assert not omissions
    assert image.tobytes() == played(without_flags(data))[0].tobytes()


@pytest.mark.parametrize("name", [name for name in CASES if "-01-" in name])
def test_blend_flag_bit_0_is_an_omission(name):
    # Native blend arithmetic differs in the last bit at some alphas.
    _, omissions = played(bytes.fromhex(CASES[name]["emf"]))
    assert [omission.reason for omission in omissions] == ["AlphaBlend BlendFlags bit 0 arithmetic"]
