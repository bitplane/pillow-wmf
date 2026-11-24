"""Wire-level EMF object structures."""

from dataclasses import dataclass

from .._values import freeze_fields
from ..binary import FormatError, Reader, pack

FACE_NAME_BYTES = 64


@dataclass(frozen=True)
class LogFont:
    """LogFont, MS-EMF 2.2.13; the face name is 32 UTF-16LE code units."""

    height: int = 0
    width: int = 0
    escapement: int = 0
    orientation: int = 0
    weight: int = 0
    italic: int = 0
    underline: int = 0
    strikeout: int = 0
    charset: int = 0
    out_precision: int = 0
    clip_precision: int = 0
    quality: int = 0
    pitch_and_family: int = 0
    face_name: bytes = bytes(FACE_NAME_BYTES)

    def __post_init__(self):
        freeze_fields(self)

    @property
    def face(self) -> str:
        """The face name up to its first NUL; undecodable units are replaced."""
        units = self.face_name[: len(self.face_name) // 2 * 2].decode("utf-16-le", "replace")
        return units.split("\0", 1)[0]

    def to_bytes(self) -> bytes:
        if len(self.face_name) != FACE_NAME_BYTES:
            raise ValueError("Font face name must be exactly 64 bytes")
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__ if name != "face_name")
        return pack("5i8B", *values) + self.face_name

    @classmethod
    def read(cls, reader: Reader) -> "LogFont":
        values = reader.unpack("5i8B")
        return cls(*values, face_name=reader.take(FACE_NAME_BYTES))


def read_palette_entries(reader: Reader, count: int) -> tuple[tuple[int, int, int, int], ...]:
    """Read PaletteEntry objects (red, green, blue, flags), MS-EMF 2.2.18."""
    if count > reader.remaining // 4:
        raise FormatError("Invalid palette entry count")
    return tuple(reader.unpack("4B") for _ in range(count))


def pack_palette_entries(entries) -> bytes:
    return b"".join(pack("4B", *entry) for entry in entries)
