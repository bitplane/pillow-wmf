"""Record GDI commands into WMF with deterministic file-handle allocation."""

import heapq
from dataclasses import replace

from ..gdi import Call, Handle
from ..trace import CREATED_KINDS, TraceContext
from .adapters import wire_arguments
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

    def prepare(self, call: Call):
        token = super().prepare(call)
        call = token.call
        binding = BINDINGS[call.name]
        arguments = wire_arguments(call.name, call.kwargs)
        for parameter in binding.signed_words:
            value = arguments[parameter]
            if not -32768 <= value <= 32767:
                raise ValueError(f"{parameter} must fit a signed WMF word")
            arguments[parameter] = value & 0xFFFF
        for parameter, field in binding.references:
            handle = arguments.pop(parameter)
            if call.name in ("select_object", "select_palette") and handle is None:
                raise ValueError("A null object selection has no portable WMF object index")
            if call.name == "select_clip_region":
                if handle is None:
                    arguments[field] = 0
                    continue
                if self._indexes[handle] == 0:
                    raise ValueError("WMF clip region slot zero means reset; use select_object for this region")
            arguments[field] = self._indexes[handle]
        if call.name == "create_pen":
            arguments["unused_y"] = 0
        if call.name == "set_layout":
            arguments["reserved"] = 0
        record = binding.record(**arguments)
        record.to_bytes()  # Validate before changing bookkeeping or appending.
        # WMF playback changes this legacy extension to DEFAULT_CHARSET.
        equivalent = call.name != "create_font" or call.kwargs["font"].charset != 254
        return replace(token, payload=record, replay_equivalent=equivalent)

    def _execute(self, prepared):
        call = prepared.call
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
        self.records.append(prepared.payload)
        return result

    def metafile(self, *, placeable: PlaceableHeader | None = None) -> Metafile:
        return Metafile.build(self.records, placeable=placeable)

    def to_bytes(self, *, placeable: PlaceableHeader | None = None) -> bytes:
        return self.metafile(placeable=placeable).to_bytes()
