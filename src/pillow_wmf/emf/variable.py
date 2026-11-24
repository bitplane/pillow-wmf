"""Variable-length vector, comment, palette, font, clipping and EOF records."""

import struct
from dataclasses import dataclass
from typing import ClassVar

from ..binary import FormatError, Limits, Reader, pack
from .constants import CommentIdentifier, RecordType
from .objects import LogFont, pack_palette_entries, read_palette_entries
from .records import ENVELOPE_SIZE, Record, register

Point = tuple[int, int]
Rect = tuple[int, int, int, int]


def read_points(reader: Reader, count: int, point_format: str, limits: Limits) -> tuple[Point, ...]:
    if count > limits.max_points or count > reader.remaining // struct.calcsize(point_format):
        raise FormatError("Invalid point count")
    return tuple(reader.unpack(point_format) for _ in range(count))


def pack_points(points, point_format: str) -> bytes:
    return b"".join(pack(point_format, *point) for point in points)


def alignment_padding(size: int, padding: bytes | None) -> bytes:
    expected = -size % 4
    result = bytes(expected) if padding is None else padding
    if len(result) != expected:
        raise ValueError("Padding must align the record to a DWORD")
    return result


def default_padding(padding: bytes) -> bytes | None:
    """None for the zero padding a writer would produce, else the exact bytes."""
    return None if not any(padding) else padding


@dataclass(frozen=True)
class PointsRecord(Record):
    """Bounds, a point count and points: MS-EMF 2.3.5 poly records."""

    bounds: Rect
    points: tuple[Point, ...]
    point_format: ClassVar[str] = "ii"

    def payload(self) -> bytes:
        return pack("4iI", *self.bounds, len(self.points)) + pack_points(self.points, self.point_format)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, count = reader.unpack("4iI")
        points = read_points(reader, count, cls.point_format, limits)
        return cls(tuple(bounds), points, trailing=reader.rest())


@dataclass(frozen=True)
class PolyPointsRecord(Record):
    """Bounds, per-figure counts and concatenated points."""

    bounds: Rect
    figures: tuple[tuple[Point, ...], ...]
    point_format: ClassVar[str] = "ii"

    def payload(self) -> bytes:
        counts = tuple(len(figure) for figure in self.figures)
        return (
            pack("4iII", *self.bounds, len(counts), sum(counts))
            + pack(f"{len(counts)}I", *counts)
            + b"".join(pack_points(figure, self.point_format) for figure in self.figures)
        )

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, count, total = reader.unpack("4iII")
        if count > limits.max_points or count > reader.remaining // 4:
            raise FormatError("Invalid figure count")
        counts = reader.unpack(f"{count}I")
        if sum(counts) != total:
            raise FormatError("Figure point counts disagree with the total")
        if total > limits.max_points or total > reader.remaining // struct.calcsize(cls.point_format):
            raise FormatError("Invalid point count")
        figures = tuple(read_points(reader, size, cls.point_format, limits) for size in counts)
        return cls(tuple(bounds), figures, trailing=reader.rest())


@dataclass(frozen=True)
class PolyDrawRecord(Record):
    """Bounds, points and one PT_* type byte per point, padded to a DWORD."""

    bounds: Rect
    points: tuple[Point, ...]
    types: bytes
    padding: bytes | None = None
    point_format: ClassVar[str] = "ii"

    def payload(self) -> bytes:
        if len(self.types) != len(self.points):
            raise ValueError("PolyDraw needs one type byte per point")
        return (
            pack("4iI", *self.bounds, len(self.points))
            + pack_points(self.points, self.point_format)
            + self.types
            + alignment_padding(len(self.points) * struct.calcsize(self.point_format) + len(self.types), self.padding)
        )

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, count = reader.unpack("4iI")
        size = struct.calcsize(cls.point_format)
        if count > limits.max_points or count > reader.remaining // (size + 1):
            raise FormatError("Invalid point count")
        points = read_points(reader, count, cls.point_format, limits)
        types = reader.take(count)
        padding = default_padding(reader.take(min(-count * (size + 1) % 4, reader.remaining)))
        return cls(tuple(bounds), points, types, padding, trailing=reader.rest())


def _poly(name, kind, base, point_format):
    cls = type(name, (base,), {"kind": kind, "point_format": point_format, "__module__": __name__})
    return register(dataclass(frozen=True)(cls))


PolyBezier = _poly("PolyBezier", RecordType.POLYBEZIER, PointsRecord, "ii")
Polygon = _poly("Polygon", RecordType.POLYGON, PointsRecord, "ii")
Polyline = _poly("Polyline", RecordType.POLYLINE, PointsRecord, "ii")
PolyBezierTo = _poly("PolyBezierTo", RecordType.POLYBEZIERTO, PointsRecord, "ii")
PolylineTo = _poly("PolylineTo", RecordType.POLYLINETO, PointsRecord, "ii")
PolyPolyline = _poly("PolyPolyline", RecordType.POLYPOLYLINE, PolyPointsRecord, "ii")
PolyPolygon = _poly("PolyPolygon", RecordType.POLYPOLYGON, PolyPointsRecord, "ii")
PolyDraw = _poly("PolyDraw", RecordType.POLYDRAW, PolyDrawRecord, "ii")
PolyBezier16 = _poly("PolyBezier16", RecordType.POLYBEZIER16, PointsRecord, "hh")
Polygon16 = _poly("Polygon16", RecordType.POLYGON16, PointsRecord, "hh")
Polyline16 = _poly("Polyline16", RecordType.POLYLINE16, PointsRecord, "hh")
PolyBezierTo16 = _poly("PolyBezierTo16", RecordType.POLYBEZIERTO16, PointsRecord, "hh")
PolylineTo16 = _poly("PolylineTo16", RecordType.POLYLINETO16, PointsRecord, "hh")
PolyPolyline16 = _poly("PolyPolyline16", RecordType.POLYPOLYLINE16, PolyPointsRecord, "hh")
PolyPolygon16 = _poly("PolyPolygon16", RecordType.POLYPOLYGON16, PolyPointsRecord, "hh")
PolyDraw16 = _poly("PolyDraw16", RecordType.POLYDRAW16, PolyDrawRecord, "hh")


@register
@dataclass(frozen=True)
class Comment(Record):
    """EMR_COMMENT. The payload, including any EMF+ records, stays opaque."""

    kind: ClassVar[RecordType] = RecordType.COMMENT
    data: bytes
    padding: bytes | None = None

    @property
    def identifier(self) -> int | None:
        return struct.unpack_from("<I", self.data)[0] if len(self.data) >= 4 else None

    @property
    def emf_plus(self) -> bool:
        return self.identifier == CommentIdentifier.EMFPLUS

    def payload(self) -> bytes:
        return pack("I", len(self.data)) + self.data + alignment_padding(len(self.data), self.padding)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        size = reader.unpack("I")[0]
        data = reader.take(size)
        padding = default_padding(reader.take(min(-size % 4, reader.remaining)))
        return cls(data, padding, trailing=reader.rest())


@register
@dataclass(frozen=True)
class ExtSelectClipRgn(Record):
    """Region mode and RegionData bytes (MS-EMF 2.2.24), kept undecoded."""

    kind: ClassVar[RecordType] = RecordType.EXTSELECTCLIPRGN
    mode: int
    region: bytes = b""

    def payload(self) -> bytes:
        return pack("II", len(self.region), self.mode) + self.region

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        size, mode = reader.unpack("II")
        return cls(mode, reader.take(size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class CreatePalette(Record):
    kind: ClassVar[RecordType] = RecordType.CREATEPALETTE
    object_index: int
    entries: tuple[tuple[int, int, int, int], ...] = ()
    version: int = 0x0300

    def payload(self) -> bytes:
        return pack("IHH", self.object_index, self.version, len(self.entries)) + pack_palette_entries(self.entries)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        object_index, version, count = reader.unpack("IHH")
        return cls(object_index, read_palette_entries(reader, count), version, trailing=reader.rest())


@register
@dataclass(frozen=True)
class SetPaletteEntries(Record):
    kind: ClassVar[RecordType] = RecordType.SETPALETTEENTRIES
    object_index: int
    start: int
    entries: tuple[tuple[int, int, int, int], ...] = ()

    def payload(self) -> bytes:
        return pack("III", self.object_index, self.start, len(self.entries)) + pack_palette_entries(self.entries)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        object_index, start, count = reader.unpack("III")
        return cls(object_index, start, read_palette_entries(reader, count), trailing=reader.rest())


@register
@dataclass(frozen=True)
class ExtCreateFontIndirectW(Record):
    """A LogFont followed by any LogFontEx, Panose or design-vector extension.

    The extension is kept as bytes: its layout depends on the record size and
    on a signature that only design-vector fonts carry (MS-EMF 2.3.7.8).
    """

    kind: ClassVar[RecordType] = RecordType.EXTCREATEFONTINDIRECTW
    object_index: int
    font: LogFont
    extension: bytes = b""

    def payload(self) -> bytes:
        return pack("I", self.object_index) + self.font.to_bytes() + self.extension

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        object_index = reader.unpack("I")[0]
        font = LogFont.read(reader)
        return cls(object_index, font, reader.rest())


EOF_PALETTE_OFFSET = 16


@register
@dataclass(frozen=True)
class Eof(Record):
    """EMR_EOF: an optional final palette and a copy of the record size.

    ``size_last`` of None means the actual record size; canonical output
    always writes the actual size.
    """

    kind: ClassVar[RecordType] = RecordType.EOF
    entries: tuple[tuple[int, int, int, int], ...] = ()
    palette_offset: int = EOF_PALETTE_OFFSET
    size_last: int | None = None

    def payload(self) -> bytes:
        return pack("II", len(self.entries), self.palette_offset) + pack_palette_entries(self.entries)

    def body(self, canonical: bool = False) -> bytes:
        body = self.payload() + self.trailing
        size_last = ENVELOPE_SIZE + len(body) + 4
        if not canonical and self.size_last is not None:
            size_last = self.size_last
        return body + pack("I", size_last)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        count, offset = reader.unpack("II")
        rest = reader.rest()
        if len(rest) < 4:
            raise FormatError("Missing final size field")
        middle, size_last = rest[:-4], struct.unpack("<I", rest[-4:])[0]
        start = offset - EOF_PALETTE_OFFSET
        if count and (start < 0 or count > (len(middle) - start) // 4):
            raise FormatError("Palette entries exceed record")
        entries = read_palette_entries(Reader(middle[start : start + 4 * count]), count) if count else ()
        if size_last == ENVELOPE_SIZE + 8 + len(middle) + 4:
            size_last = None
        # Entries away from their usual offset decode here, but the record
        # does not re-encode identically and therefore stays opaque.
        return cls(entries, offset, size_last, trailing=middle[4 * count :])
