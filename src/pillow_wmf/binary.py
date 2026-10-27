"""Bounded little-endian IO and errors shared by graphics codecs."""

import struct

from .limits import Limits as Limits


class FormatError(ValueError):
    """The input cannot be interpreted safely as a graphics structure."""


class ResourceLimitError(FormatError):
    """A configured safety limit was exceeded; never a recoverable omission."""


class Reader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def take(self, size: int) -> bytes:
        if size < 0 or size > self.remaining:
            raise FormatError(f"Truncated structure at byte {self.position}: need {size}, have {self.remaining}")
        start = self.position
        self.position += size
        return self.data[start : self.position]

    def unpack(self, fmt: str) -> tuple:
        return struct.unpack("<" + fmt, self.take(struct.calcsize("<" + fmt)))

    def rest(self) -> bytes:
        return self.take(self.remaining)


def pack(fmt: str, *values) -> bytes:
    try:
        return struct.pack("<" + fmt, *values)
    except (struct.error, OverflowError) as error:
        raise ValueError(f"Invalid {fmt} field values: {values!r}") from error
