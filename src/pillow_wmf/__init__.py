"""WMF codec and GDI recording foundation; pixel rendering is not implemented."""

from .gdi import GDI, Call, Handle, UnsupportedOperation
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
    "Recorder",
    "TraceContext",
    "UnsupportedOperation",
    "play",
]
