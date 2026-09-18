"""Table-based angular arithmetic used by the native GDI Arc constructor.

These are mathematical lookup tables, not drawing-specific correction data.
See docs/gdi-arcs.md for native path measurements and precision limits.
"""

from math import atan, atan2, cos, floor, pi, sin
from struct import pack, unpack


def circle_control(radius: int, *, upward: bool) -> int:
    """GDI's signed 0.32 circle-inset multiply, expressed as a handle length.

    The complement of the usual cubic circle coefficient is stored as
    0x729d7775, not recomputed from sqrt(2). Arithmetic shifts preserve the
    oriented rounding used by ellipse, rounded-rectangle and pen constructors.
    """
    inset = ((radius if upward else -radius) * 0x729D7775) >> 32
    return radius - inset if upward else radius + inset


def float32(value: float) -> float:
    return unpack("<f", pack("<f", value))[0]


_FLOAT_PI = float32(pi)
_ATAN = tuple(atan(index / 32) for index in range(33))
_SIN = tuple(sin(index * pi / 64) for index in range(33))
_COS = tuple(cos(index * pi / 64) for index in range(33))
ANGLE_STEP = 90 / 32
_ANGLE_TO_TABLE = float32(1 / ANGLE_STEP)
# Native endpoint evaluation switches at three degrees, not one table cell.
# Run 35106971946 distinguishes 2.9999, 3.0 and 3.0001 degree sweeps.
SHORT_ANGLE = 3.0


def _interpolate(table: tuple[float, ...], position: float) -> float:
    index = min(len(table) - 2, floor(position))
    fraction = position - index
    return table[index] * (1 - fraction) + table[index + 1] * fraction


def atan2_degrees(y: float, x: float) -> float:
    """Reduce to the arctangent table's [0, 1] ratio interval."""
    if x == 0:
        radians = atan2(y, x)
    else:
        ratio = abs(y / x)
        inverse = ratio > 1
        if inverse:
            ratio = 1 / ratio
        radians = _interpolate(_ATAN, ratio * 32)
        if inverse:
            radians = pi / 2 - radians
        radians = float32(radians)
        if x < 0:
            radians = pi - radians
        if y < 0:
            radians = -radians
    return (radians * 180 / _FLOAT_PI) % 360


def sincos_degrees(angle: float, *, accurate=False) -> tuple[float, float]:
    """Return (sine, cosine), with quadrant signs and FLOAT results."""
    angle %= 360
    sine_sign = cosine_sign = 1
    if accurate:
        if angle > 180:
            angle = 360 - angle
            sine_sign = -1
        if angle > 90:
            angle = 180 - angle
            cosine_sign = -1
        radians = angle * pi / 180
        sine, cosine = sin(radians), cos(radians)
    else:
        # GDI quantizes the angle and full-circle lookup position as FLOATs
        # before quadrant reduction. Folding in double precision first loses
        # the native spacing near cardinal angles and changes tangent handles.
        position = float32(float32(angle) * _ANGLE_TO_TABLE)
        if position > 64:
            position = 128 - position
            sine_sign = -1
        if position > 32:
            position = 64 - position
            cosine_sign = -1
        sine, cosine = _interpolate(_SIN, position), _interpolate(_COS, position)
    return sine_sign * float32(sine), cosine_sign * float32(cosine)
