"""Format adapters own wire conventions; drawing backends receive logical data."""

import ast
from pathlib import Path

import pytest

from pillow_wmf import (
    GDI,
    EncodedFaceName,
    EncodedText,
    FontCollection,
    FontRequest,
    GlyphIndices,
    InvalidOperation,
    Metafile,
    PaletteEntries,
    PaletteUpdate,
    RasterContext,
    Recorder,
    RegionGeometry,
    TraceContext,
    UnsupportedOperation,
    binary,
    play,
)
from pillow_wmf.clip import RegionMask
from pillow_wmf.constants import ETO_GLYPH_INDEX, ETO_PDY
from pillow_wmf.objects import BitmapData
from pillow_wmf.wmf import binary as legacy_binary
from pillow_wmf.wmf.objects import BitmapData as LegacyBitmapData
from pillow_wmf.wmf.objects import Font, Palette, Region, Scan
from pillow_wmf.wmf.variable import ExtTextOut


def test_shared_modules_do_not_depend_on_metafile_codecs():
    root = Path(__file__).resolve().parents[2] / "src" / "pillow_wmf"
    for path in root.glob("*.py"):
        if path.name in {"__init__.py", "plugin.py", "render.py"}:
            continue  # Public exports and format-facing entry points.
        for node in ast.walk(ast.parse(path.read_text())):
            imports = (
                [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else ([alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            )
            assert not any("wmf" in name.split(".") or "emf" in name.split(".") for name in imports), path


def test_shared_binary_and_bitmap_types_preserve_published_import_identity():
    for name in ("FormatError", "ResourceLimitError", "Limits", "Reader", "pack"):
        assert getattr(legacy_binary, name) is getattr(binary, name)
    assert LegacyBitmapData is BitmapData


def test_wire_objects_are_adapted_before_an_arbitrary_backend_sees_them():
    class Sink(GDI):
        def invoke(self, call):
            return call

    # Call construction is also the compatibility boundary for direct GDI users.
    sink = Sink()
    call = sink.create_font(Font(height=-15, face_name=b"Example"))
    assert call.kwargs["font"] == FontRequest(height=-15, face_name=EncodedFaceName(b"Example"))
    assert not hasattr(call.kwargs["font"], "to_bytes")


def test_logical_coordinates_are_not_limited_to_wmf_words():
    context = TraceContext()
    context.move_to(100_000, -100_000)
    context.create_font(FontRequest(height=-100_000, face_name="Example"))
    recorder = Recorder()
    for call in context.calls:
        with pytest.raises(ValueError):
            recorder.invoke(call)
    assert not recorder.calls and not recorder.records


def test_font_resolution_accepts_unicode_names_without_an_ansi_round_trip(face):
    fonts = FontCollection([face], aliases={"字体": face.family})
    assert fonts.resolve(FontRequest(face_name="字体")) is face
    recorder = Recorder()
    with pytest.raises(UnsupportedOperation, match="explicitly encoded"):
        recorder.create_font(FontRequest(face_name="字体"))
    assert not recorder.records


def test_wmf_region_conversion_owns_signed_words_and_null_creation():
    wire = Region((0, 0, 0, 0), (Scan(65534, 3, (65535, 4)),), declared_size=123)
    assert wire.to_gdi("create_region") == RegionGeometry(((-1, -2, 4, 3),))
    assert Region((0, 0, 0, 0), ()).to_gdi("create_region") is None
    dc = RasterContext(4, 4)
    empty = dc.create_region(RegionGeometry())
    failed = dc.create_region(None)
    assert not dc.is_null_object(empty)
    assert dc.is_null_object(failed)


def test_region_export_uses_sorted_disjoint_bands():
    geometry = RegionGeometry(((4, 4, -2, -2), (1, 1, 8, 6), (0, 0, 0, 0)))
    recorder = Recorder()
    recorder.create_region(geometry)
    wire = recorder.records[0].region
    replayed = wire.to_gdi("create_region")
    assert RegionMask.from_rectangles(replayed.rectangles) == RegionMask.from_rectangles(geometry.rectangles)
    assert len(wire.scans) == 3


def test_palette_creation_and_updates_have_distinct_logical_values():
    entries = ((1, 2, 3, 0),)
    assert Palette(entries=entries).to_gdi("create_palette") == PaletteEntries(entries)
    assert Palette(7, entries).to_gdi("set_palette_entries") == PaletteUpdate(7, entries)
    assert Palette(entries=entries, declared_count=2).to_gdi("create_palette") is None
    recorder = Recorder()
    recorder.create_palette(PaletteEntries(entries))
    recorder.set_palette_entries(PaletteUpdate(7, entries))
    assert recorder.records[0].palette.start == 0x300
    assert recorder.records[1].palette.start == 7


@pytest.mark.parametrize("options,advances", [(0, (5, 7)), (ETO_PDY, (5, 1, 7, -1))])
def test_glyph_advances_are_glyph_indexed_and_wmf_padding_stays_in_the_adapter(options, advances):
    recorder = Recorder()
    recorder.ext_text_out(2, 3, GlyphIndices((1, 2)), options, advances=advances)
    wire = recorder.records[0]
    assert wire.text == b"\x01\0\x02\0"
    assert wire.advances == advances + (0,) * len(advances)
    trace = TraceContext()
    play(Metafile.from_bytes(recorder.to_bytes()), trace, strict=True)
    assert trace.calls == recorder.calls


def test_raw_glyph_record_round_trip_preserves_unused_bytes_but_playback_normalizes():
    wire = ExtTextOut(2, 3, b"\x01\0x", ETO_GLYPH_INDEX, advances=(5, 17, 19))
    source = Metafile.build([wire]).to_bytes()
    parsed = Metafile.from_bytes(source)
    assert parsed.to_bytes() == source
    trace = TraceContext()
    play(parsed, trace, strict=True)
    assert trace.calls[0].kwargs["text"] == GlyphIndices((1,))
    assert trace.calls[0].kwargs["advances"] == (5,)


def test_encoded_text_keeps_bytes_for_selected_font_decoding():
    trace = TraceContext()
    trace.ext_text_out(1, 2, b"\x82\xa0A", advances=(3, 4, 5))
    assert trace.calls[0].kwargs["text"] == EncodedText(b"\x82\xa0A")
    assert trace.calls[0].kwargs["advances"] == (3, 4, 5)


def test_explicit_text_payload_rejects_conflicting_encoding_flags():
    trace = TraceContext()
    with pytest.raises(InvalidOperation, match="EncodedText"):
        trace.ext_text_out(0, 0, EncodedText(b"A"), ETO_GLYPH_INDEX)
    with pytest.raises(InvalidOperation, match="ext_text_out"):
        trace.text_out(0, 0, GlyphIndices((1,)))
    assert not trace.calls
