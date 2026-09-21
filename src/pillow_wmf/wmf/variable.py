"""Variable-length vector, text, object and escape records."""

from dataclasses import dataclass
from typing import ClassVar

from .binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .objects import BitmapData, Font, Palette, Region
from .records import Record, register


def read_points(reader: Reader, count: int, limits: Limits) -> tuple[tuple[int, int], ...]:
    if count < 0 or count > limits.max_points or count > reader.remaining // 4:
        raise FormatError("Invalid point count")
    return tuple(reader.unpack("hh") for _ in range(count))


@dataclass(frozen=True)
class PointsRecord(Record):
    points: tuple[tuple[int, int], ...]

    def payload(self) -> bytes:
        return pack("h", len(self.points)) + b"".join(pack("hh", *point) for point in self.points)

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        count = reader.unpack("h")[0]
        points = read_points(reader, count, limits)
        return cls(points, wire_function=function, trailing=reader.rest())


@register
class Polygon(PointsRecord):
    kind = RecordType.POLYGON


@register
class Polyline(PointsRecord):
    kind = RecordType.POLYLINE


@register
@dataclass(frozen=True)
class PolyPolygon(Record):
    kind: ClassVar[RecordType] = RecordType.POLYPOLYGON
    polygons: tuple[tuple[tuple[int, int], ...], ...]

    def payload(self) -> bytes:
        return (
            pack("H", len(self.polygons))
            + b"".join(pack("H", len(p)) for p in self.polygons)
            + b"".join(pack("hh", *point) for polygon in self.polygons for point in polygon)
        )

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        count = reader.unpack("H")[0]
        if count > limits.max_points or count > reader.remaining // 2:
            raise FormatError("Invalid polygon count")
        sizes = reader.unpack("H" * count)
        if sum(sizes) > limits.max_points:
            raise FormatError("Point limit exceeded")
        polygons = tuple(read_points(reader, size, limits) for size in sizes)
        return cls(polygons, wire_function=function, trailing=reader.rest())


def text_padding(text: bytes, padding: bytes | None) -> bytes:
    expected = len(text) % 2
    result = bytes(expected) if padding is None else padding
    if len(result) != expected:
        raise ValueError("Text padding must align the string to a word")
    return result


@register
@dataclass(frozen=True)
class TextOut(Record):
    kind: ClassVar[RecordType] = RecordType.TEXTOUT
    x: int
    y: int
    text: bytes
    padding: bytes | None = None

    def payload(self) -> bytes:
        return (
            pack("h", len(self.text)) + self.text + text_padding(self.text, self.padding) + pack("hh", self.y, self.x)
        )

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        count = reader.unpack("h")[0]
        text = reader.take(count)
        padding = reader.take(count % 2)
        y, x = reader.unpack("hh")
        return cls(x, y, text, padding, wire_function=function, trailing=reader.rest())


@register
@dataclass(frozen=True)
class ExtTextOut(Record):
    kind: ClassVar[RecordType] = RecordType.EXTTEXTOUT
    x: int
    y: int
    text: bytes
    options: int = 0
    rectangle: tuple[int, int, int, int] | None = None
    advances: tuple[int, ...] = ()
    padding: bytes | None = None

    def payload(self) -> bytes:
        if bool(self.options & 6) != (self.rectangle is not None):
            raise ValueError("Text rectangle is required exactly when OPAQUE or CLIPPED is set")
        # Preserve raw advances. Their relationship to bytes/glyphs depends on
        # charset and flags; do not infer a Unicode character count here.
        result = pack("hhhH", self.y, self.x, len(self.text), self.options)
        if self.rectangle is not None:
            result += pack("4h", *self.rectangle)
        return (
            result + self.text + text_padding(self.text, self.padding) + pack("h" * len(self.advances), *self.advances)
        )

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        y, x, count, options = reader.unpack("hhhH")
        rectangle = reader.unpack("4h") if options & 6 else None
        text = reader.take(count)
        padding = reader.take(count % 2)
        if reader.remaining // 2 > limits.max_points:
            raise FormatError("Text advance limit exceeded")
        advances = reader.unpack("h" * (reader.remaining // 2))
        return cls(x, y, text, options, rectangle, advances, padding, wire_function=function, trailing=reader.rest())


@register
@dataclass(frozen=True)
class CreateFontIndirect(Record):
    kind: ClassVar[RecordType] = RecordType.CREATEFONTINDIRECT
    font: Font

    def payload(self) -> bytes:
        return self.font.to_bytes()

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        font = Font.read(reader)
        return cls(font, wire_function=function, trailing=reader.rest())


@dataclass(frozen=True)
class PaletteRecord(Record):
    palette: Palette

    def payload(self) -> bytes:
        if self.kind == RecordType.CREATEPALETTE and self.palette.start != 0x0300:
            raise ValueError("New palettes require start/version 0x0300")
        return self.palette.to_bytes()

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        palette = Palette.read(reader, limits, allow_incomplete=cls.kind == RecordType.CREATEPALETTE)
        if cls.kind == RecordType.CREATEPALETTE and palette.start != 0x0300:
            raise FormatError("New palettes require start/version 0x0300")
        return cls(palette, wire_function=function, trailing=reader.rest())


@register
class CreatePalette(PaletteRecord):
    kind = RecordType.CREATEPALETTE


@register
class AnimatePalette(PaletteRecord):
    kind = RecordType.ANIMATEPALETTE


@register
class SetPalEntries(PaletteRecord):
    kind = RecordType.SETPALENTRIES


@register
@dataclass(frozen=True)
class CreateRegion(Record):
    kind: ClassVar[RecordType] = RecordType.CREATEREGION
    region: Region

    def payload(self) -> bytes:
        return self.region.to_bytes()

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        region = Region.read(reader, limits)
        return cls(region, wire_function=function, trailing=reader.rest())


@register
@dataclass(frozen=True)
class CreatePatternBrush(Record):
    kind: ClassVar[RecordType] = RecordType.CREATEPATTERNBRUSH
    bitmap: BitmapData

    def payload(self) -> bytes:
        if self.bitmap.format != "pattern16" or len(self.bitmap.data) < 32:
            raise ValueError("Legacy pattern brush requires its 32-byte header/reserved block")
        return self.bitmap.data

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        if reader.remaining < 32:
            raise FormatError("Truncated legacy pattern brush")
        return cls(BitmapData("pattern16", reader.rest()), wire_function=function)


@register
@dataclass(frozen=True)
class DibCreatePatternBrush(Record):
    kind: ClassVar[RecordType] = RecordType.DIBCREATEPATTERNBRUSH
    style: int
    color_usage: int
    bitmap: BitmapData

    def payload(self) -> bytes:
        if self.bitmap.format != "dib":
            raise ValueError("DIB pattern brush requires encoded DIB data")
        return pack("HH", self.style, self.color_usage) + self.bitmap.data

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        style, usage = reader.unpack("HH")
        return cls(style, usage, BitmapData("dib", reader.rest()), wire_function=function)


@register
@dataclass(frozen=True)
class Escape(Record):
    kind: ClassVar[RecordType] = RecordType.ESCAPE
    escape_function: int
    data: bytes = b""
    padding: bytes | None = None

    def payload(self) -> bytes:
        return pack("HH", self.escape_function, len(self.data)) + self.data + text_padding(self.data, self.padding)

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        escape_function, count = reader.unpack("HH")
        data = reader.take(count)
        padding = reader.take(count % 2)
        return cls(escape_function, data, padding, wire_function=function, trailing=reader.rest())
