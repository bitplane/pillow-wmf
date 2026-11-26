"""COLORADJUSTMENT as native HALFTONE stretching applies it.

Each channel is mapped independently in GDI's six-digit fixed point (FD6,
10**6 is one), in the native table builder's order: the level becomes
``level / 255`` rounded half up; the channel's gamma raises it to a power;
the reference black and white levels stretch it; contrast multiplies it by
1.015 ** contrast; brightness adds 0.375 * brightness / 100;
CA_LOG_FILTER replaces it with log8(1 + 7 * value); it is clamped to 0..1;
CA_NEGATIVE inverts it. The result is rounded to the nearest 8-bit level.

Colourfulness, red-green tint and illuminants other than the default mix
the channels: the source is first mapped through the colour engine
(``color_engine.py``), and the per-channel tables then apply to the
mapped colours.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from .color_engine import ONE, antilog, colour_map, div, log10, mul, uses_engine

CA_NEGATIVE, CA_LOG_FILTER = 1, 2
LOG8 = log10(8 * ONE)


def raise_power(x: int, exponent: int, *, integer: bool = False) -> int:
    """GDI's FD6 RaisePower: through its six-digit logarithm, an exact
    integer exponent multiplying the logarithm directly."""
    if not integer:
        if exponent == ONE:
            return x
        if exponent % ONE == 0:
            integer, exponent = True, exponent // ONE
    elif exponent == 1:
        return x
    negative = x < 1
    x = abs(x)
    if negative and x == 0:
        return 0
    if exponent == 0:
        return -ONE if negative else ONE
    logarithm = ONE if x == 10 * ONE else log10(x)
    logarithm = logarithm * exponent if integer else mul(logarithm, exponent)
    result = antilog(logarithm)
    return -result if negative and integer and exponent % 2 else result


@dataclass(frozen=True)
class ColorAdjustment:
    flags: int = 0
    illuminant: int = 0
    gamma: tuple[int, int, int] = (10000, 10000, 10000)
    black: int = 0
    white: int = 10000
    contrast: int = 0
    brightness: int = 0
    colorfulness: int = 0
    tint: int = 0

    @property
    def neutral(self) -> bool:
        return not self.engine and self.neutral_tables

    @property
    def neutral_tables(self) -> bool:
        return self.tables == NEUTRAL.tables

    @property
    def engine(self) -> bool:
        """Whether colours are mapped through the colour engine before the tables apply."""
        return uses_engine(self.colorfulness, self.tint, self.illuminant)

    @property
    def colour_map(self) -> bytes:
        return colour_map(self.colorfulness, self.tint, self.illuminant)

    @cached_property
    def tables(self) -> tuple[tuple[int, ...], ...]:
        gammas = tuple(div(gamma, 10000) for gamma in self.gamma)
        any_gamma = any(gamma != ONE for gamma in gammas)
        black, white = self.black * 100, self.white * 100
        stretch = black != 0 or white != ONE
        slope = div(ONE, (self.white - self.black) * 100) if stretch else 0
        factor = raise_power(1_015_000, self.contrast, integer=True) if self.contrast else ONE
        offset = self.brightness * 3750

        def level(value, gamma):
            x = 0 if value == 0 else ONE if value == 255 else (value * ONE + 127) // 255
            if any_gamma:
                x = raise_power(x, gamma)
            if stretch:
                x = 0 if x <= black else ONE + mul(x - white, 0) if x >= white else mul(x - black, slope)
            if self.contrast:
                x = mul(x, factor)
            x += offset
            if self.flags & CA_LOG_FILTER:
                x = div(log10(x * 7 + ONE), LOG8)
            x = min(ONE, max(0, x))
            if self.flags & CA_NEGATIVE:
                x = ONE - x
            return (x * 255 + 500_000) // ONE

        return tuple(tuple(level(value, gamma) for value in range(256)) for gamma in gammas)

    def apply(self, color: tuple[int, int, int]) -> tuple[int, int, int]:
        red, green, blue = self.tables
        return red[color[0]], green[color[1]], blue[color[2]]


NEUTRAL = ColorAdjustment()


class AdjustedBitmap:
    """A view of a halftone result with each pixel colour-adjusted."""

    def __init__(self, bitmap, adjustment: ColorAdjustment):
        self.bitmap, self.adjustment = bitmap, adjustment
        self.width, self.height = bitmap.width, bitmap.height

    def __getattr__(self, name):
        return getattr(self.bitmap, name)

    def pixel(self, x, y):
        return self.adjustment.apply(self.bitmap.pixel(x, y))
