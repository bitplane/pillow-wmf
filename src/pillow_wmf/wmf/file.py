"""WMF file framing and preserving/canonical serialization."""

import heapq
from dataclasses import dataclass, replace
from functools import reduce
from operator import xor

from .binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .fixed import Eof
from .records import Record, UnknownRecord, decode_record

CREATION_TYPES = frozenset(
    {
        RecordType.CREATEPENINDIRECT,
        RecordType.CREATEBRUSHINDIRECT,
        RecordType.CREATEFONTINDIRECT,
        RecordType.CREATEPALETTE,
        RecordType.CREATEREGION,
        RecordType.CREATEPATTERNBRUSH,
        RecordType.DIBCREATEPATTERNBRUSH,
    }
)


@dataclass(frozen=True)
class Header:
    type: int = 1
    header_size: int = 9
    version: int = 0x0300
    size: int = 12
    object_count: int = 0
    max_record: int = 3
    members: int = 0

    def to_bytes(self) -> bytes:
        return pack(
            "HHHIHIH",
            self.type,
            self.header_size,
            self.version,
            self.size,
            self.object_count,
            self.max_record,
            self.members,
        )


@dataclass(frozen=True)
class PlaceableHeader:
    left: int
    top: int
    right: int
    bottom: int
    inch: int = 1440
    handle: int = 0
    reserved: int = 0
    checksum: int | None = None

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        if self.inch == 0:
            raise ValueError("Placeable units per inch must be nonzero")
        prefix = pack(
            "IH4hHI", 0x9AC6CDD7, self.handle, self.left, self.top, self.right, self.bottom, self.inch, self.reserved
        )
        checksum = reduce(xor, Reader(prefix).unpack("10H"), 0)
        return prefix + pack("H", checksum if canonical or self.checksum is None else self.checksum)

    @classmethod
    def read(cls, reader: Reader, validate_checksum: bool):
        raw = reader.take(22)
        key, handle, left, top, right, bottom, inch, reserved, checksum = Reader(raw).unpack("IH4hHIH")
        if key != 0x9AC6CDD7 or inch == 0:
            raise FormatError("Invalid placeable header")
        if validate_checksum and reduce(xor, Reader(raw).unpack("11H"), 0):
            raise FormatError("Invalid placeable checksum")
        return cls(left, top, right, bottom, inch, handle, reserved, checksum)


def object_capacity(records: tuple[Record | UnknownRecord, ...]) -> int:
    free = []
    live = set()
    capacity = 0
    for record in records:
        if isinstance(record, UnknownRecord):
            continue
        if record.kind in CREATION_TYPES:
            if free:
                index = heapq.heappop(free)
            else:
                index = capacity
                capacity += 1
            live.add(index)
        elif record.kind == RecordType.DELETEOBJECT and record.object_index in live:
            live.remove(record.object_index)
            heapq.heappush(free, record.object_index)
    return capacity


@dataclass(frozen=True)
class Metafile:
    header: Header
    records: tuple[Record | UnknownRecord, ...]
    placeable: PlaceableHeader | None = None
    trailing: bytes = b""

    @classmethod
    def build(cls, records, *, placeable: PlaceableHeader | None = None, version: int = 0x0300):
        """Build a new stream, inserting EOF and calculating header accounting.

        Direct records may intentionally contain semantically invalid handle
        references for test fixtures. Use Recorder for checked handle lifetimes.
        """
        if version not in (0x0100, 0x0300):
            raise ValueError("Unsupported WMF version")
        records = tuple(records)
        if not records or not isinstance(records[-1], Eof):
            records += (Eof(),)
        result = cls(Header(version=version), records, placeable)
        return replace(result, header=result._canonical_header())

    def _encoded_records(self, canonical: bool) -> tuple[bytes, ...]:
        if not self.records or not isinstance(self.records[-1], Eof):
            raise ValueError("WMF must end with EOF")
        if any(isinstance(record, Eof) for record in self.records[:-1]):
            raise ValueError("EOF must be the last record")
        return tuple(record.to_bytes(canonical=canonical) for record in self.records)

    def _canonical_header(self, encoded: tuple[bytes, ...] | None = None) -> Header:
        encoded = self._encoded_records(True) if encoded is None else encoded
        return replace(
            self.header,
            header_size=9,
            size=9 + sum(len(r) // 2 for r in encoded),
            max_record=max(len(r) // 2 for r in encoded),
            object_count=object_capacity(self.records),
        )

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        """Preserve metadata by default; canonical=True recomputes file sizes.

        Trailing file bytes are retained but excluded from canonical stream size.
        Reserved/padding bytes in records remain explicit data in either mode.
        """
        encoded = self._encoded_records(canonical)
        header = self._canonical_header(encoded) if canonical else self.header
        prefix = self.placeable.to_bytes(canonical=canonical) if self.placeable else b""
        return prefix + header.to_bytes() + b"".join(encoded) + self.trailing

    @classmethod
    def from_bytes(cls, data: bytes, *, limits: Limits | None = None, validate_checksum: bool = True):
        limits = limits if limits is not None else Limits()
        if len(data) > limits.max_bytes:
            raise FormatError("File byte limit exceeded")
        if not isinstance(data, bytes):
            raise TypeError("Input must be immutable bytes")
        reader = Reader(data)
        placeable = PlaceableHeader.read(reader, validate_checksum) if data[:4] == b"\xd7\xcd\xc6\x9a" else None
        start = reader.position
        header = Header(*reader.unpack("HHHIHIH"))
        if header.type not in (1, 2) or header.version not in (0x0100, 0x0300) or header.header_size != 9:
            raise FormatError("Unsupported WMF header type, version or size")
        if header.object_count > limits.max_objects:
            raise FormatError("Object capacity limit exceeded")
        end = start + header.size * 2
        if end < reader.position + 6 or end > len(data):
            raise FormatError("Invalid declared metafile size")
        records = []
        while reader.position < end:
            if len(records) >= limits.max_records:
                raise FormatError("Record count limit exceeded")
            offset = reader.position
            if end - offset < 6:
                raise FormatError(f"Truncated record header at byte {offset}")
            size, function = reader.unpack("IH")
            if size < 3 or size * 2 > end - offset:
                raise FormatError(f"Invalid record size at byte {offset}")
            payload = reader.take(size * 2 - 6)
            try:
                record = decode_record(function, payload, limits)
            except FormatError as error:
                raise FormatError(f"Record at byte {offset}: {error}") from error
            records.append(record)
            if isinstance(record, Eof):
                return cls(header, tuple(records), placeable, reader.rest())
        raise FormatError("Missing EOF record")
