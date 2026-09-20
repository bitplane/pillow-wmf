"""Bitmap transfer envelopes; BitmapData explicitly preserves opaque pixels."""

from dataclasses import dataclass
from typing import ClassVar

from .binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .objects import BitmapData
from .records import Record, register


@dataclass(frozen=True)
class Blit(Record):
    x: int
    y: int
    width: int
    height: int
    src_x: int
    src_y: int
    rop: int
    source: BitmapData | None = None
    reserved: int = 0
    bitmap_format: ClassVar[str]
    stretch: ClassVar[bool] = False

    def payload(self) -> bytes:
        result = pack("I", self.rop)
        if self.stretch:
            result += pack("hh", self.src_height, self.src_width)
        result += pack("hh", self.src_y, self.src_x)
        if self.source is None:
            result += pack("H", self.reserved)
        result += pack("hhhh", self.height, self.width, self.y, self.x)
        if self.source is not None:
            minimum = 12 if self.bitmap_format == "dib" else 10
            if self.source.format != self.bitmap_format or len(self.source.data) < minimum:
                raise ValueError("Blit source must contain data of the correct bitmap type")
            result += self.source.data
        return result

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        without_source = reader.remaining // 2 == function >> 8
        rop = reader.unpack("I")[0]
        dimensions = {}
        if cls.stretch:
            src_height, src_width = reader.unpack("hh")
            dimensions = {"src_height": src_height, "src_width": src_width}
        src_y, src_x = reader.unpack("hh")
        reserved = reader.unpack("H")[0] if without_source else 0
        height, width, y, x = reader.unpack("hhhh")
        source = None if without_source else BitmapData(cls.bitmap_format, reader.rest())
        minimum = 12 if cls.bitmap_format == "dib" else 10
        if source is not None and len(source.data) < minimum:
            raise FormatError("Missing or truncated embedded bitmap header")
        return cls(
            x,
            y,
            width,
            height,
            src_x,
            src_y,
            rop,
            source,
            reserved,
            **dimensions,
            wire_function=function,
            trailing=reader.rest(),
        )


@register
class BitBlt(Blit):
    kind = RecordType.BITBLT
    bitmap_format = "bitmap16"


@register
class DibBitBlt(Blit):
    kind = RecordType.DIBBITBLT
    bitmap_format = "dib"


@dataclass(frozen=True)
class StretchBlit(Blit):
    src_width: int = 0
    src_height: int = 0
    stretch: ClassVar[bool] = True


@register
class StretchBlt(StretchBlit):
    kind = RecordType.STRETCHBLT
    bitmap_format = "bitmap16"


@register
class DibStretchBlt(StretchBlit):
    kind = RecordType.DIBSTRETCHBLT
    bitmap_format = "dib"


@register
@dataclass(frozen=True)
class SetDibToDev(Record):
    kind: ClassVar[RecordType] = RecordType.SETDIBTODEV
    x: int
    y: int
    width: int
    height: int
    src_x: int
    src_y: int
    start_scan: int
    scan_count: int
    color_usage: int
    source: BitmapData

    def payload(self) -> bytes:
        if self.source.format != "dib":
            raise ValueError("DIB data required")
        return (
            pack(
                "9H",
                self.color_usage,
                self.scan_count,
                self.start_scan,
                self.src_y,
                self.src_x,
                self.height,
                self.width,
                self.y,
                self.x,
            )
            + self.source.data
        )

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        usage, scans, start, src_y, src_x, height, width, y, x = reader.unpack("9H")
        return cls(
            x,
            y,
            width,
            height,
            src_x,
            src_y,
            start,
            scans,
            usage,
            BitmapData("dib", reader.rest()),
            wire_function=function,
        )


@register
@dataclass(frozen=True)
class StretchDib(Record):
    kind: ClassVar[RecordType] = RecordType.STRETCHDIB
    x: int
    y: int
    width: int
    height: int
    src_x: int
    src_y: int
    src_width: int
    src_height: int
    rop: int
    color_usage: int
    source: BitmapData

    def payload(self) -> bytes:
        if self.source.format != "dib":
            raise ValueError("DIB data required")
        return (
            pack(
                "IH8h",
                self.rop,
                self.color_usage,
                self.src_height,
                self.src_width,
                self.src_y,
                self.src_x,
                self.height,
                self.width,
                self.y,
                self.x,
            )
            + self.source.data
        )

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        rop, usage, src_height, src_width, src_y, src_x, height, width, y, x = reader.unpack("IH8h")
        return cls(
            x,
            y,
            width,
            height,
            src_x,
            src_y,
            src_width,
            src_height,
            rop,
            usage,
            BitmapData("dib", reader.rest()),
            wire_function=function,
        )
