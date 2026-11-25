"""EMF record envelopes and the explicit typed-record registry.

Every record is a 32-bit type, a 32-bit byte size that includes the envelope,
and a payload padded to a DWORD boundary. Unknown types stay opaque. A typed
record keeps any bytes after its decoded fields as ``trailing``, and a record
whose decoded fields cannot reproduce its input exactly is kept opaque, so
preserving serialization is byte-exact for every accepted file.
"""

import struct
from dataclasses import dataclass, make_dataclass
from typing import ClassVar

from .._values import freeze_fields
from ..binary import FormatError, Limits, Reader, pack
from .constants import RecordType

RECORD_CLASSES: dict[RecordType, type["Record"]] = {}
ENVELOPE_SIZE = 8


def register(cls):
    if cls.kind in RECORD_CLASSES:
        raise RuntimeError(f"Duplicate EMF record registration: {cls.kind}")
    RECORD_CLASSES[cls.kind] = cls
    return cls


def envelope(kind: int, body: bytes) -> bytes:
    if len(body) % 4:
        raise ValueError("Record payload must be DWORD-aligned")
    return pack("II", kind, ENVELOPE_SIZE + len(body)) + body


@dataclass(frozen=True, kw_only=True)
class Record:
    trailing: bytes = b""
    kind: ClassVar[RecordType]

    def __post_init__(self):
        freeze_fields(self)

    def payload(self) -> bytes:
        raise NotImplementedError

    def body(self, canonical: bool = False) -> bytes:
        return self.payload() + self.trailing

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        return envelope(int(self.kind), self.body(canonical))


class FixedRecord(Record):
    wire_layout: ClassVar[str]
    fields: ClassVar[tuple[str, ...]]

    def payload(self) -> bytes:
        return pack(self.wire_layout, *(getattr(self, name) for name in self.fields))

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        values = reader.unpack(cls.wire_layout)
        return cls(**dict(zip(cls.fields, values, strict=True)), trailing=reader.rest())


class OffsetRecord(FixedRecord):
    """Fixed fields, then data that those fields address by record offset.

    ``data`` holds every byte after the fixed fields, so arbitrary producer
    layouts round-trip. Offsets are checked only when a blob is requested.
    """

    def data_offset(self) -> int:
        """Record offset of the first ``data`` byte."""
        return ENVELOPE_SIZE + struct.calcsize("<" + self.wire_layout)

    def payload(self) -> bytes:
        return super().payload() + self.data

    def blob(self, offset: int, size: int) -> bytes:
        if not size:
            return b""
        start = offset - self.data_offset()
        if start < 0 or size > len(self.data) - start:
            raise FormatError(f"{self.kind.name} data lies outside the record")
        return self.data[start : start + size]

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        values = reader.unpack(cls.wire_layout)
        return cls(**dict(zip(cls.fields, values, strict=True)), data=reader.rest())


def layout_codes(layout: str) -> list[str]:
    codes = []
    count = ""
    for char in layout:
        if char.isdigit():
            count += char
        else:
            codes.extend(char * int(count or 1))
            count = ""
    return codes


def define(module: str, name: str, kind: RecordType, layout: str, names: tuple[str, ...], base=FixedRecord):
    """Declare and register a record class from a struct layout and field names."""
    fields = [(field, float if code == "f" else int) for field, code in zip(names, layout_codes(layout), strict=True)]
    if issubclass(base, OffsetRecord):
        fields.append(("data", bytes))
    cls = make_dataclass(
        name,
        fields,
        bases=(base,),
        frozen=True,
        namespace={"kind": kind, "wire_layout": layout, "fields": names},
        module=module,
    )
    return register(cls)


@dataclass(frozen=True)
class UnknownRecord:
    type: int
    data: bytes

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        return envelope(self.type, self.data)


def decode_record(kind: int, payload: bytes, limits: Limits) -> Record | UnknownRecord:
    try:
        cls = RECORD_CLASSES[RecordType(kind)]
    except (ValueError, KeyError):
        return UnknownRecord(kind, payload)
    try:
        record = cls.read(Reader(payload), limits)
    except FormatError as error:
        raise FormatError(f"{cls.kind.name}: {error}") from error
    # A layout the typed fields cannot express, such as an EOF palette away
    # from its usual offset, stays opaque so that its bytes are preserved.
    try:
        exact = record.body() == payload
    except ValueError:
        exact = False
    return record if exact else UnknownRecord(kind, payload)


def record_type(record: Record | UnknownRecord) -> int:
    return record.type if isinstance(record, UnknownRecord) else int(record.kind)
