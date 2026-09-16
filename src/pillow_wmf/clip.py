"""Immutable application clipping in device coordinates.

The bitmap bounds are applied when pixels are written. They must not trim an
application clip: a later OffsetClipRgn can move an off-surface clip into view.
"""

from dataclasses import dataclass

type Rectangle = tuple[int, int, int, int]


@dataclass(frozen=True)
class ClipRegion:
    constraints: tuple[tuple[bool, Rectangle], ...] = ()

    def contains(self, x: int, y: int) -> bool:
        return all(
            (left <= x < right and top <= y < bottom) == include
            for include, (left, top, right, bottom) in self.constraints
        )

    def intersect(self, rectangle: Rectangle) -> "ClipRegion":
        return ClipRegion(self.constraints + ((True, rectangle),))

    def exclude(self, rectangle: Rectangle) -> "ClipRegion":
        return ClipRegion(self.constraints + ((False, rectangle),))

    def offset(self, dx: int, dy: int) -> "ClipRegion":
        return ClipRegion(
            tuple(
                (include, (left + dx, top + dy, right + dx, bottom + dy))
                for include, (left, top, right, bottom) in self.constraints
            )
        )
