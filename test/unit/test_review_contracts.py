"""Small parser, public API and mapping invariants."""

import pytest

from pillow_wmf import Font, FontCollection, InvalidOperation, Limits, Metafile, Omission, RasterContext
from pillow_wmf.mapping import Mapping
from pillow_wmf.wmf.binary import Reader
from pillow_wmf.wmf.constants import RecordType
from pillow_wmf.wmf.records import RECORD_TYPES_BY_LOW_BYTE, FixedRecord


@pytest.mark.parametrize("data", [memoryview(b"large"), bytearray(b"large"), None])
def test_parser_checks_input_type_before_size(data):
    with pytest.raises(TypeError, match="immutable bytes"):
        Metafile.from_bytes(data, limits=Limits(max_bytes=0))


def test_record_low_bytes_are_unambiguous():
    assert len(RECORD_TYPES_BY_LOW_BYTE) == len(RecordType)


def test_fixed_record_layout_mismatch_is_not_silently_truncated():
    class BrokenRecord(FixedRecord):
        wire_layout = "HH"
        fields = ("one",)

    with pytest.raises(ValueError, match="zip"):
        BrokenRecord.read(Reader(b"\0" * 4), 1, Limits())


def test_public_font_configuration_and_diagnostics():
    assert issubclass(InvalidOperation, ValueError)
    assert Omission(1, 2, "reason").reason == "reason"
    with pytest.raises(ValueError, match="ANSI environment"):
        FontCollection(ansi_codepage=0)
    with pytest.raises(ValueError, match="Invalid default font"):
        FontCollection(default_font=Font(face_name=b"Missing"))


def test_offset_window_origin_changes_mapping_and_restores():
    dc = RasterContext(32, 32)
    dc.set_window_origin(2, 3)
    dc.save_dc()
    dc.offset_window_origin(-4, 5)
    assert dc.mapping.window_origin == (-2, 8)
    dc.set_pixel(1, 10, 255)
    assert dc.image.getpixel((3, 2)) == (255, 0, 0)
    dc.restore_dc(-1)
    assert dc.mapping.window_origin == (2, 3)


@pytest.mark.parametrize("viewport", [(100, 200), (200, 100)])
def test_isotropic_mapping_adjusts_the_oversized_axis(viewport):
    mapping = Mapping(mode=7, window_extent=(100, 100), viewport_extent=viewport)
    mapping._fix_isotropic()
    assert mapping.viewport_extent == (100, 100)
