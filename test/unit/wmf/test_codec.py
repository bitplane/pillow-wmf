import struct
from dataclasses import replace

import pytest

from pillow_wmf import FormatError, Limits, Metafile, PlaceableHeader
from pillow_wmf.wmf import RECORD_CLASSES, RecordType, UnknownRecord, bitmaps, fixed, variable
from pillow_wmf.wmf.binary import Reader
from pillow_wmf.wmf.objects import BitmapData, Font, Palette, Region, Scan
from pillow_wmf.wmf.records import FixedRecord

# Hand-specified file independent of the writer/schema: header, MoveTo(2,-3), EOF.
MINIMAL_LINE = bytes.fromhex("0100 0900 0003 11000000 0000 05000000 000005000000 1402 fdff 020003000000 0000")
DIB = BitmapData(
    "dib",
    bytes.fromhex("28000000 01000000 01000000 0100 1800 00000000 0400000000000000 00000000 00000000 00000000 0000ff00"),
)


def examples():
    for cls in RECORD_CLASSES.values():
        if issubclass(cls, FixedRecord):
            yield cls(**dict.fromkeys(cls.fields, 0))
    yield variable.Polygon(((1, -2), (3, 4)))
    yield variable.Polyline(((1, -2), (3, 4)))
    yield variable.PolyPolygon((((1, 2), (3, 4)), (), ((5, 6),)))
    yield variable.TextOut(10, -20, b"a\x00b", b"\xa5")
    yield variable.ExtTextOut(1, 2, b"abc", 6, (1, 2, 3, 4), (5, 6, 7), b"\xa5")
    yield variable.CreateFontIndirect(Font(height=-12, face_name=b"Example\0" + bytes(24)))
    yield variable.CreatePalette(Palette(entries=((255, 0, 0, 1),)))
    yield variable.AnimatePalette(Palette(0, ((0, 255, 0, 1),)))
    yield variable.SetPalEntries(Palette(0, ((0, 0, 255, 0),)))
    yield variable.CreateRegion(Region((0, 0, 10, 10), (Scan(0, 10, (0, 10)),)))
    yield variable.CreatePatternBrush(BitmapData("pattern16", bytes(34)))
    yield variable.DibCreatePatternBrush(5, 0, DIB)
    yield variable.Escape(0x7777, b"odd", b"\xa5")
    for cls in (bitmaps.BitBlt, bitmaps.DibBitBlt, bitmaps.StretchBlt, bitmaps.DibStretchBlt):
        yield cls(1, 2, 3, 4, 5, 6, 0x005A0049, reserved=0xABCD)
        source = DIB if cls.bitmap_format == "dib" else BitmapData("bitmap16", bytes(12))
        yield cls(1, 2, 3, 4, 5, 6, 0x00CC0020, source)
    yield bitmaps.SetDibToDev(1, 2, 3, 4, 5, 6, 0, 1, 0, DIB)
    yield bitmaps.StretchDib(1, 2, 3, 4, 5, 6, 7, 8, 0x00CC0020, 0, DIB)


CASES = tuple(examples())


def test_independent_input_and_output():
    parsed = Metafile.from_bytes(MINIMAL_LINE)
    move, eof = parsed.records
    assert isinstance(move, fixed.MoveTo)
    assert (move.x, move.y) == (2, -3)
    assert isinstance(eof, fixed.Eof)
    assert parsed.to_bytes() == MINIMAL_LINE
    assert Metafile.build([fixed.MoveTo(y=-3, x=2)]).to_bytes() == MINIMAL_LINE


def test_inventory_has_every_record_and_test_case():
    assert len(RecordType) == 70
    assert set(RECORD_CLASSES) == set(RecordType)
    assert {case.kind for case in CASES} == set(RecordType)


@pytest.mark.parametrize("record", CASES, ids=lambda record: type(record).__name__)
def test_record_round_trip(record):
    original = Metafile.build([record]).to_bytes()
    parsed = Metafile.from_bytes(original)
    assert type(parsed.records[0]) is type(record)
    assert parsed.records[0].payload() == record.payload()
    assert parsed.to_bytes() == original


@pytest.mark.parametrize("length", range(len(MINIMAL_LINE)))
def test_truncated_file_is_rejected(length):
    with pytest.raises(FormatError):
        Metafile.from_bytes(MINIMAL_LINE[:length])


@pytest.mark.parametrize("word_count", [0, 1, 2, 0xFFFFFFFF])
def test_invalid_record_length(word_count):
    bad = MINIMAL_LINE[:18] + struct.pack("<I", word_count) + MINIMAL_LINE[22:]
    with pytest.raises(FormatError, match="record size"):
        Metafile.from_bytes(bad)


def test_unknown_and_noncanonical_records_are_preserved():
    source = Metafile.build(
        [
            UnknownRecord(0xABFE, b"\xa5\x00"),
            fixed.MoveTo(y=-1, x=2, wire_function=0xFF14, trailing=b"\xad\xde"),
        ]
    )
    # build computes canonical accounting but ordinary output keeps wire words.
    data = source.to_bytes() + b"file trailer"
    parsed = Metafile.from_bytes(data)
    assert parsed.to_bytes() == data
    assert parsed.records[1].wire_function == 0xFF14
    assert parsed.records[1].trailing == b"\xad\xde"


def test_placeable_checksum_and_stream_size():
    file = Metafile.build([fixed.MoveTo(y=2, x=1)], placeable=PlaceableHeader(-10, -20, 100, 200))
    data = file.to_bytes()
    assert len(data) == file.header.size * 2 + 22
    assert Metafile.from_bytes(data).to_bytes() == data
    corrupted = data[:20] + bytes([data[20] ^ 1]) + data[21:]
    with pytest.raises(FormatError, match="checksum"):
        Metafile.from_bytes(corrupted)
    assert Metafile.from_bytes(corrupted, validate_checksum=False).to_bytes() == corrupted
    assert Metafile.from_bytes(corrupted, validate_checksum=False).to_bytes(canonical=True) == data


def test_canonical_output_recalculates_metadata_after_edit():
    file = Metafile.from_bytes(MINIMAL_LINE)
    edited = replace(file, records=(variable.TextOut(1, 2, b"longer text"), fixed.Eof()))
    canonical = edited.to_bytes(canonical=True)
    parsed = Metafile.from_bytes(canonical)
    assert parsed.header.size * 2 == len(canonical)
    assert parsed.header.max_record == len(parsed.records[0].to_bytes()) // 2


@pytest.mark.parametrize("limits", [Limits(max_bytes=1), Limits(max_records=1)])
def test_resource_limits(limits):
    with pytest.raises(FormatError, match="limit"):
        Metafile.from_bytes(MINIMAL_LINE, limits=limits)


def test_object_capacity_limit():
    file = Metafile.build([fixed.CreatePenIndirect(0, 1, 0, 0)])
    with pytest.raises(FormatError, match="capacity"):
        Metafile.from_bytes(file.to_bytes(), limits=Limits(max_objects=0))


def test_variable_count_exceeds_record():
    file = Metafile.build([UnknownRecord(RecordType.POLYGON, bytes.fromhex("ff7f"))])
    with pytest.raises(FormatError, match="point count"):
        Metafile.from_bytes(file.to_bytes())


def test_polygon_resource_limit():
    file = Metafile.build([variable.Polygon(((0, 0), (1, 1)))])
    with pytest.raises(FormatError, match="point count"):
        Metafile.from_bytes(file.to_bytes(), limits=Limits(max_points=1))


def test_scan_counts_must_match():
    with pytest.raises(FormatError, match="counts disagree"):
        Scan.read(Reader(bytes.fromhex("0200 0000 0100 0000 0100 0400")), Limits())


def test_missing_eof():
    data = bytearray(MINIMAL_LINE[:-6])
    struct.pack_into("<I", data, 6, len(data) // 2)
    with pytest.raises(FormatError, match="Missing EOF"):
        Metafile.from_bytes(bytes(data))


@pytest.mark.parametrize(
    "record", [fixed.MoveTo(32768, 0), UnknownRecord(0xFFFF, b"x"), variable.TextOut(0, 0, b"x", b"")]
)
def test_writer_rejects_unrepresentable_fields(record):
    with pytest.raises(ValueError):
        record.to_bytes()


def test_opaque_payloads_are_not_claimed_as_decoded_bitmaps():
    record = variable.DibCreatePatternBrush(5, 0, BitmapData("dib", b"\x00\x00"))
    parsed = Metafile.from_bytes(Metafile.build([record]).to_bytes())
    assert parsed.records[0].bitmap == BitmapData("dib", b"\x00\x00")


@pytest.mark.parametrize(
    ("record", "hex_bytes"),
    [
        (fixed.CreatePenIndirect(4, -2, 0, 0x00332211), "08000000 fa02 0400 feff 0000 11223300"),
        (fixed.CreateBrushIndirect(2, 0x00332211, 4), "07000000 fc02 0200 11223300 0400"),
        (fixed.Rectangle(bottom=4, right=3, top=2, left=1), "07000000 1b04 0400 0300 0200 0100"),
        (fixed.ScaleWindowExt(4, 3, 2, 1), "07000000 1004 0400 0300 0200 0100"),
        (variable.TextOut(1, -2, b"abc"), "08000000 2105 0300 61626300 feff 0100"),
        (variable.Polygon(((1, -2), (3, -4))), "08000000 2403 0200 0100 feff 0300 fcff"),
        (variable.Escape(0x7777, b"abc"), "07000000 2606 7777 0300 61626300"),
    ],
)
def test_independent_record_layouts(record, hex_bytes):
    assert record.to_bytes() == bytes.fromhex(hex_bytes)
    file = Metafile.build([record])
    # Substitute literal record bytes, rather than round-tripping our encoder.
    data = file.header.to_bytes() + bytes.fromhex(hex_bytes) + bytes.fromhex("03000000 0000")
    assert Metafile.from_bytes(data).records[0].payload() == record.payload()


@pytest.mark.parametrize(
    ("function", "payload"),
    [
        (0x0214, b""),  # MoveTo with no coordinates.
        (0x0521, bytes.fromhex("ffff")),  # Negative text length.
        (0x0521, bytes.fromhex("0300 6162")),  # Text overruns record.
        (0x0A32, bytes.fromhex("0000 0000 0000 0200")),  # Missing opaque rectangle.
        (0x0538, bytes.fromhex("0200 0100")),  # Missing polygon count.
        (0x00F7, bytes.fromhex("0003 0100")),  # Missing palette entry.
        (0x0626, bytes.fromhex("7777 ffff")),  # Escape exceeds envelope.
        (0x06FF, bytes(22)),  # Invalid region kind.
    ],
)
def test_malformed_record_payloads(function, payload):
    encoded = Metafile.build([UnknownRecord(function, payload)]).to_bytes()
    with pytest.raises(FormatError):
        Metafile.from_bytes(encoded)


@pytest.mark.parametrize("cls", [cls for cls in RECORD_CLASSES.values() if issubclass(cls, FixedRecord) and cls.fields])
def test_fixed_records_cannot_consume_the_next_record(cls):
    payload = cls(**dict.fromkeys(cls.fields, 0)).payload()[:-2]
    encoded = Metafile.build([UnknownRecord(cls.kind, payload), fixed.MoveTo(1, 2)]).to_bytes()
    with pytest.raises(FormatError, match="Truncated"):
        Metafile.from_bytes(encoded)
