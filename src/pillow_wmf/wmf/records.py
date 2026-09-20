"""Record envelopes and the explicit typed-record registry.

Unknown records stay opaque. Known records retain their original function word
and any uninterpreted trailing bytes independently of their decoded fields.
"""

from dataclasses import dataclass
from typing import ClassVar

from .._values import freeze_fields
from .binary import FormatError, Limits, Reader, pack
from .constants import RecordType

RECORD_CLASSES: dict[RecordType, type["Record"]] = {}
RECORD_TYPES_BY_LOW_BYTE = {int(kind) & 0xFF: kind for kind in RecordType}


def register(cls):
    if cls.kind in RECORD_CLASSES:
        raise RuntimeError(f"Duplicate WMF record registration: {cls.kind}")
    RECORD_CLASSES[cls.kind] = cls
    return cls


@dataclass(frozen=True, kw_only=True)
class Record:
    wire_function: int | None = None
    trailing: bytes = b""
    kind: ClassVar[RecordType]

    def __post_init__(self):
        freeze_fields(self)

    def payload(self) -> bytes:
        raise NotImplementedError

    def function(self, canonical: bool = False) -> int:
        if not canonical and self.wire_function is not None:
            if self.wire_function & 0xFF != self.kind & 0xFF:
                raise ValueError("Function word does not match the record type")
            return self.wire_function
        return int(self.kind)

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        payload = self.payload() + self.trailing
        if len(payload) % 2:
            raise ValueError("Record payload must be word-aligned")
        return pack("IH", 3 + len(payload) // 2, self.function(canonical)) + payload


class FixedRecord(Record):
    wire_layout: ClassVar[str]
    fields: ClassVar[tuple[str, ...]]

    def payload(self) -> bytes:
        return pack(self.wire_layout, *(getattr(self, name) for name in self.fields))

    @classmethod
    def read(cls, reader: Reader, function: int, limits: Limits):
        values = reader.unpack(cls.wire_layout)
        return cls(**dict(zip(cls.fields, values, strict=True)), wire_function=function, trailing=reader.rest())


@dataclass(frozen=True)
class UnknownRecord:
    function: int
    data: bytes

    def __post_init__(self):
        freeze_fields(self)

    def to_bytes(self, *, canonical: bool = False) -> bytes:
        if len(self.data) % 2:
            raise ValueError("Unknown record payload must be word-aligned")
        return pack("IH", 3 + len(self.data) // 2, self.function) + self.data


def decode_record(function: int, payload: bytes, limits: Limits) -> Record | UnknownRecord:
    # Most function high bytes are advisory. Bitmap variants inspect the actual
    # word and record size themselves. EOF is explicitly the full word 0x0000.
    kind = RECORD_TYPES_BY_LOW_BYTE.get(function & 0xFF)
    if kind is None or (kind == RecordType.EOF and function != 0):
        return UnknownRecord(function, payload)
    cls = RECORD_CLASSES[kind]
    try:
        return cls.read(Reader(payload), function, limits)
    except FormatError as error:
        raise FormatError(f"{kind.name}: {error}") from error
