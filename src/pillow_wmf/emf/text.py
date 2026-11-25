"""Text records: ExtTextOutA/W, PolyTextOutA/W (MS-EMF 2.3.5, EmrText 2.2.5) and SmallTextOut."""

import struct
from dataclasses import dataclass
from typing import ClassVar

from ..binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .records import ENVELOPE_SIZE, OffsetRecord, Record, register

ETO_NO_RECT = 0x0100
ETO_PDY = 0x2000


@dataclass(frozen=True)
class ExtTextOutRecord(OffsetRecord):
    """Text and advances addressed by offset; the rectangle is optional.

    ``rectangle`` is None exactly when ETO_NO_RECT is set in ``options``.
    """

    bounds: tuple[int, int, int, int]
    graphics_mode: int
    ex_scale: float
    ey_scale: float
    x: int
    y: int
    chars: int
    string_offset: int
    options: int
    rectangle: tuple[int, int, int, int] | None
    dx_offset: int
    data: bytes = b""
    code_unit: ClassVar[int]

    def data_offset(self) -> int:
        return ENVELOPE_SIZE + 52 + (16 if self.rectangle is not None else 0)

    def payload(self) -> bytes:
        if (self.rectangle is None) != bool(self.options & ETO_NO_RECT):
            raise ValueError("Text rectangle is required unless ETO_NO_RECT is set")
        result = pack(
            "4iIffiiIII",
            *self.bounds,
            self.graphics_mode,
            self.ex_scale,
            self.ey_scale,
            self.x,
            self.y,
            self.chars,
            self.string_offset,
            self.options,
        )
        if self.rectangle is not None:
            result += pack("4i", *self.rectangle)
        return result + pack("I", self.dx_offset) + self.data

    @property
    def text(self) -> bytes:
        """The undecoded string: bytes for ExtTextOutA, UTF-16LE for ExtTextOutW."""
        return self.blob(self.string_offset, self.chars * self.code_unit)

    @property
    def advances(self) -> tuple[int, ...]:
        """Per-character advances, interleaved x/y pairs when ETO_PDY is set."""
        count = self.chars * (2 if self.options & ETO_PDY else 1)
        if not self.dx_offset:
            return ()
        return struct.unpack(f"<{count}i", self.blob(self.dx_offset, 4 * count))

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, mode, ex_scale, ey_scale, x, y, chars, string_offset, options = reader.unpack("4iIffiiIII")
        if chars > limits.max_points:
            raise FormatError("Character count limit exceeded")
        rectangle = None if options & ETO_NO_RECT else reader.unpack("4i")
        dx_offset = reader.unpack("I")[0]
        return cls(
            tuple(bounds),
            mode,
            ex_scale,
            ey_scale,
            x,
            y,
            chars,
            string_offset,
            options,
            rectangle,
            dx_offset,
            reader.rest(),
        )


@register
@dataclass(frozen=True)
class ExtTextOutA(ExtTextOutRecord):
    kind: ClassVar[RecordType] = RecordType.EXTTEXTOUTA
    code_unit: ClassVar[int] = 1


@register
@dataclass(frozen=True)
class ExtTextOutW(ExtTextOutRecord):
    kind: ClassVar[RecordType] = RecordType.EXTTEXTOUTW
    code_unit: ClassVar[int] = 2


@dataclass(frozen=True)
class EmrText:
    """One string of a PolyTextOut record; offsets address the record's data."""

    x: int
    y: int
    chars: int
    string_offset: int
    options: int
    rectangle: tuple[int, int, int, int] | None
    dx_offset: int

    def to_bytes(self) -> bytes:
        if (self.rectangle is None) != bool(self.options & ETO_NO_RECT):
            raise ValueError("Text rectangle is required unless ETO_NO_RECT is set")
        result = pack("iiIII", self.x, self.y, self.chars, self.string_offset, self.options)
        if self.rectangle is not None:
            result += pack("4i", *self.rectangle)
        return result + pack("I", self.dx_offset)

    @classmethod
    def read(cls, reader: Reader) -> "EmrText":
        x, y, chars, string_offset, options = reader.unpack("iiIII")
        rectangle = None if options & ETO_NO_RECT else reader.unpack("4i")
        return cls(x, y, chars, string_offset, options, rectangle, reader.unpack("I")[0])


@dataclass(frozen=True)
class PolyTextOutRecord(OffsetRecord):
    bounds: tuple[int, int, int, int]
    graphics_mode: int
    ex_scale: float
    ey_scale: float
    texts: tuple[EmrText, ...]
    data: bytes = b""
    code_unit: ClassVar[int]

    def data_offset(self) -> int:
        return ENVELOPE_SIZE + 32 + sum(len(text.to_bytes()) for text in self.texts)

    def payload(self) -> bytes:
        header = pack("4iIffI", *self.bounds, self.graphics_mode, self.ex_scale, self.ey_scale, len(self.texts))
        return header + b"".join(text.to_bytes() for text in self.texts) + self.data

    def text(self, index: int) -> bytes:
        entry = self.texts[index]
        return self.blob(entry.string_offset, entry.chars * self.code_unit)

    def advances(self, index: int) -> tuple[int, ...]:
        entry = self.texts[index]
        count = entry.chars * (2 if entry.options & ETO_PDY else 1)
        return struct.unpack(f"<{count}i", self.blob(entry.dx_offset, 4 * count)) if entry.dx_offset else ()

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, mode, ex_scale, ey_scale, count = reader.unpack("4iIffI")
        if count > limits.max_points or count > reader.remaining // 24:
            raise FormatError("Invalid string count")
        texts = tuple(EmrText.read(reader) for _ in range(count))
        return cls(tuple(bounds), mode, ex_scale, ey_scale, texts, reader.rest())


@register
@dataclass(frozen=True)
class PolyTextOutA(PolyTextOutRecord):
    kind: ClassVar[RecordType] = RecordType.POLYTEXTOUTA
    code_unit: ClassVar[int] = 1


@register
@dataclass(frozen=True)
class PolyTextOutW(PolyTextOutRecord):
    kind: ClassVar[RecordType] = RecordType.POLYTEXTOUTW
    code_unit: ClassVar[int] = 2


SMALLTEXT_TYPE_ANSI = 0x0200


@register
@dataclass(frozen=True)
class SmallTextOut(Record):
    """Text without advances: 8-bit with SMALLTEXT_TYPE_ANSI, else UTF-16LE.

    ``bounds`` is None exactly when ETO_NO_RECT is set.
    """

    kind: ClassVar[RecordType] = RecordType.SMALLTEXTOUT
    x: int
    y: int
    options: int
    graphics_mode: int
    ex_scale: float
    ey_scale: float
    bounds: tuple[int, int, int, int] | None
    text: bytes
    padding: bytes | None = None

    @property
    def code_unit(self) -> int:
        return 1 if self.options & SMALLTEXT_TYPE_ANSI else 2

    def payload(self) -> bytes:
        if (self.bounds is None) != bool(self.options & ETO_NO_RECT):
            raise ValueError("Bounds are required unless ETO_NO_RECT is set")
        if len(self.text) % self.code_unit:
            raise ValueError("Text must be whole code units")
        chars = len(self.text) // self.code_unit
        result = pack("iiIIIff", self.x, self.y, chars, self.options, self.graphics_mode, self.ex_scale, self.ey_scale)
        if self.bounds is not None:
            result += pack("4i", *self.bounds)
        expected = -len(self.text) % 4
        padding = bytes(expected) if self.padding is None else self.padding
        if len(padding) != expected:
            raise ValueError("Padding must align the record to a DWORD")
        return result + self.text + padding

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        x, y, chars, options, mode, ex_scale, ey_scale = reader.unpack("iiIIIff")
        bounds = None if options & ETO_NO_RECT else reader.unpack("4i")
        text = reader.take(chars * (1 if options & SMALLTEXT_TYPE_ANSI else 2))
        padding = reader.take(min(-len(text) % 4, reader.remaining))
        padding = None if not any(padding) else padding
        return cls(x, y, options, mode, ex_scale, ey_scale, bounds, text, padding, trailing=reader.rest())
