"""Wire-level graphics structures. Bitmap pixels are deliberately undecoded."""

from dataclasses import dataclass, field

from .._values import freeze_fields
from .binary import FormatError, Limits, Reader, pack


@dataclass(frozen=True)
class Font:
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
    face_name: bytes = bytes(32)

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self) -> bytes:
        if len(self.face_name) > 32:
            raise ValueError("Font face name is at most 32 bytes")
        values = tuple(getattr(self, name) for name in self.__dataclass_fields__ if name != "face_name")
        return pack("5h8B", *values) + self.face_name

    @classmethod
    def read(cls, reader: Reader):
        values = reader.unpack("5h8B")
        return cls(*values, face_name=reader.take(min(32, reader.remaining)))


@dataclass(frozen=True)
class Palette:
    start: int = 0x0300
    entries: tuple[tuple[int, int, int, int], ...] = ()

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self) -> bytes:
        return pack("HH", self.start, len(self.entries)) + b"".join(pack("4B", *entry) for entry in self.entries)

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        start, count = reader.unpack("HH")
        if count > reader.remaining // 4:
            raise FormatError("Palette entries exceed record")
        return cls(start, tuple(reader.unpack("4B") for _ in range(count)))


@dataclass(frozen=True)
class Scan:
    top: int
    bottom: int
    endpoints: tuple[int, ...]

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self) -> bytes:
        if len(self.endpoints) % 2:
            raise ValueError("Scan endpoints must be left/right pairs")
        return pack("HHH", len(self.endpoints), self.top, self.bottom) + pack(
            "H" * (len(self.endpoints) + 1), *self.endpoints, len(self.endpoints)
        )

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        count, top, bottom = reader.unpack("HHH")
        if count % 2 or count > limits.max_points:
            raise FormatError("Invalid scan endpoint count")
        endpoints = reader.unpack("H" * count)
        if reader.unpack("H")[0] != count:
            raise FormatError("Scan endpoint counts disagree")
        return cls(top, bottom, endpoints)


@dataclass(frozen=True)
class Region:
    bounds: tuple[int, int, int, int]
    scans: tuple[Scan, ...]
    next_in_chain: int = field(default=0, compare=False)
    object_type: int = 6
    object_count: int = field(default=0, compare=False)
    declared_size: int | None = field(default=None, compare=False)
    max_scan: int | None = field(default=None, compare=False)

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self) -> bytes:
        scans = b"".join(scan.to_bytes() for scan in self.scans)
        size = self.declared_size if self.declared_size is not None else 22 + len(scans)
        maximum = self.max_scan if self.max_scan is not None else max((len(s.endpoints) for s in self.scans), default=0)
        return (
            pack(
                "HhIhhh4h",
                self.next_in_chain,
                self.object_type,
                self.object_count,
                size,
                len(self.scans),
                maximum,
                *self.bounds,
            )
            + scans
        )

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        chain, kind, objects, size, count, maximum, *bounds = reader.unpack("HhIhhh4h")
        if kind != 6 or count < 0 or count > limits.max_points or count > reader.remaining // 8:
            raise FormatError("Invalid region header")
        scans = []
        total = 0
        for _ in range(count):
            scan = Scan.read(reader, limits)
            total += len(scan.endpoints)
            if total > limits.max_points:
                raise FormatError("Region endpoint limit exceeded")
            scans.append(scan)
        return cls(tuple(bounds), tuple(scans), chain, kind, objects, size, maximum)


@dataclass(frozen=True)
class BitmapData:
    """An encoded Bitmap16 or DIB, not decoded or certified as renderable.

    Keeping this explicit prevents opaque preservation from being mistaken for
    bitmap codec support. The separate bitmap module decodes a bounded subset;
    constructing this envelope alone does not validate its header or pixels.
    """

    format: str
    data: bytes

    def __post_init__(self):
        freeze_fields(self)
        if self.format not in ("dib", "bitmap16", "pattern16"):
            raise ValueError("Unknown bitmap representation")
        if not isinstance(self.data, bytes):
            raise TypeError("Bitmap data must be immutable bytes")
