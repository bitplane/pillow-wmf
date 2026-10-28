"""A non-rendering GDI backend retaining a diagnostic history of requested calls.

This does not emulate mapping, selected-object deletion quirks, clipping,
palette realization or pixel effects.
"""

from .execution import CREATED_KINDS as CREATED_KINDS
from .execution import REFERENCES as REFERENCES
from .execution import ExecutionContext
from .limits import DEFAULT_LIMITS


class TraceContext(ExecutionContext[None]):
    def __init__(
        self,
        *,
        max_objects: int = DEFAULT_LIMITS.max_objects,
        max_saved_states: int = DEFAULT_LIMITS.max_saved_states,
        trace_calls: bool = True,
    ):
        super().__init__(max_objects=max_objects, max_saved_states=max_saved_states, trace_calls=trace_calls)
