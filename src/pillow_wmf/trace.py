"""A non-rendering GDI backend retaining a diagnostic history of requested calls.

This does not emulate mapping, selected-object deletion quirks, clipping,
palette realization or pixel effects.
"""

from .execution import CREATED_KINDS as CREATED_KINDS
from .execution import REFERENCES as REFERENCES
from .execution import ExecutionContext


class TraceContext(ExecutionContext[None]):
    def __init__(self, *, trace_calls=True, **limits):
        super().__init__(trace_calls=trace_calls, **limits)
