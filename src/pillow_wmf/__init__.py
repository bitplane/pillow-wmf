"""WMF codec, GDI recording, and an initial Pillow raster backend."""

from .gdi import GDI, Call, Handle, UnsupportedOperation
from .raster import RasterContext
from .trace import TraceContext
from .wmf import FormatError, Limits, Metafile, PlaceableHeader
from .wmf.player import PlaybackError, play
from .wmf.recorder import Recorder

__all__ = [
    "GDI",
    "Call",
    "FormatError",
    "Handle",
    "Limits",
    "Metafile",
    "PlaceableHeader",
    "PlaybackError",
    "RasterContext",
    "Recorder",
    "TraceContext",
    "UnsupportedOperation",
    "play",
]
