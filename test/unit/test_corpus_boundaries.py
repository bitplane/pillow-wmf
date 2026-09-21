"""Native malformed-input behavior without weakening byte/resource bounds."""

from dataclasses import replace
from pathlib import Path

import pytest

from pillow_wmf import FormatError, Limits, Metafile, PlaceableHeader, RasterContext, Recorder, play, render


def test_record_boundary_references_are_reproducible(load_script):
    cases = load_script("record_rejection_cases.py")
    programs = dict((*cases["corpus_cases"](), *cases["header_cases"](), *cases["palette_cases"]()))
    root = Path(__file__).parents[1] / "compatibility/wmf/record-boundaries"
    assert {p.stem for p in root.glob("*.wmf")} == {
        "negative-pen-3",
        "restore-invalid--2",
        "object-overflow",
        "background-transparent-0",
        "understated-size-0",
        "palette-count-65535",
        "fill-region-empty-slot",
    }
    for source in root.glob("*.wmf"):
        assert source.read_bytes() == programs[source.stem].to_bytes()


@pytest.mark.parametrize("mode", (0, 65535))
def test_nontransparent_background_values_remain_opaque_and_saved(mode):
    dc = RasterContext(16, 16)
    dc.set_background_mode(mode)
    dc.save_dc()
    dc.set_background_mode(1)
    dc.restore_dc(-1)
    assert dc._background_mode == mode
    dc.set_background_color(0x00FF00)
    dc.select_object(dc.create_brush(2, 255, 0))
    dc.pat_blt(0, 0, 16, 16, 0x00F00021)
    assert set(dc.image.get_flattened_data()) == {(255, 0, 0), (0, 255, 0)}


def test_negative_pen_width_normalizes_object_not_recorded_call():
    dc = RasterContext(16, 16)
    handle = dc.create_pen(0, -3, 255)
    assert dc._objects[handle].width == 3
    assert dc.calls[-1].kwargs["width"] == -3


def test_invalid_restore_preserves_the_valid_saved_frame(load_script):
    m = dict(load_script("record_rejection_cases.py")["corpus_cases"]())["restore-invalid--2"]
    dc = RasterContext(128, 128)
    assert play(m, dc, strict=True) == ()
    assert dc.image.getpixel((20, 20)) == (255, 0, 0)
    assert dc.image.getpixel((120, 120)) == (255, 0, 0)


@pytest.mark.parametrize("zero_units", (False, True))
def test_explicit_canvas_render_does_not_validate_unused_placeable_metadata(zero_units):
    recorder = Recorder()
    recorder.set_pixel(2, 3, 255)
    wrapper = bytearray(PlaceableHeader(0, 0, 100, 100).to_bytes())
    wrapper[20] ^= 1
    if zero_units:
        wrapper[14:16] = b"\0\0"
    source = bytes(wrapper) + recorder.to_bytes()
    with pytest.raises(FormatError):
        Metafile.from_bytes(source)
    assert render(source, (8, 8)).getpixel((2, 3)) == (255, 0, 0)
    with pytest.raises(FormatError, match="byte limit"):
        render(source, (8, 8), limits=Limits(max_bytes=len(source) - 1))


def test_understated_size_cannot_bypass_record_or_eof_bounds():
    m = Metafile.build([])
    data = replace(m, header=replace(m.header, size=0)).to_bytes()
    with pytest.raises(FormatError):
        Metafile.from_bytes(data[:-1])


def test_incomplete_palette_preserves_count_without_reading_next_record(load_script):
    source = dict(load_script("record_rejection_cases.py")["palette_cases"]())["palette-count-65535"].to_bytes()
    m = Metafile.from_bytes(source)
    assert m.to_bytes() == source
    palette = m.records[0].palette
    assert palette.declared_count == 65535
    assert len(palette.entries) == 2
    assert not palette.complete
    dc = RasterContext(128, 128)
    assert play(m, dc, strict=True) == ()
    assert dc.image.getpixel((20, 20)) == (128, 0, 0)
    assert dc.image.getpixel((120, 120)) == (255, 0, 0)
