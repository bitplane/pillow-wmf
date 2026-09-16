"""Record GDI commands into WMF with deterministic file-handle allocation."""

import heapq

from ..gdi import Call, Handle
from ..trace import CREATED_KINDS, TraceContext
from .bindings import BINDINGS
from .file import Metafile, PlaceableHeader
from .records import Record


class Recorder(TraceContext):
    """A checked command recorder, not a rendering device-context emulator.

    Use direct Record construction for reserved fields, unknown opcodes and
    intentionally invalid test cases. Public calls use logical backend handles.
    """

    def __init__(self, **limits):
        super().__init__(**limits)
        self.records: list[Record] = []
        self._indexes: dict[Handle, int] = {}
        self._free: list[int] = []
        self._capacity = 0

    def invoke(self, call: Call) -> Handle | int | None:
        call = self._prepare(call)
        binding = BINDINGS[call.name]
        arguments = call.kwargs
        for parameter, field in binding.references:
            arguments[field] = self._indexes[arguments.pop(parameter)]
        if call.name == "create_pen":
            arguments["unused_y"] = 0
        if call.name == "set_layout":
            arguments["reserved"] = 0
        record = binding.record(**arguments)
        record.to_bytes()  # Validate before changing bookkeeping or appending.
        result = self._commit(call)
        if call.name in CREATED_KINDS:
            if self._free:
                index = heapq.heappop(self._free)
            else:
                index = self._capacity
                self._capacity += 1
            self._indexes[result] = index
        elif call.name == "delete_object":
            heapq.heappush(self._free, self._indexes.pop(call.kwargs["handle"]))
        self.records.append(record)
        return result

    def metafile(self, *, placeable: PlaceableHeader | None = None) -> Metafile:
        return Metafile.build(self.records, placeable=placeable)

    def to_bytes(self, *, placeable: PlaceableHeader | None = None) -> bytes:
        return self.metafile(placeable=placeable).to_bytes()
