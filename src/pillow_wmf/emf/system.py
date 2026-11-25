"""Colour management, OpenGL, escape and font-linking records.

Their payloads are carried as bytes; these records do not draw on a bitmap
DC, or depend on device resources outside the metafile.
"""

from dataclasses import dataclass
from typing import ClassVar

from ..binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .records import Record, register

LOGCOLORSPACEA_SIZE = 328
LOGCOLORSPACEW_SIZE = 588
PIXELFORMATDESCRIPTOR_SIZE = 40


@register
@dataclass(frozen=True)
class CreateColorSpace(Record):
    kind: ClassVar[RecordType] = RecordType.CREATECOLORSPACE
    object_index: int
    color_space: bytes

    def payload(self) -> bytes:
        if len(self.color_space) != LOGCOLORSPACEA_SIZE:
            raise ValueError("LogColorSpace is 328 bytes")
        return pack("I", self.object_index) + self.color_space

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        return cls(reader.unpack("I")[0], reader.take(LOGCOLORSPACEA_SIZE), trailing=reader.rest())


@register
@dataclass(frozen=True)
class CreateColorSpaceW(Record):
    kind: ClassVar[RecordType] = RecordType.CREATECOLORSPACEW
    object_index: int
    color_space: bytes
    flags: int = 0
    data: bytes = b""

    def payload(self) -> bytes:
        if len(self.color_space) != LOGCOLORSPACEW_SIZE:
            raise ValueError("LogColorSpaceW is 588 bytes")
        return pack("I", self.object_index) + self.color_space + pack("II", self.flags, len(self.data)) + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        object_index = reader.unpack("I")[0]
        color_space = reader.take(LOGCOLORSPACEW_SIZE)
        flags, size = reader.unpack("II")
        return cls(object_index, color_space, flags, reader.take(size), trailing=reader.rest())


@dataclass(frozen=True)
class ProfileRecord(Record):
    """A profile name followed by profile data."""

    flags: int
    name: bytes
    data: bytes = b""

    def payload(self) -> bytes:
        return pack("III", self.flags, len(self.name), len(self.data)) + self.name + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        flags, name_size, data_size = reader.unpack("III")
        return cls(flags, reader.take(name_size), reader.take(data_size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class SetICMProfileA(ProfileRecord):
    kind: ClassVar[RecordType] = RecordType.SETICMPROFILEA


@register
@dataclass(frozen=True)
class SetICMProfileW(ProfileRecord):
    kind: ClassVar[RecordType] = RecordType.SETICMPROFILEW


@register
@dataclass(frozen=True)
class ColorMatchToTargetW(Record):
    kind: ClassVar[RecordType] = RecordType.COLORMATCHTOTARGETW
    action: int
    flags: int
    name: bytes
    data: bytes = b""

    def payload(self) -> bytes:
        return pack("IIII", self.action, self.flags, len(self.name), len(self.data)) + self.name + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        action, flags, name_size, data_size = reader.unpack("IIII")
        return cls(action, flags, reader.take(name_size), reader.take(data_size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class GlsRecord(Record):
    kind: ClassVar[RecordType] = RecordType.GLSRECORD
    data: bytes

    def payload(self) -> bytes:
        return pack("I", len(self.data)) + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        return cls(reader.take(reader.unpack("I")[0]), trailing=reader.rest())


@register
@dataclass(frozen=True)
class GlsBoundedRecord(Record):
    kind: ClassVar[RecordType] = RecordType.GLSBOUNDEDRECORD
    bounds: tuple[int, int, int, int]
    data: bytes

    def payload(self) -> bytes:
        return pack("4iI", *self.bounds, len(self.data)) + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        *bounds, size = reader.unpack("4iI")
        return cls(tuple(bounds), reader.take(size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class PixelFormat(Record):
    kind: ClassVar[RecordType] = RecordType.PIXELFORMAT
    descriptor: bytes

    def payload(self) -> bytes:
        if len(self.descriptor) != PIXELFORMATDESCRIPTOR_SIZE:
            raise ValueError("PixelFormatDescriptor is 40 bytes")
        return self.descriptor

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        return cls(reader.take(PIXELFORMATDESCRIPTOR_SIZE), trailing=reader.rest())


@dataclass(frozen=True)
class EscapeRecord(Record):
    escape: int
    data: bytes

    def payload(self) -> bytes:
        return pack("iI", self.escape, len(self.data)) + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        escape, size = reader.unpack("iI")
        return cls(escape, reader.take(size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class DrawEscape(EscapeRecord):
    kind: ClassVar[RecordType] = RecordType.DRAWESCAPE


@register
@dataclass(frozen=True)
class ExtEscape(EscapeRecord):
    kind: ClassVar[RecordType] = RecordType.EXTESCAPE


@register
@dataclass(frozen=True)
class NamedEscape(Record):
    kind: ClassVar[RecordType] = RecordType.NAMEDESCAPE
    escape: int
    driver: bytes
    data: bytes

    def payload(self) -> bytes:
        return pack("iII", self.escape, len(self.driver), len(self.data)) + self.driver + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        escape, driver_size, data_size = reader.unpack("iII")
        return cls(escape, reader.take(driver_size), reader.take(data_size), trailing=reader.rest())


@register
@dataclass(frozen=True)
class SetLinkedUFIs(Record):
    """UniversalFontId (checksum, index) pairs and 8 reserved bytes."""

    kind: ClassVar[RecordType] = RecordType.SETLINKEDUFIS
    fonts: tuple[tuple[int, int], ...]
    reserved: bytes = bytes(8)

    def payload(self) -> bytes:
        if len(self.reserved) != 8:
            raise ValueError("SetLinkedUFIs reserves 8 bytes")
        return pack("I", len(self.fonts)) + b"".join(pack("2I", *font) for font in self.fonts) + self.reserved

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        count = reader.unpack("I")[0]
        if count > reader.remaining // 8:
            raise FormatError("Invalid linked font count")
        fonts = tuple(reader.unpack("2I") for _ in range(count))
        return cls(fonts, reader.take(8), trailing=reader.rest())
