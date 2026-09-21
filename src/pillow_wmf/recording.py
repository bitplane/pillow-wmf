"""Draw and record the same GDI commands through exclusively owned contexts."""

from dataclasses import replace

from .gdi import Call, Handle, UnsupportedOperation
from .trace import CREATED_KINDS, REFERENCES, TraceContext


class RecordingContext(TraceContext):
    """Pair fresh staged backends, rejecting work before either side applies it.

    Issue all drawing through this wrapper after construction. Direct changes
    to the image, backend state or recorder records are not captured. Rendering
    a recording requires the same canvas, initial background and font setup.
    Unexpected execution failures invalidate the pair; no pixel rollback is
    attempted. Failed native creations are rejected rather than recorded with
    potentially different object-slot lifetimes.
    """

    def __init__(self, drawing: TraceContext, recorder: TraceContext):
        if drawing is recorder:
            raise ValueError("Drawing and recording require distinct contexts")
        for backend in (drawing, recorder):
            if not isinstance(backend, TraceContext):
                raise TypeError("Recording requires staged TraceContext backends")
            backend._check_usable()
            if backend.calls or backend._revision or getattr(backend, "records", ()):
                raise ValueError("Recording must start with fresh contexts")
        super().__init__(
            max_objects=min(drawing.max_objects, recorder.max_objects),
            max_saved_states=min(drawing.max_saved_states, recorder.max_saved_states),
        )
        self.drawing = drawing
        self.recorder = recorder
        self._backends = (drawing, recorder)
        self._backend_revisions = tuple(backend._revision for backend in self._backends)
        self._handles = {}
        self._saved = []

    @property
    def image(self):
        """The live image; mutating it directly bypasses recording."""
        self._check_usable()
        return self.drawing.image

    def _check_usable(self):
        super()._check_usable()
        if any(backend._failed for backend in self._backends) or self._backend_revisions != tuple(
            backend._revision for backend in self._backends
        ):
            self._failed = True
            raise RuntimeError("Recording context is unusable: a backend was modified independently")

    def prepare(self, call):
        token = super().prepare(call)
        call = token.call
        prepared = []
        for side, backend in enumerate(self._backends):
            arguments = call.kwargs
            for name in REFERENCES.get(call.name, {}):
                handle = arguments[name]
                arguments[name] = None if handle is None else self._handles[handle][side]
            if call.name == "restore_dc":
                level = arguments["saved_dc"]
                index = level - 1 if level > 0 else len(self._saved) + level
                arguments["saved_dc"] = self._saved[index][side]
            operation = backend.prepare(Call.make(call.name, **arguments))
            if operation.null_object:
                raise UnsupportedOperation("Recording requires successful object creation")
            if not operation.replay_equivalent:
                raise UnsupportedOperation("The recording would replay with different drawing semantics")
            prepared.append(operation)
        return replace(token, payload=tuple(prepared))

    def _check_prepared(self, prepared):
        super()._check_prepared(prepared)
        for backend, operation in zip(self._backends, prepared.payload, strict=True):
            backend._check_prepared(operation)

    def _execute(self, prepared):
        call = prepared.call
        results = tuple(
            backend.apply(operation) for backend, operation in zip(self._backends, prepared.payload, strict=True)
        )
        if call.name in CREATED_KINDS:
            for backend, result in zip(self._backends, results, strict=True):
                if (
                    not isinstance(result, Handle)
                    or result.owner is not backend
                    or result.kind != CREATED_KINDS[call.name]
                ):
                    raise RuntimeError("Backend creation did not return its own correctly typed handle")
                if backend.is_null_object(result):
                    raise RuntimeError("Backend returned an unexpected null handle")
        elif call.name == "save_dc":
            for side, result in enumerate(results):
                if type(result) is not int or result <= 0 or any(frame[side] == result for frame in self._saved):
                    raise RuntimeError("Backend returned an invalid saved-state identifier")
        result = self._commit(call)
        if call.name in CREATED_KINDS:
            self._handles[result] = results
        elif call.name == "delete_object":
            del self._handles[call.kwargs["handle"]]
        elif call.name == "save_dc":
            self._saved.append(results)
        elif call.name == "restore_dc":
            level = call.kwargs["saved_dc"]
            index = level - 1 if level > 0 else len(self._saved) + level
            del self._saved[index:]
        self._backend_revisions = tuple(backend._revision for backend in self._backends)
        return result
