"""Bounded little-endian IO and resource policy shared by graphics codecs."""

import struct
from dataclasses import dataclass


class FormatError(ValueError):
    """The input cannot be interpreted safely as a graphics structure."""


class ResourceLimitError(FormatError):
    """A configured safety limit was exceeded; never a recoverable omission."""


@dataclass(frozen=True)
class Limits:
    """Allocation/work limits; these are policy, not WMF format limits."""

    max_bytes: int = 64 * 1024 * 1024
    max_records: int = 100_000
    max_points: int = 1_000_000
    max_objects: int = 65_535
    max_saved_states: int = 1024

    def __post_init__(self):
        if any(value < 0 for value in vars(self).values()):
            raise ValueError("Limits must be nonnegative")


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
