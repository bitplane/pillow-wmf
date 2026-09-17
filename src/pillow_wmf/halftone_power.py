"""Six-decimal GDI tent-weight powers, using reproducible logarithm samples.

The native packed tables encode rounded log10 samples at 0.001 intervals on
[1, 10]. Generate those mathematical values, not copies of proprietary tables.
Only table construction uses Decimal; interpolation and powers use integers.
"""

from decimal import ROUND_HALF_UP, Context, Decimal, localcontext
from functools import lru_cache

FD6 = 1_000_000


def round_ratio(numerator, denominator):
    """Round a signed ratio to nearest, with ties away from zero."""
    if numerator < 0:
        return -((-numerator + denominator // 2) // denominator)
    return (numerator + denominator // 2) // denominator


@lru_cache(maxsize=9001)
def log_sample(index):
    with localcontext(Context(prec=32, rounding=ROUND_HALF_UP)):
        return int(((Decimal(index) / 1000).log10() * FD6).to_integral_value())


def log_fd6(value):
    if not 0 < value <= FD6:
        raise ValueError("Tent logarithm input must be in (0, 1]")
    exponent = 0
    while value < FD6:
        value *= 10
        exponent -= 1
    index, remainder = divmod(value, 1000)
    low = log_sample(index)
    return exponent * FD6 + low + round_ratio((log_sample(index + 1) - low) * remainder, 1000)


def antilog_fd6(value):
    if value > 0:
        raise ValueError("Tent logarithm must be nonpositive")
    if value <= -6 * FD6:
        return 1
    exponent, mantissa = divmod(value, FD6)
    low, high = 1000, 10000
    while high - low > 1:
        middle = (low + high) // 2
        if log_sample(middle) <= mantissa:
            low = middle
        else:
            high = middle
    fraction = round_ratio((mantissa - log_sample(low)) * 100000, log_sample(low + 1) - log_sample(low))
    return round_ratio(low * 100000 + fraction, 10 ** (2 - exponent))


def tent_power(value):
    """Native asymmetric power curve; the exact half-weight bypasses power."""
    if not 0 <= value <= FD6:
        raise ValueError("Tent weight must be in [0, 1]")
    if value in (0, FD6 // 2, FD6):
        return value
    logarithm = log_fd6(value)
    powered = round_ratio(logarithm * FD6, 1414214) if value > FD6 // 2 else round_ratio(logarithm * 1414214, FD6)
    return antilog_fd6(powered)
