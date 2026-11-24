"""ExtTextOutA/W records, MS-EMF 2.3.5.7-8 with EmrText 2.2.5."""

import struct
from dataclasses import dataclass
from typing import ClassVar

from ..binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .records import ENVELOPE_SIZE, OffsetRecord, register

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
