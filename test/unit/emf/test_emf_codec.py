import contextlib
import random
import struct
from dataclasses import replace

import pytest

from pillow_wmf.emf import (
    RECORD_CLASSES,
    FormatError,
    Header,
    Limits,
    LogFont,
    Metafile,
    RecordType,
    UnknownRecord,
    accepts,
    bitmaps,
    fixed,
    text,
    variable,
)
from pillow_wmf.mapping import ReferenceDevice

# Hand-specified file independent of the writer: an 88-byte header without
# extensions, MoveToEx(2, -3) and EOF.
BASE_HEADER = bytes.fromhex(
    "01000000 58000000"
    "00000000 00000000 09000000 09000000"  # bounds
    "00000000 00000000 64000000 64000000"  # frame
    "20454d46 00000100 7c000000 03000000 0100 0000"  # signature, version, bytes, records, handles
    "00000000 00000000 00000000"  # description count/offset, palette entries
    "00040000 00030000 0f010000 cb000000"  # 1024x768 pixels, 271x203 mm
)
MOVE = bytes.fromhex("1b000000 10000000 02000000 fdffffff")
EOF = bytes.fromhex("0e000000 14000000 00000000 10000000 14000000")
MINIMAL_MOVE = BASE_HEADER + MOVE + EOF

# The same picture as Metafile.build writes it: both header extensions,
# micrometres 271000 x 203000.
BUILT_MOVE = (
    bytes.fromhex("01000000 6c000000")
    + BASE_HEADER[8:48]
    + bytes.fromhex("90000000")
    + BASE_HEADER[52:]
    + bytes.fromhex("00000000 00000000 00000000 98220400 f8180300")
    + MOVE
    + EOF
)

DIB = bytes.fromhex("28000000 01000000 01000000 0100 1800 00000000 04000000 00000000 00000000 00000000 00000000")
PIXEL = bytes.fromhex("0000ff00")


def blit_source(data_offset):
    """Offsets for a BitmapInfo immediately followed by its bits."""
    return {
        "bitmap_offset": data_offset,
        "bitmap_size": len(DIB),
        "bits_offset": data_offset + len(DIB),
        "bits_size": len(PIXEL),
        "data": DIB + PIXEL,
    }


def zeroed(cls, **values):
    return cls(**(dict.fromkeys(cls.fields, 0) | values))


def examples():
    for name, *_ in fixed.TABLE:
        yield zeroed(getattr(fixed, name))
    for name, *_ in bitmaps.TABLE:
        cls = getattr(bitmaps, name)
        offset = 8 + struct.calcsize("<" + cls.wire_layout)
        yield zeroed(cls, **blit_source(offset))
    yield bitmaps.ExtCreatePen(1, 0, 0, 0, 0, 0x10000, 3, 0, 0xFF, 0, (2, 4))
    yield bitmaps.ExtCreatePen(2, 52, len(DIB), 52 + len(DIB), 4, 0x10000, 1, 3, 0, 0, (), DIB + PIXEL)
    for poly in (variable.PolyBezier, variable.Polygon, variable.Polyline, variable.PolyBezierTo, variable.PolylineTo):
        yield poly((1, 2, 3, 4), ((1, -2), (3, 4)))
    for poly in (variable.PolyBezier16, variable.Polygon16, variable.Polyline16):
        yield poly((1, 2, 3, 4), ((1, -2), (3, 4)))
    for poly in (variable.PolyBezierTo16, variable.PolylineTo16):
        yield poly((1, 2, 3, 4), ((1, -2),))
    for poly in (variable.PolyPolyline, variable.PolyPolygon, variable.PolyPolyline16, variable.PolyPolygon16):
        yield poly((0, 0, 6, 6), (((1, 2), (3, 4)), (), ((5, 6),)))
    yield variable.PolyDraw((0, 0, 1, 1), ((0, 0), (1, 1), (2, 2)), b"\x06\x02\x03")
    yield variable.PolyDraw16((0, 0, 1, 1), ((0, 0),), b"\x06", b"\xa5\x00\x5a")
    yield variable.Comment(b"EMF+\x01\x40\x01\x00")
    yield variable.Comment(b"odd", b"\xa5")
    yield variable.ExtSelectClipRgn(5, bytes(32))
    yield variable.CreatePalette(1, ((255, 0, 0, 1),))
    yield variable.SetPaletteEntries(1, 4, ((0, 255, 0, 0), (0, 0, 255, 0)))
    yield variable.ExtCreateFontIndirectW(
        3, LogFont(height=-12, face_name="Arial".encode("utf-16-le").ljust(64, b"\0"))
    )
    yield variable.ExtCreateFontIndirectW(4, LogFont(), bytes(228))
    yield text.ExtTextOutW(
        (0, 0, 9, 9), 1, 1.5, 2.0, 3, 4, 2, 76, 6, (1, 2, 3, 4), 80, "hi".encode("utf-16-le") + bytes(8)
    )
    yield variable.Eof(((1, 2, 3, 0),))
    yield text.ExtTextOutA((0, 0, 9, 9), 1, 0.0, 0.0, 3, 4, 3, 60, 0x0100, None, 64, b"abc\0" + bytes(12))


CASES = tuple(examples())

# Record types deliberately left opaque: their payloads stay UnknownRecord bytes.
OPAQUE = {
    RecordType.HEADER,  # Always decoded as the Metafile header instead.
    RecordType.FILLRGN,
    RecordType.FRAMERGN,
    RecordType.INVERTRGN,
    RecordType.PAINTRGN,
    RecordType.MASKBLT,
    RecordType.PLGBLT,
    RecordType.POLYTEXTOUTA,
    RecordType.POLYTEXTOUTW,
    RecordType.CREATECOLORSPACE,
    RecordType.CREATECOLORSPACEW,
    RecordType.GLSRECORD,
    RecordType.GLSBOUNDEDRECORD,
    RecordType.PIXELFORMAT,
    RecordType.DRAWESCAPE,
    RecordType.EXTESCAPE,
    RecordType.SMALLTEXTOUT,
    RecordType.NAMEDESCAPE,
    RecordType.SETICMPROFILEA,
    RecordType.SETICMPROFILEW,
    RecordType.ALPHABLEND,
    RecordType.TRANSPARENTBLT,
    RecordType.GRADIENTFILL,
    RecordType.SETLINKEDUFIS,
    RecordType.COLORMATCHTOTARGETW,
}


def test_independent_input_and_output():
    parsed = Metafile.from_bytes(MINIMAL_MOVE)
    move, eof = parsed.records
    assert move == fixed.MoveToEx(2, -3)
    assert isinstance(eof, variable.Eof)
    assert parsed.header.bounds == (0, 0, 9, 9)
    assert parsed.header.frame == (0, 0, 100, 100)
    assert parsed.header.micrometres is None
    assert parsed.to_bytes() == MINIMAL_MOVE
    assert parsed.to_bytes(canonical=True) == MINIMAL_MOVE


def test_build_writes_both_header_extensions():
    built = Metafile.build([fixed.MoveToEx(2, -3)], bounds=(0, 0, 9, 9), frame=(0, 0, 100, 100))
    assert built.to_bytes() == BUILT_MOVE
    assert built.header.micrometres == (271000, 203000)
    assert built.header.pixel_format_size == 0
    assert Metafile.from_bytes(BUILT_MOVE) == built


def test_accepts():
    assert accepts(MINIMAL_MOVE[:44])
    assert not accepts(MINIMAL_MOVE[:43])
    assert not accepts(MINIMAL_MOVE[:40] + b"WMF ")


def test_inventory_has_every_record_and_test_case():
    assert len(RecordType) == 119
    assert set(RECORD_CLASSES) == set(RecordType) - OPAQUE
    assert {case.kind for case in CASES} == set(RECORD_CLASSES)


@pytest.mark.parametrize("record", CASES, ids=lambda record: type(record).__name__)
def test_record_round_trip(record):
    original = Metafile.build([record]).to_bytes()
    parsed = Metafile.from_bytes(original)
    assert parsed.records[0] == record
    assert parsed.to_bytes() == original
    assert parsed.to_bytes(canonical=True) == original


@pytest.mark.parametrize(
    ("record", "hex_bytes"),
    [
        (fixed.SetMapMode(8), "11000000 0c000000 08000000"),
        (fixed.Rectangle(1, 2, 3, 4), "2b000000 18000000 01000000 02000000 03000000 04000000"),
        (fixed.CreatePen(1, 0, 2, 0, 0x00332211), "26000000 1c000000 01000000 00000000 02000000 00000000 11223300"),
        (
            fixed.SetWorldTransform(1.0, 0.0, 0.0, -1.0, 0.5, 2.0),
            "23000000 20000000 0000803f 00000000 00000000 000080bf 0000003f 00000040",
        ),
        (
            variable.Polygon16((0, 0, 3, 4), ((1, -2), (3, 4))),
            "56000000 24000000 00000000 00000000 03000000 04000000 02000000 0100feff 03000400",
        ),
        (variable.Comment(b"abcde"), "46000000 14000000 05000000 61626364 65000000"),
    ],
)
def test_independent_record_layouts(record, hex_bytes):
    data = bytes.fromhex(hex_bytes)
    assert record.to_bytes() == data
    parsed = Metafile.from_bytes(BASE_HEADER + data + EOF)
    assert parsed.records[0] == record


@pytest.mark.parametrize("length", range(len(MINIMAL_MOVE)))
def test_truncated_file_is_rejected(length):
    with pytest.raises(FormatError):
        Metafile.from_bytes(MINIMAL_MOVE[:length])


@pytest.mark.parametrize("size", [0, 4, 7, 10, 18, 20, 0xFFFFFFFF])
def test_invalid_record_size(size):
    bad = BASE_HEADER + MOVE[:4] + struct.pack("<I", size) + MOVE[8:] + EOF
    with pytest.raises(FormatError, match="record size"):
        Metafile.from_bytes(bad)


@pytest.mark.parametrize(
    "header",
    [
        BASE_HEADER[:40] + b"WMF " + BASE_HEADER[44:],  # Signature.
        b"\x02" + BASE_HEADER[1:],  # Record type.
        BASE_HEADER[:4] + struct.pack("<I", 84) + BASE_HEADER[8:],  # Shorter than the header object.
        BASE_HEADER[:4] + struct.pack("<I", 90) + BASE_HEADER[8:],  # Not DWORD-aligned.
    ],
)
def test_invalid_header(header):
    with pytest.raises(FormatError):
        Metafile.from_bytes(header + MOVE + EOF)


def test_missing_eof():
    with pytest.raises(FormatError, match="Missing EOF"):
        Metafile.from_bytes(BASE_HEADER + MOVE)


def test_unknown_records_trailing_fields_and_file_trailer_are_preserved():
    data = (
        BASE_HEADER
        + UnknownRecord(0xABCD, b"\xa5\x5a\x00\x01").to_bytes()
        + fixed.MoveToEx(2, -3, trailing=b"\xad\xde\xef\xbe").to_bytes()
        + EOF
        + b"file trailer"
    )
    parsed = Metafile.from_bytes(data)
    assert parsed.records[0] == UnknownRecord(0xABCD, b"\xa5\x5a\x00\x01")
    assert parsed.records[1].trailing == b"\xad\xde\xef\xbe"
    assert parsed.trailing == b"file trailer"
    assert parsed.to_bytes() == data


def test_eof_palette_offsets():
    # Producers write 0 as well as 16 when there is no palette.
    plain = Metafile.from_bytes(BASE_HEADER + MOVE + bytes.fromhex("0e000000 14000000 00000000 00000000 14000000"))
    assert plain.records[-1] == variable.Eof(palette_offset=0)
    assert Metafile.from_bytes(MINIMAL_MOVE[:-4] + b"\x01\0\0\0").records[-1].size_last == 1
    # Entries after a gap decode only as opaque bytes, but still end the file.
    gapped = bytes.fromhex("0e000000 1c000000 01000000 14000000 00000000 11223300 1c000000")
    parsed = Metafile.from_bytes(BASE_HEADER + gapped + b"tail")
    assert parsed.records == (UnknownRecord(RecordType.EOF, gapped[8:]),)
    assert parsed.trailing == b"tail"
    assert Metafile.from_bytes(parsed.to_bytes(canonical=True)).header.palette_count == 1
    with pytest.raises(FormatError, match="exceed"):
        Metafile.from_bytes(BASE_HEADER + bytes.fromhex("0e000000 14000000 01000000 10000000 14000000"))


def test_canonical_output_recalculates_accounting():
    palette = ((1, 2, 3, 0), (4, 5, 6, 0))
    source = Metafile.build(
        [
            fixed.CreatePen(7, 0, 1, 0, 0),
            UnknownRecord(RecordType.CREATECOLORSPACEW, struct.pack("<I", 9) + bytes(4)),
            variable.Eof(palette, size_last=1),
        ],
        description="App\0Picture\0\0",
    )
    stale = replace(source, header=replace(source.header, size=1, record_count=1, handle_count=1, palette_count=0))
    assert stale.to_bytes() != source.to_bytes()
    canonical = Metafile.from_bytes(stale.to_bytes(canonical=True))
    assert canonical.header.size == len(stale.to_bytes(canonical=True))
    assert canonical.header.record_count == 4
    assert canonical.header.handle_count == 10
    assert canonical.header.palette_count == 2
    assert canonical.records[-1].size_last is None  # The actual record size.
    assert canonical.records[-1].to_bytes()[-4:] == struct.pack("<I", 28)
    assert canonical.header.description == "App\0Picture\0\0"
    assert canonical.header.description_offset == 108


def test_header_extensions_follow_declared_offsets():
    header = Header.create((0, 0, 1, 1), (0, 0, 10, 10), device=ReferenceDevice((800, 600), (200, 150)))
    assert (header.device, header.millimetres, header.micrometres) == ((800, 600), (200, 150), (200000, 150000))
    # A description that starts inside the would-be extensions displaces them.
    early = replace(header, description_length=2, description_offset=96, extra=bytes(8) + "hi".encode("utf-16-le"))
    assert early.description == "hi"
    assert early.pixel_format_size is None
    assert early.micrometres is None
    # Offsets outside the record are reported as absent, not read.
    assert replace(header, description_length=4, description_offset=0xFFFF).description is None


def test_writer_validates_eof_placement():
    file = Metafile.build([fixed.SaveDC()])
    with pytest.raises(ValueError, match="end with EOF"):
        replace(file, records=file.records[:-1]).to_bytes()
    with pytest.raises(ValueError, match="EOF must be the last"):
        replace(file, records=(variable.Eof(), *file.records)).to_bytes()


@pytest.mark.parametrize(
    "record",
    [
        fixed.MoveToEx(2**31, 0),
        UnknownRecord(1, b"abc"),
        variable.Comment(b"abc", b""),
        variable.PolyDraw((0, 0, 0, 0), ((0, 0),), b""),
        text.ExtTextOutW((0, 0, 0, 0), 1, 1.0, 1.0, 0, 0, 0, 0, 0x0100, (0, 0, 0, 0), 0),
        variable.ExtCreateFontIndirectW(1, LogFont(face_name=b"short")),
    ],
)
def test_writer_rejects_unrepresentable_fields(record):
    with pytest.raises(ValueError):
        record.to_bytes()


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (Limits(max_bytes=1), "byte limit"),
        (Limits(max_records=1), "Record count limit"),
        (Limits(max_objects=0), "capacity"),
        (Limits(max_points=1), "point count"),
    ],
)
def test_resource_limits(limits, message):
    data = Metafile.build([variable.Polyline((0, 0, 1, 1), ((0, 0), (1, 1)))]).to_bytes()
    with pytest.raises(FormatError, match=message):
        Metafile.from_bytes(data, limits=limits)


@pytest.mark.parametrize(
    ("kind", "payload", "message"),
    [
        (RecordType.POLYLINE, struct.pack("<4iI", 0, 0, 0, 0, 2) + bytes(8), "point count"),
        (RecordType.POLYPOLYGON, struct.pack("<4iII", 0, 0, 0, 0, 1, 3) + struct.pack("<I", 2) + bytes(16), "disagree"),
        (RecordType.POLYPOLYGON, struct.pack("<4iII", 0, 0, 0, 0, 0xFFFFFFFF, 0), "figure count"),
        (RecordType.COMMENT, struct.pack("<I", 8) + bytes(4), "Truncated"),
        (RecordType.EXTSELECTCLIPRGN, struct.pack("<II", 32, 5), "Truncated"),
        (RecordType.CREATEPALETTE, struct.pack("<IHH", 1, 0x300, 2) + bytes(4), "palette entry count"),
        (RecordType.EXTCREATEPEN, struct.pack("<11I", *range(10), 9), "Style entries"),
        (RecordType.MOVETOEX, bytes(4), "Truncated"),
    ],
)
def test_malformed_record_payloads(kind, payload, message):
    data = BASE_HEADER + struct.pack("<II", kind, 8 + len(payload)) + payload + EOF
    with pytest.raises(FormatError, match=message):
        Metafile.from_bytes(data)


def test_comment_identifies_emf_plus_without_decoding_it():
    assert variable.Comment(b"EMF+" + bytes(12)).emf_plus
    assert variable.Comment(b"GDIC" + bytes(4)).identifier == 0x43494447
    assert variable.Comment(b"EM").identifier is None


def test_offset_addressed_data():
    blit = next(case for case in CASES if isinstance(case, bitmaps.StretchDIBits))
    assert (blit.bitmap_info, blit.bits) == (DIB, PIXEL)
    with pytest.raises(FormatError, match="outside the record"):
        _ = replace(blit, bits_offset=blit.bits_offset + 1).bits
    wide = next(case for case in CASES if isinstance(case, text.ExtTextOutW))
    assert wide.text.decode("utf-16-le") == "hi"
    assert wide.advances == (0, 0)
    narrow = next(case for case in CASES if isinstance(case, text.ExtTextOutA))
    assert narrow.data_offset() == 60
    assert narrow.text == b"abc"
    pen = next(case for case in CASES if isinstance(case, bitmaps.ExtCreatePen) and case.data)
    assert pen.data_offset() == 52
    assert (pen.bitmap_info, pen.bits) == (DIB, PIXEL)


def test_log_font_face():
    font = LogFont(face_name="Arial\0junk".encode("utf-16-le").ljust(64, b"\0"))
    assert font.face == "Arial"


def mutations(data: bytes, rng: random.Random, count: int):
    for _ in range(count):
        mutated = bytearray(data)
        for _ in range(rng.randint(1, 8)):
            position = rng.randrange(len(mutated))
            choice = rng.random()
            if choice < 0.6:
                mutated[position] = rng.randrange(256)
            elif choice < 0.8:
                struct.pack_into("<I", mutated, position & ~3, rng.choice((0, 4, 8, 0x7FFFFFFF, 0xFFFFFFFF)))
            else:
                del mutated[position:]
                break
        yield bytes(mutated)


def test_mutated_files_round_trip_or_raise_format_error():
    # Every accepted input must reproduce exactly; everything else must fail
    # as FormatError, never as another exception.
    seed = Metafile.build([case for case in CASES if not isinstance(case, variable.Eof)]).to_bytes()
    accepted = 0
    for data in mutations(seed, random.Random(0xE3F), 3000):
        try:
            parsed = Metafile.from_bytes(data, limits=Limits(max_points=4096, max_records=4096))
        except FormatError:
            continue
        accepted += 1
        assert parsed.to_bytes() == data
        # Canonical accounting may not fit its field, such as a handle beyond 65535.
        with contextlib.suppress(ValueError):
            parsed.to_bytes(canonical=True)
    assert accepted > 100
