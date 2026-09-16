"""Fixed-point outlines for the initial solid GDI pen slice."""

from __future__ import annotations

from math import floor, sqrt

type Point = tuple[int, int]


def line_outline(start: Point, end: Point, width: int, scale_x: float, scale_y: float) -> list[Point]:
    """Widen an axis-aligned or rising line with GDI's rounded endcaps.

    The outline stays in 28.4 device coordinates until scan conversion.
    """
    sx, sy = start[0] * 16, start[1] * 16
    ex, ey = end[0] * 16, end[1] * 16
    rx = round(abs(width * scale_x) * 8)
    ry = round(abs(width * scale_y) * 8)
    if width == 1:
        if sy == ey or sx != ex:
            return [(sx, sy - ry), (sx - rx + 1, sy), (sx, sy + ry), (ex, ey + ry), (ex + rx - 1, ey), (ex, ey - ry)]
        if sx == ex:
            return [(sx + rx, sy), (sx, sy - ry + 1), (sx - rx, sy), (ex - rx, ey), (ex, ey + ry - 1), (ex + rx, ey)]

    cx = floor(rx / sqrt(2))
    cy = floor(ry / sqrt(2))
    if sy == ey:
        return [
            (sx, sy - ry),
            (sx - cx, sy - cy),
            (sx - rx + 1, sy),
            (sx - cx, sy + cy),
            (sx, sy + ry),
            (ex, ey + ry),
            (ex + cx, ey + cy),
            (ex + rx - 1, ey),
            (ex + cx, ey - cy),
            (ex, ey - ry),
        ]
    if sx == ex:
        return [
            (sx + rx, sy),
            (sx + cx, sy - cy),
            (sx, sy - ry + 1),
            (sx - cx, sy - cy),
            (sx - rx, sy),
            (ex - rx, ey),
            (ex - cx, ey + cy),
            (ex, ey + ry - 1),
            (ex + cx, ey + cy),
            (ex + rx, ey),
        ]
    if (ex - sx) * (ey - sy) > 0:
        tx, ty = ((rx - 1) // 16) * 16, ((ry - 1) // 16) * 16
        return [
            (sx + tx, sy - ty),
            (sx, sy - ry + 1),
            (sx - cx, sy - cy),
            (sx - rx + 1, sy),
            (sx - tx, sy + ty),
            (ex - tx, ey + ty),
            (ex, ey + ry - 1),
            (ex + cx, ey + cy),
            (ex + rx - 1, ey),
            (ex + tx, ey - ty),
        ]
    return []
