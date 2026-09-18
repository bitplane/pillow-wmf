"""Table-based angular arithmetic used by the native GDI Arc constructor.

These are mathematical lookup tables, not drawing-specific correction data.
See docs/gdi-arcs.md for native path measurements and precision limits.
"""

from math import atan, floor, pi, sin
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


_FLOAT_PI = 3.141592502593994  # Native FP_PI (0x40490fda).
_ATAN = tuple(float32(atan(index / 32) * 180 / pi) for index in range(33))
_SIN = tuple(float32(sin(index * pi / 64)) for index in range(33))
ANGLE_STEP = 90 / 32
_ANGLE_TO_TABLE = float32(1 / ANGLE_STEP)
# Native endpoint evaluation switches at three degrees, not one table cell.
# Run 35106971946 distinguishes 2.9999, 3.0 and 3.0001 degree sweeps.
SHORT_ANGLE = 3.0


def _interpolate(table: tuple[float, ...], position: float) -> float:
    index = min(len(table) - 2, floor(position))
    fraction = position - index
    return float32(table[index] + float32(float32(table[index + 1] - table[index]) * fraction))


def atan2_degrees(y: float, x: float) -> float:
    """Reduce to the arctangent table's [0, 1] ratio interval."""
    x, y = float32(x), float32(y)
    major, minor = max(abs(x), abs(y)), min(abs(x), abs(y))
    if major == 0:
        return 0.0
    angle = _interpolate(_ATAN, float32(float32(minor * 32) / major))
    # Restore the octant with one FLOAT addition, not successive quadrant
    # subtractions (which introduce a different intermediate rounding).
    octant = (x < 0) + 2 * (y < 0) + 4 * (abs(y) > abs(x))
    origin, sign = ((0, 1), (180, -1), (360, -1), (180, 1), (90, -1), (90, 1), (270, 1), (270, -1))[octant]
    return float32(origin + sign * angle)


def sincos_degrees(angle: float, *, accurate=False) -> tuple[float, float]:
    """Return (sine, cosine), with quadrant signs and FLOAT results."""
    sine_sign = -1 if angle < 0 else 1
    cosine_sign = 1
    angle = abs(float32(angle))
    if accurate:
        turns = float32(angle / 360)
        angle = float32((turns - floor(turns)) * 360)
        if angle > 180:
            angle = 360 - angle
            sine_sign *= -1
        if angle > 90:
            angle = 180 - angle
            cosine_sign = -1
        radians = float32(float32(angle * _FLOAT_PI) / 180)
        sine, cosine = radians, 1.0
        power, factorial = radians, 2.0
        for exponent in range(2, 13):
            power = float32(power * radians)
            term = float32(power / factorial)
            if exponent & 2:
                term = -term
            if exponent & 1:
                sine = float32(sine + term)
            else:
                cosine = float32(cosine + term)
            factorial = float32(factorial * (exponent + 1))
    else:
        # GDI quantizes the angle and full-circle lookup position as FLOATs
        # before quadrant reduction. Folding in double precision first loses
        # the native spacing near cardinal angles and changes tangent handles.
        position = float32(float32(angle) * _ANGLE_TO_TABLE)
        quadrant, index = divmod(floor(position), 32)
        fraction = position - floor(position)
        rising = _interpolate(_SIN, index + fraction)
        high, low = _SIN[32 - index], _SIN[31 - index]
        falling = float32(high - float32(float32(high - low) * fraction))
        sine, cosine = (falling, rising) if quadrant & 1 else (rising, falling)
        sine_sign *= -1 if quadrant & 2 else 1
        cosine_sign = -1 if (quadrant + 1) & 2 else 1
    return sine_sign * float32(sine), cosine_sign * float32(cosine)


def arc_control_normals(first: float, last: float, start, end):
    """Intersect endpoint tangents and blend their FLOAT control normals."""
    c0, s0 = start
    c3, s3 = end
    determinant = abs(float32(float32(c0 * s3) - float32(c3 * s0)))
    if determinant <= 2**-16:  # Native FP_EPSILON.
        return start, start, end, end

    tangent = (float32(float32(s3 - s0) / determinant), float32(float32(c0 - c3) / determinant))
    half_angle = float32(float32(last - first) * 0.5)
    # efCos calls efSin(angle + 90), which rounds before table lookup.
    # Selecting vCosSin's cosine result loses that distinct angle spacing.
    half_cosine, _ = sincos_degrees(float32(half_angle + 90))
    half_cosine = abs(half_cosine)
    weight = float32(float32(float32(4 / 3) * half_cosine) / float32(1 + half_cosine))
    remainder = float32(1 - weight)

    def control(normal):
        # Native evaluates a weighted sum, not n + weight*(tangent - n).
        return tuple(float32(float32(remainder * n) + float32(weight * t)) for n, t in zip(normal, tangent))

    return start, control(start), control(end), end
