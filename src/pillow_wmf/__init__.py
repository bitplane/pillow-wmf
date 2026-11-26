"""WMF and EMF codecs, GDI recording and Pillow loading with an RGB raster backend."""

from .binary import ResourceLimitError
from .gdi import GDI, Call, Handle, InvalidOperation, PreparedCall, UnsupportedOperation
from .objects import (
    EncodedFaceName,
    EncodedText,
    FontRequest,
    GlyphIndices,
    PaletteEntries,
    PaletteUpdate,
    RegionGeometry,
    UnicodeText,
)
from .playback import Omission, PlaybackError
from .plugin import register as _register
from .raster import RasterContext
from .recording import RecordingContext
from .render import render
from .system_fonts import FontSubstitution, SystemFontCollection
from .text import FontCollection, FontFace
from .trace import TraceContext
from .wmf import FormatError, Limits, Metafile, PlaceableHeader
from .wmf.objects import Font
from .wmf.player import play
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
    "UnicodeText",
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
    "PreparedCall",
    "PlaybackError",
    "RasterContext",
    "RecordingContext",
    "Recorder",
    "ResourceLimitError",
    "TraceContext",
    "UnsupportedOperation",
    "play",
    "render",
]
