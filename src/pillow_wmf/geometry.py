"""Device paths in 28.4 fixed point, retained through scan conversion."""

from __future__ import annotations

from math import floor

type Point = tuple[int, int]
type Polygon = list[Point]


def flatten_cubic(control: tuple[Point, Point, Point, Point]) -> Polygon:
    """Subdivide a cubic to a half-pixel chord-error bound.

    A cubic's deviation is bounded by 3/4 of its largest second difference.
    Eight fixed-point units are half a pixel, hence 3 * difference <= 32.
    Subdivision uses exact dyadic values; only emitted vertices are rounded.
    """
    points: Polygon = []

    def recurse(curve):
        deviation = max(
            abs(curve[index][axis] - 2 * curve[index + 1][axis] + curve[index + 2][axis])
            for index in (0, 1)
            for axis in (0, 1)
        )
        if 3 * deviation <= 32:
            points.append((floor(curve[3][0] + 0.5), floor(curve[3][1] + 0.5)))
            return

        def midpoint(a, b):
            return (a[0] + b[0]) / 2, (a[1] + b[1]) / 2

        a, b, c = (midpoint(curve[i], curve[i + 1]) for i in range(3))
        d, e = midpoint(a, b), midpoint(b, c)
        middle = midpoint(d, e)
        recurse((curve[0], a, d, middle))
        recurse((middle, e, c, curve[3]))

    recurse(control)
    return points


def contains(polygons: tuple[Polygon, ...], x: int, y: int) -> bool:
    """Evaluate even-odd coverage at an integer device-pixel coordinate."""
    px, py = x * 16, y * 16
    enclosed = False
    for polygon in polygons:
        for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
            if (y1 > py) == (y2 > py):
                continue
            cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
            if (cross < 0) if y2 > y1 else (cross > 0):
                enclosed = not enclosed
    return enclosed
