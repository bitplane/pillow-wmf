"""Translate WMF records to backend calls without rasterizing or decoding text."""

import heapq
from dataclasses import dataclass, replace

from ..gdi import GDI, Call, Handle, InvalidOperation, UnsupportedOperation
from .binary import Limits
from .bindings import BY_KIND
from .constants import RecordType
from .file import CREATION_TYPES, Metafile
from .records import UnknownRecord


class PlaybackError(ValueError):
    """A stream's handle references or backend results are invalid."""


@dataclass(frozen=True)
class Omission:
    record_index: int
    function: int
    reason: str


def play(
    metafile: Metafile, backend: GDI, *, strict: bool = False, limits: Limits | None = None
) -> tuple[Omission, ...]:
    """Play into a supplied context; return diagnostics for unsupported work.

    The caller owns the backend and its initial state. No implicit drawing-state
    reset, object deletion, or source-byte rewrite is inserted into the trace.
    Unsupported creations occupy their WMF slots to prevent handle aliasing.
    """
    limits = limits if limits is not None else Limits()
    if metafile.header.object_count > limits.max_objects or len(metafile.records) > limits.max_records:
        raise PlaybackError("Playback resource limit exceeded")
    empty = object()
    unavailable = object()
    slots = [empty] * metafile.header.object_count
    free = list(range(len(slots)))
    free_slots = set(free)
    omissions = []
    saved = []
    backend_saved = []

    def release(slot):
        if slot not in free_slots:
            heapq.heappush(free, slot)
            free_slots.add(slot)

    def omit(index, function, reason):
        if strict:
            raise UnsupportedOperation(f"Record {index}: {reason}")
        omissions.append(Omission(index, function, reason))

    for index, record in enumerate(metafile.records):
        if isinstance(record, UnknownRecord):
            omit(index, record.function, "Unknown record")
            continue
        if record.kind == RecordType.EOF:
            break
        if record.kind == RecordType.SETRELABS:
            continue  # Required-ignore, even in strict mode.
        name, binding = BY_KIND[record.kind]
        if name == "save_dc" and max(len(saved), len(backend_saved)) >= limits.max_saved_states:
            raise PlaybackError(f"Record {index}: saved-state limit exceeded")
        if name == "restore_dc":
            level = record.saved_dc
            target = level if level > 0 else len(saved) + level + 1
            if level == 0 or target < 1 or target > len(saved):
                raise PlaybackError(f"Record {index}: invalid saved DC reference")
            native_saved = saved[target - 1]
            del saved[target - 1 :]
            if native_saved is None:
                omit(index, record.function(), "Saved DC was unsupported")
                continue
        elif name == "save_dc":
            saved.append(None)
        references = dict(binding.references)
        arguments = {}
        missing = False
        for parameter in binding.parameters:
            value = getattr(record, references.get(parameter, parameter))
            if parameter in references:
                if name == "select_clip_region" and value == 0:
                    arguments[parameter] = None
                    continue
                if value >= len(slots) or value < 0:
                    raise PlaybackError(f"Record {index}: invalid object index {value}")
                if slots[value] is empty:
                    if name not in {"select_clip_region", "select_object", "select_palette", "delete_object"}:
                        raise PlaybackError(f"Record {index}: invalid object index {value}")
                    arguments[parameter] = None
                    continue
                if slots[value] is unavailable:
                    missing = True
                value = slots[value]
            arguments[parameter] = value

        for parameter in binding.signed_words:
            value = arguments[parameter]
            arguments[parameter] = value - 0x10000 if value & 0x8000 else value

        if name == "create_font" and arguments["font"].charset == 254:
            # WMF playback converts the UTF-8 extension to DEFAULT_CHARSET;
            # it does not preserve the direct GDI font API's UTF-8 request.
            # Our explicit ANSI environments are all legacy code pages.
            arguments["font"] = replace(arguments["font"], charset=1)

        if name == "restore_dc":
            # File save levels include omitted saves. Backend levels do not,
            # and may also include frames left by a rejected restore.
            native_index = backend_saved.index(native_saved)
            arguments["saved_dc"] = native_saved if level > 0 else native_index - len(backend_saved)

        slot = None
        if record.kind in CREATION_TYPES:
            if not free:
                raise PlaybackError(f"Record {index}: object table is full")
            slot = heapq.heappop(free)
            free_slots.remove(slot)
            slots[slot] = unavailable
        if missing:
            omit(index, record.function(), "Object creation was unsupported")
            # A deletion still releases the file slot of an unsupported object.
            if record.kind == RecordType.DELETEOBJECT:
                slots[record.object_index] = empty
                release(record.object_index)
            continue
        if name == "delete_object" and arguments["handle"] is None:
            continue  # An empty slot has no backend resource to delete.
        try:
            result = backend.invoke(Call.make(name, **arguments))
        except (UnsupportedOperation, InvalidOperation) as error:
            if strict and isinstance(error, InvalidOperation):
                raise PlaybackError(f"Record {index}: {error}") from error
            omit(index, record.function(), str(error))
            # File-slot lifetime is independent of backend resource cleanup.
            if record.kind == RecordType.DELETEOBJECT:
                slots[record.object_index] = empty
                release(record.object_index)
            continue
        if slot is not None:
            if not isinstance(result, Handle):
                raise PlaybackError(f"Record {index}: object creation did not return a handle")
            slots[slot] = result
            if backend.is_null_object(result):
                release(slot)
        if name == "save_dc":
            if not isinstance(result, int) or isinstance(result, bool) or result <= 0 or result in backend_saved:
                raise PlaybackError(f"Record {index}: save did not return a valid saved DC identifier")
            saved[-1] = result
            backend_saved.append(result)
        elif name == "restore_dc":
            del backend_saved[native_index:]
        if record.kind == RecordType.DELETEOBJECT:
            slots[record.object_index] = empty
            release(record.object_index)
    return tuple(omissions)
