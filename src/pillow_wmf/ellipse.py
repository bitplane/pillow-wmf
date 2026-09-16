"""Construct the exclusive-bound ellipse as a fixed-point device path."""

from math import ceil, floor, sqrt

from .geometry import Polygon, flatten_cubic

_SCALE = 16
_CUBIC_CIRCLE_CONTROL = 4 * (sqrt(2) - 1) / 3


def ellipse_path(left: int, top: int, right: int, bottom: int) -> Polygon:
    """Flatten the four GDI-style cubic arcs of an exclusive-bound ellipse."""
    left_fixed, top_fixed = left * _SCALE, top * _SCALE
    right_fixed, bottom_fixed = (right - 1) * _SCALE, (bottom - 1) * _SCALE
    cx, cy = (left_fixed + right_fixed) // 2, (top_fixed + bottom_fixed) // 2
    rx, ry = (right_fixed - left_fixed) // 2, (bottom_fixed - top_fixed) // 2
    horizontal_control = ceil(_CUBIC_CIRCLE_CONTROL * rx)
    vertical_control = floor(_CUBIC_CIRCLE_CONTROL * ry)
    arcs = (
        (
            (right_fixed, cy),
            (right_fixed, cy - vertical_control),
            (cx + horizontal_control, top_fixed),
            (cx, top_fixed),
        ),
        ((cx, top_fixed), (cx - horizontal_control, top_fixed), (left_fixed, cy - vertical_control), (left_fixed, cy)),
        (
            (left_fixed, cy),
            (left_fixed, cy + vertical_control),
            (cx - horizontal_control, bottom_fixed),
            (cx, bottom_fixed),
        ),
        (
            (cx, bottom_fixed),
            (cx + horizontal_control, bottom_fixed),
            (right_fixed, cy + vertical_control),
            (right_fixed, cy),
        ),
    )
    vertices = [arcs[0][0]]
    for arc in arcs:
        vertices.extend(flatten_cubic(arc))
    return vertices[:-1]
