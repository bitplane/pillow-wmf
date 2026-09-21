"""WMF codec, GDI recording and Pillow loading with an RGB raster backend."""

from .gdi import GDI, Call, Handle, InvalidOperation, UnsupportedOperation
from .objects import (
    EncodedFaceName,
    EncodedText,
    FontRequest,
    GlyphIndices,
    PaletteEntries,
    PaletteUpdate,
    RegionGeometry,
)
from .plugin import register as _register
from .raster import RasterContext
from .render import render
from .system_fonts import FontSubstitution, SystemFontCollection
from .text import FontCollection, FontFace
from .trace import TraceContext
from .wmf import FormatError, Limits, Metafile, PlaceableHeader
from .wmf.objects import Font
from .wmf.player import Omission, PlaybackError, play
from .wmf.recorder import Recorder

_register()

__all__ = [
    "GDI",
    "Call",
    "Font",
    "FontRequest",
    "EncodedFaceName",
    "EncodedText",
    "GlyphIndices",
    "PaletteEntries",
    "PaletteUpdate",
    "RegionGeometry",
    "FontCollection",
    "FontFace",
    "FontSubstitution",
    "SystemFontCollection",
    "FormatError",
    "Handle",
    "InvalidOperation",
    "Limits",
    "Metafile",
    "Omission",
    "PlaceableHeader",
    "PlaybackError",
    "RasterContext",
    "Recorder",
    "TraceContext",
    "UnsupportedOperation",
    "play",
    "render",
]
