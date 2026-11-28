"""Load EMF data for rendering: identify it from its header, then play it."""

import struct

from ..binary import FormatError, Limits
from ..placement import Placement
from .constants import SIGNATURE
from .file import HEADER_SIZE, Header, Metafile
from .player import play
from .transform import natural_size

# The base header object: enough for the frame and reference device.
HEADER_BYTES = HEADER_SIZE
FRAME_UNITS_PER_INCH = 2540  # The frame is in 0.01 mm.


def accepts(prefix: bytes) -> bool:
    """An EMR_HEADER record, with the EMF signature once the prefix reaches it."""
    if prefix[:4] != b"\x01\x00\x00\x00":
        return False
    return len(prefix) < 44 or struct.unpack_from("<I", prefix, 40)[0] == SIGNATURE


def placement(header: bytes) -> Placement:
    """The picture frame, and its size in reference-device pixels as the default."""
    if len(header) < HEADER_SIZE or not accepts(header):
        raise FormatError("Invalid EMF header record")
    kind, size, *values = struct.unpack_from("<II4i4iIIIIHHIII2i2i", header)
    if size < HEADER_SIZE or size % 4:
        raise FormatError("Invalid EMF header record")
    frame = tuple(values[4:8])
    device, millimetres = tuple(values[17:19]), tuple(values[19:21])
    if any(value <= 0 for value in (*device, *millimetres)):
        raise FormatError("EMF header has no reference device size")
    picture = Header((0, 0, -1, -1), frame, device=device, millimetres=millimetres)
    return Placement(frame, FRAME_UNITS_PER_INCH, natural_size(picture))


def read(data: bytes, limits: Limits | None = None) -> Metafile:
    """Read for playback: records end at an invalid record size, as natively."""
    return Metafile.from_bytes(data, limits=limits, stop_at_invalid_size=True)


def play_into(context, data: bytes, area: Placement | None) -> None:
    """Render completely, fitting the picture frame to the whole context.

    Unsupported drawing raises rather than leaving partial art.
    """
    play(read(data), context, strict=True, rect=(0, 0, context.surface.width, context.surface.height))
