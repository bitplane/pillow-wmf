"""Immutable GDI inputs, independent of metafile record layouts."""

from dataclasses import dataclass

from ._values import freeze_fields


@dataclass(frozen=True)
class EncodedText:
    """Text bytes decoded with the selected font and code-page environment.

    Explicit advances retain source-byte indexing until decoding determines
    character spans and the environment's spacing convention.
    """

    data: bytes

    def __post_init__(self):
        freeze_fields(self)
        if not isinstance(self.data, bytes):
            raise TypeError("Encoded text must contain bytes")

    def __bool__(self):
        return bool(self.data)


@dataclass(frozen=True)
class GlyphIndices:
    """Font-local glyph IDs; advances index glyphs, not encoded bytes."""

    indices: tuple[int, ...]

    def __post_init__(self):
        freeze_fields(self)
        if any(not 0 <= index <= 65535 for index in self.indices):
            raise ValueError("Glyph indices must fit unsigned words")

    def __bool__(self):
        return bool(self.indices)


@dataclass(frozen=True)
class EncodedFaceName:
    """A legacy face name decoded using the caller's ANSI environment."""

    data: bytes

    def __post_init__(self):
        freeze_fields(self)
        if not isinstance(self.data, bytes):
            raise TypeError("Encoded face names must contain bytes")


@dataclass(frozen=True)
class FontRequest:
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
    face_name: str | EncodedFaceName = ""

    def __post_init__(self):
        # Accept legacy API callers without making bytes the logical contract.
        if isinstance(self.face_name, (bytes, bytearray, memoryview)):
            object.__setattr__(self, "face_name", EncodedFaceName(bytes(self.face_name)))
        elif not isinstance(self.face_name, (str, EncodedFaceName)):
            raise TypeError("Font face name must be text or an encoded face name")


@dataclass(frozen=True)
class PaletteEntries:
    entries: tuple[tuple[int, int, int, int], ...] = ()

    def __post_init__(self):
        freeze_fields(self)
        if any(len(entry) != 4 or any(not 0 <= value <= 255 for value in entry) for entry in self.entries):
            raise ValueError("Palette entries must contain four bytes")


@dataclass(frozen=True)
class PaletteUpdate:
    start: int
    entries: tuple[tuple[int, int, int, int], ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "entries", PaletteEntries(self.entries).entries)
        if self.start < 0:
            raise ValueError("Palette entry offset must be nonnegative")


@dataclass(frozen=True)
class RegionGeometry:
    """Logical rectangles; empty geometry is a valid empty region."""

    rectangles: tuple[tuple[int, int, int, int], ...] = ()

    def __post_init__(self):
        freeze_fields(self)
        if any(len(rectangle) != 4 for rectangle in self.rectangles):
            raise ValueError("Region rectangles require four coordinates")


@dataclass(frozen=True)
class BitmapData:
    """Encoded bitmap bytes, not decoded or certified as renderable."""

    format: str
    data: bytes

    def __post_init__(self):
        freeze_fields(self)
        if self.format not in ("dib", "bitmap16", "pattern16"):
            raise ValueError("Unknown bitmap representation")
        if not isinstance(self.data, bytes):
            raise TypeError("Bitmap data must be immutable bytes")
