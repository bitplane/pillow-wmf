"""EMF reader/writer and player. Import record classes from fixed, variable, bitmaps, text and system."""

from ..binary import FormatError, Limits
from . import bitmaps, fixed, system, text, variable
from .constants import CommentIdentifier, RecordType
from .file import Header, Metafile, accepts
from .objects import LogFont
from .player import play
from .records import RECORD_CLASSES, Record, UnknownRecord

__all__ = [
    "RECORD_CLASSES",
    "CommentIdentifier",
    "FormatError",
    "Header",
    "Limits",
    "LogFont",
    "Metafile",
    "Record",
    "RecordType",
    "UnknownRecord",
    "accepts",
    "bitmaps",
    "fixed",
    "play",
    "system",
    "text",
    "variable",
]
