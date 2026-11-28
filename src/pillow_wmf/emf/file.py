"""EMF file framing and preserving/canonical serialization."""

import struct
from dataclasses import dataclass, replace

from ..binary import FormatError, Limits, Reader, pack
from ..mapping import REFERENCE_DEVICE, ReferenceDevice
from .constants import CREATION_TYPES, SIGNATURE, RecordType
from .records import Record, UnknownRecord, decode_record, envelope, record_type
from .variable import Eof

HEADER_LAYOUT = "4i4iIIIIHHIII2i2i"
HEADER_SIZE = 8 + struct.calcsize("<" + HEADER_LAYOUT)  # 88: the base Header object
EXTENSION1_SIZE = HEADER_SIZE + 12  # cbPixelFormat, offPixelFormat, bOpenGL
EXTENSION2_SIZE = EXTENSION1_SIZE + 8  # MicrometersX, MicrometersY
VERSION = 0x00010000


def accepts(prefix: bytes) -> bool:
    """Whether bytes start with an EMR_HEADER record carrying the EMF signature."""
    return len(prefix) >= 44 and prefix[:4] == b"\x01\0\0\0" and struct.unpack_from("<I", prefix, 40)[0] == SIGNATURE


@dataclass(frozen=True)
class Header:
    """EMR_HEADER, MS-EMF 2.3.4.2.

    ``extra`` holds every byte after the base header: the optional extension
    fields, the description and the pixel format descriptor, addressed by the
    offsets the record itself declares.
    """

    bounds: tuple[int, int, int, int]
    frame: tuple[int, int, int, int]
    signature: int = SIGNATURE
    version: int = VERSION
    size: int = HEADER_SIZE
    record_count: int = 1
    handle_count: int = 1
    reserved: int = 0
    description_length: int = 0
    description_offset: int = 0
    palette_count: int = 0
    device: tuple[int, int] = REFERENCE_DEVICE.pixels
    millimetres: tuple[int, int] = REFERENCE_DEVICE.millimetres
    extra: bytes = b""

    @classmethod
    def create(cls, bounds, frame, *, device: ReferenceDevice = REFERENCE_DEVICE, description: str | None = None):
        """A header with both extensions and an optional UTF-16LE description.

        A description conventionally names the application and the picture,
        each terminated by NUL, with a final extra NUL.
        """
        micrometres = tuple(1000 * value for value in device.millimetres)
        extra = pack("III2i", 0, 0, 0, *micrometres)
        length = offset = 0
        if description:
            encoded = description.encode("utf-16-le")
            length, offset = len(encoded) // 2, EXTENSION2_SIZE
            extra += encoded + bytes(-len(encoded) % 4)
        return cls(
            tuple(bounds),
            tuple(frame),
            description_length=length,
            description_offset=offset,
            device=device.pixels,
            millimetres=device.millimetres,
            extra=extra,
        )

    @property
    def record_size(self) -> int:
        return HEADER_SIZE + len(self.extra)

    def _clear_of(self, end: int) -> bool:
        # An extension exists only when the record is long enough and no
        # variable-length field starts inside it.
        return self.record_size >= end and (self.description_length == 0 or self.description_offset >= end)

    @property
    def pixel_format_size(self) -> int | None:
        return struct.unpack_from("<I", self.extra)[0] if self._clear_of(EXTENSION1_SIZE) else None

    @property
    def pixel_format_offset(self) -> int | None:
        return struct.unpack_from("<I", self.extra, 4)[0] if self._clear_of(EXTENSION1_SIZE) else None

    @property
    def opengl(self) -> int | None:
        return struct.unpack_from("<I", self.extra, 8)[0] if self._clear_of(EXTENSION1_SIZE) else None

    @property
    def micrometres(self) -> tuple[int, int] | None:
        if not self._clear_of(EXTENSION2_SIZE) or (
            self.pixel_format_size and self.pixel_format_offset < EXTENSION2_SIZE
        ):
            return None
        return struct.unpack_from("<2i", self.extra, 12)

    def _span(self, offset: int, size: int) -> bytes | None:
        start = offset - HEADER_SIZE
        if start < 0 or size > len(self.extra) - start:
            return None
        return self.extra[start : start + size]

    @property
    def description(self) -> str | None:
        """The description text, or None when absent or outside the record."""
        if not self.description_length:
            return None
        data = self._span(self.description_offset, 2 * self.description_length)
        return None if data is None else data.decode("utf-16-le", "replace")

    @property
    def pixel_format(self) -> bytes | None:
        """The raw PixelFormatDescriptor, or None when absent or outside the record."""
        if not self.pixel_format_size:
            return None
        return self._span(self.pixel_format_offset, self.pixel_format_size)

    def to_bytes(self) -> bytes:
        fields = pack(
            HEADER_LAYOUT,
            *self.bounds,
            *self.frame,
            self.signature,
            self.version,
            self.size,
            self.record_count,
            self.handle_count,
            self.reserved,
            self.description_length,
            self.description_offset,
            self.palette_count,
            *self.device,
            *self.millimetres,
        )
        return envelope(RecordType.HEADER, fields + self.extra)

    @classmethod
    def read(cls, reader: Reader, limits: Limits) -> "Header":
        kind, size = reader.unpack("II")
        if kind != RecordType.HEADER or size < HEADER_SIZE or size % 4 or size - 8 > reader.remaining:
            raise FormatError("Invalid EMF header record")
        values = reader.unpack(HEADER_LAYOUT)
        header = cls(
            values[0:4],
            values[4:8],
            *values[8:17],
            device=values[17:19],
            millimetres=values[19:21],
            extra=reader.take(size - HEADER_SIZE),
        )
        if header.signature != SIGNATURE:
            raise FormatError("Invalid EMF signature")
        if header.handle_count > limits.max_objects:
            raise FormatError("Object capacity limit exceeded")
        return header


def object_capacity(records) -> int:
    """Handle-table size: one past the highest slot any record creates.

    Slot 0 is reserved for the metafile itself, so the minimum is 1.
    """
    capacity = 1
    for record in records:
        if record_type(record) not in CREATION_TYPES:
            continue
        if isinstance(record, UnknownRecord):
            if len(record.data) < 4:
                continue
            index = struct.unpack_from("<I", record.data)[0]
        else:
            index = record.object_index
        capacity = max(capacity, index + 1)
    return capacity


def palette_count(eof: Record | UnknownRecord) -> int:
    if isinstance(eof, UnknownRecord):
        return struct.unpack_from("<I", eof.data)[0] if len(eof.data) >= 4 else 0
    return len(eof.entries)


@dataclass(frozen=True)
class Metafile:
    """A header and its records; ``stopped_at`` is the byte offset of an
    invalid record size where a playback read ended, without EOF."""

    header: Header
    records: tuple[Record | UnknownRecord, ...]
    trailing: bytes = b""
    stopped_at: int | None = None

    @classmethod
    def build(
        cls,
        records,
        *,
        bounds=(0, 0, -1, -1),
        frame=(0, 0, -1, -1),
        device: ReferenceDevice = REFERENCE_DEVICE,
        description: str | None = None,
    ):
        """Build a new stream, appending EOF and calculating header accounting.

        ``bounds`` is the inclusive device-pixel bounding box and ``frame``
        the picture frame in 0.01 mm. Neither is derived from the records.
        """
        records = tuple(records)
        if not records or record_type(records[-1]) != RecordType.EOF:
            records += (Eof(),)
        header = Header.create(bounds, frame, device=device, description=description)
        result = cls(header, records)
        return replace(result, header=result._canonical_header())

    def _encoded_records(self, canonical: bool) -> tuple[bytes, ...]:
        if not self.records or record_type(self.records[-1]) != RecordType.EOF:
            raise ValueError("EMF must end with EOF")
        if any(record_type(record) in (RecordType.EOF, RecordType.HEADER) for record in self.records[:-1]):
            raise ValueError("EOF must be the last record and HEADER the first")
        return tuple(record.to_bytes(canonical=canonical) for record in self.records)

    def _canonical_header(self, encoded: tuple[bytes, ...] | None = None) -> Header:
        encoded = self._encoded_records(True) if encoded is None else encoded
        return replace(
            self.header,
            size=self.header.record_size + sum(len(record) for record in encoded),
            record_count=1 + len(encoded),
            handle_count=object_capacity(self.records),
            palette_count=palette_count(self.records[-1]),
        )

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        """Preserve metadata by default; canonical=True recomputes accounting.

        Canonical output rewrites the header's byte, record, handle and
        palette counts and the EOF size copy. Trailing file bytes are retained
        but excluded from the canonical byte count.
        """
        encoded = self._encoded_records(canonical)
        header = self._canonical_header(encoded) if canonical else self.header
        return header.to_bytes() + b"".join(encoded) + self.trailing

    @classmethod
    def from_bytes(cls, data: bytes, *, limits: Limits | None = None, stop_at_invalid_size: bool = False):
        """Decode a stream; every record must be well formed.

        With ``stop_at_invalid_size``, as native playback does, an invalid
        record size ends the records instead, and ``stopped_at`` names it.
        Such a metafile plays but does not encode.
        """
        limits = limits if limits is not None else Limits()
        if not isinstance(data, bytes):
            raise TypeError("Input must be immutable bytes")
        if len(data) > limits.max_bytes:
            raise FormatError("File byte limit exceeded")
        reader = Reader(data)
        header = Header.read(reader, limits)
        # Like WMF, records are walked to EOF within the supplied buffer. The
        # header's byte and record counts are preserved, never trusted.
        end = len(data)
        records = []
        while reader.position < end:
            if len(records) >= limits.max_records:
                raise FormatError("Record count limit exceeded")
            offset = reader.position
            if end - offset < 8:
                raise FormatError(f"Truncated record header at byte {offset}")
            kind, size = reader.unpack("II")
            if size < 8 or size % 4 or size > end - offset:
                if stop_at_invalid_size:
                    return cls(header, tuple(records), data[offset:], stopped_at=offset)
                raise FormatError(f"Invalid record size at byte {offset}")
            payload = reader.take(size - 8)
            try:
                record = decode_record(kind, payload, limits)
            except FormatError as error:
                raise FormatError(f"Record at byte {offset}: {error}") from error
            records.append(record)
            if kind == RecordType.EOF:
                return cls(header, tuple(records), reader.rest())
        raise FormatError("Missing EOF record")
