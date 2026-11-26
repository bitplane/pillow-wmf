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
    """Text and advances addressed by offset.

    Playback always reads the fixed layout with the rectangle present, whatever
    ETO_NO_RECT says (MS-EMF describes the rectangle as optional). ``rectangle``
    and ``dx_offset`` are None only for a record too short to hold them, which
    native playback rejects.
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
    dx_offset: int | None
    data: bytes = b""
    code_unit: ClassVar[int]

    # The fixed record: envelope, header fields, rectangle and advance offset.
    FIXED_SIZE: ClassVar[int] = ENVELOPE_SIZE + 68

    def data_offset(self) -> int:
        return self.FIXED_SIZE if self.rectangle is not None else ENVELOPE_SIZE + 48

    def payload(self) -> bytes:
        if (self.rectangle is None) != (self.dx_offset is None):
            raise ValueError("The text rectangle and advance offset are present together")
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
            result += pack("4iI", *self.rectangle, self.dx_offset)
        return result + self.data

    @property
    def text(self) -> bytes:
        """The undecoded string: bytes for ExtTextOutA, UTF-16LE for ExtTextOutW."""
        return self.record_bytes(self.string_offset, self.chars * self.code_unit)

    @property
    def advances(self) -> tuple[int, ...]:
        """Per-character advances, interleaved x/y pairs when ETO_PDY is set."""
        count = self.chars * (2 if self.options & ETO_PDY else 1)
        if not self.dx_offset:
            return ()
        return struct.unpack(f"<{count}i", self.record_bytes(self.dx_offset, 4 * count))

    def playable(self) -> bool:
        """Whether native playback accepts the record's size and offsets."""
        if self.rectangle is None:
            return False
        size = ENVELOPE_SIZE + len(self.payload())
        unit = self.code_unit
        advance = (2 if self.options & ETO_PDY else 1) * 4 if self.dx_offset else 0
        if (unit + advance) * self.chars + 0x4F & ~3 > size:
            return False
        if not self.chars:
            return True
        try:
            return self.text is not None and self.advances is not None
        except FormatError:
            return False

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, mode, ex_scale, ey_scale, x, y, chars, string_offset, options = reader.unpack("4iIffiiIII")
        if chars > limits.max_points:
            raise FormatError("Character count limit exceeded")
        rectangle = dx_offset = None
        if reader.remaining >= 20:
            *rectangle, dx_offset = reader.unpack("4iI")
            rectangle = tuple(rectangle)
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
    """One string of a PolyTextOut record; offsets address the record's data.

    Like ExtTextOut, each entry always carries its rectangle.
    """

    x: int
    y: int
    chars: int
    string_offset: int
    options: int
    rectangle: tuple[int, int, int, int]
    dx_offset: int

    SIZE: ClassVar[int] = 40

    def to_bytes(self) -> bytes:
        return pack(
            "iiIII4iI", self.x, self.y, self.chars, self.string_offset, self.options, *self.rectangle, self.dx_offset
        )

    @classmethod
    def read(cls, reader: Reader) -> "EmrText":
        x, y, chars, string_offset, options, *rectangle, dx_offset = reader.unpack("iiIII4iI")
        return cls(x, y, chars, string_offset, options, tuple(rectangle), dx_offset)


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
        return ENVELOPE_SIZE + 32 + EmrText.SIZE * len(self.texts)

    def payload(self) -> bytes:
        header = pack("4iIffI", *self.bounds, self.graphics_mode, self.ex_scale, self.ey_scale, len(self.texts))
        return header + b"".join(text.to_bytes() for text in self.texts) + self.data

    def text(self, index: int) -> bytes:
        entry = self.texts[index]
        return self.record_bytes(entry.string_offset, entry.chars * self.code_unit)

    def advances(self, index: int) -> tuple[int, ...]:
        """Playback always reads advances; a zero offset addresses the record header."""
        entry = self.texts[index]
        count = entry.chars * (2 if entry.options & ETO_PDY else 1)
        return struct.unpack(f"<{count}i", self.record_bytes(entry.dx_offset, 4 * count))

    def playable(self) -> bool:
        """Whether native playback accepts every entry's string and advance extents."""
        try:
            for index, entry in enumerate(self.texts):
                if entry.chars:
                    self.text(index)
                    self.advances(index)
        except FormatError:
            return False
        return True

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, mode, ex_scale, ey_scale, count = reader.unpack("4iIffI")
        if count > limits.max_points or count > reader.remaining // EmrText.SIZE:
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
