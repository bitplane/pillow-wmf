"""A non-rendering GDI backend with checked handle and save-stack bookkeeping.

This records requested operations. It does not emulate mapping, selected-object
deletion quirks, clipping, palette realization or any pixel effects.
"""

import inspect

from .gdi import GDI, OPERATION_NAMES, Call, Handle, UnsupportedOperation

CREATED_KINDS = {
    "create_pen": "pen",
    "create_brush": "brush",
    "create_font": "font",
    "create_palette": "palette",
    "create_region": "region",
    "create_pattern_brush": "brush",
    "create_dib_pattern_brush": "brush",
}
REFERENCES = {
    "select_object": {"handle": {"pen", "brush", "font", "region"}},
    "delete_object": {"handle": {"pen", "brush", "font", "region", "palette"}},
    "select_palette": {"handle": {"palette"}},
    "select_clip_region": {"region": {"region"}},
    "fill_region": {"region": {"region"}, "brush": {"brush"}},
    "frame_region": {"region": {"region"}, "brush": {"brush"}},
    "paint_region": {"region": {"region"}},
    "invert_region": {"region": {"region"}},
}
SIGNATURES = {name: inspect.signature(getattr(GDI, name)) for name in OPERATION_NAMES}


class TraceContext(GDI):
    def __init__(self, *, max_objects: int = 65_535, max_saved_states: int = 1024):
        if max_objects < 0 or max_saved_states < 0:
            raise ValueError("Limits must be nonnegative")
        self.calls: list[Call] = []
        self._live: dict[int, Handle] = {}
        self._next_handle = 1
        self._save_depth = 0
        self.max_objects = max_objects
        self.max_saved_states = max_saved_states

    def _prepare(self, call: Call) -> Call:
        if call.name not in SIGNATURES:
            raise UnsupportedOperation(call.name)
        if len(call.kwargs) != len(call.arguments):
            raise ValueError("Duplicate call arguments")
        bound = SIGNATURES[call.name].bind(self, **call.kwargs)
        bound.apply_defaults()
        arguments = {name: value for name, value in bound.arguments.items() if name != "self"}
        for name, kinds in REFERENCES.get(call.name, {}).items():
            handle = arguments[name]
            if not isinstance(handle, Handle) or handle.owner is not self or self._live.get(handle.serial) != handle:
                raise ValueError(f"Invalid or deleted handle: {name}")
            if handle.kind not in kinds:
                raise ValueError(f"Wrong object type for {call.name}.{name}")
        if call.name in CREATED_KINDS and len(self._live) >= self.max_objects:
            raise ValueError("Object limit exceeded")
        if call.name == "save_dc" and self._save_depth >= self.max_saved_states:
            raise ValueError("Saved-state limit exceeded")
        if call.name == "restore_dc":
            level = arguments["saved_dc"]
            target = level if level > 0 else self._save_depth + level + 1
            if level == 0 or target < 1 or target > self._save_depth:
                raise ValueError("Invalid saved DC reference")
        return Call.make(call.name, **arguments)

    def _commit(self, call: Call) -> Handle | int | None:
        result = None
        if call.name in CREATED_KINDS:
            result = Handle(self._next_handle, CREATED_KINDS[call.name], self)
            self._live[result.serial] = result
            self._next_handle += 1
        elif call.name == "delete_object":
            del self._live[call.kwargs["handle"].serial]
        elif call.name == "save_dc":
            self._save_depth += 1
            result = self._save_depth
        elif call.name == "restore_dc":
            level = call.kwargs["saved_dc"]
            self._save_depth = level - 1 if level > 0 else self._save_depth + level
        self.calls.append(call)
        return result

    def invoke(self, call: Call) -> Handle | int | None:
        return self._commit(self._prepare(call))
