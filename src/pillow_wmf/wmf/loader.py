"""Load WMF data for rendering: identify it from its headers, then play it."""

import struct
from dataclasses import dataclass

from .binary import FormatError, Limits, Reader
from .file import Header, Metafile
from .player import play

PLACEABLE_KEY = b"\xd7\xcd\xc6\x9a"
PLACEABLE_SIZE = 22
# Enough to identify the format and read its placement.
HEADER_BYTES = PLACEABLE_SIZE + 18


@dataclass(frozen=True)
class Placement:
    """A drawing area the file declares: logical bounds and their units per inch."""

    bounds: tuple[int, int, int, int]
    units_per_inch: int


def accepts(prefix: bytes) -> bool:
    return prefix.startswith((PLACEABLE_KEY, b"\x01\x00\x09\x00", b"\x02\x00\x09\x00"))


def placement(header: bytes) -> Placement | None:
    """Validate the headers; return the placeable area when it is usable.

    Plain WMFs have no physical size. Empty or reversed placeable bounds, or
    a zero unit density, leave the file without one too.
    """
    placeable = header.startswith(PLACEABLE_KEY)
    Header.read(Reader(header[PLACEABLE_SIZE:] if placeable else header), Limits())
    if placeable:
        left, top, right, bottom, inch = struct.unpack_from("<4hH", header, 6)
        if right > left and bottom > top and inch:
            return Placement((left, top, right, bottom), inch)
    return None


def read(data: bytes, limits: Limits | None = None) -> Metafile:
    """Read for an explicitly sized DC; the placeable wrapper is not GDI data.

    Keep codec validation strict for callers inspecting the wrapper. Native
    playback receives only the enclosed WMF, independent of wrapper checksum,
    physical units or suggested bounds. Byte limits still include the wrapper.
    """
    limits = limits if limits is not None else Limits()
    if not isinstance(data, bytes):
        raise TypeError("Input must be immutable bytes")
    if len(data) > limits.max_bytes:
        raise FormatError("File byte limit exceeded")
    if data.startswith(PLACEABLE_KEY):
        if len(data) < PLACEABLE_SIZE:
            raise FormatError("Truncated placeable WMF header")
        data = data[PLACEABLE_SIZE:]
    return Metafile.from_bytes(data, limits=limits)


def play_into(context, data: bytes, area: Placement | None) -> None:
    """Render completely into a fresh context, mapping any placement onto it.

    Records can override the initial mapping. Unsupported drawing raises
    rather than leaving partial art.
    """
    if area is not None:
        left, top, right, bottom = area.bounds
        context.mapping.window_origin = (left, top)
        context.mapping.window_extent = (right - left, bottom - top)
    play(read(data), context, strict=True)
