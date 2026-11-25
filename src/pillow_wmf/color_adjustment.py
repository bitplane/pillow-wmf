"""COLORADJUSTMENT as native HALFTONE stretching applies it.

Each channel is mapped independently on the 0..1 scale: the reference black
and white levels stretch it, the channel's gamma raises it to a power,
CA_LOG_FILTER replaces it with log8(1 + 7 * value), contrast multiplies it
by exp(0.0148885 * contrast), brightness adds 0.375 * brightness / 100, and
CA_NEGATIVE inverts it. The result is clamped and rounded to the nearest
8-bit level. The order of the gamma, filter and contrast steps relative to
each other is unverified in combination.

Colourfulness, red-green tint and illuminants other than the default mix
the channels: the source is first mapped through the colour engine
(``color_engine.py``), and the per-channel tables then apply to the
mapped colours.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from math import exp, floor, log

from .color_engine import colour_map, uses_engine

CA_NEGATIVE, CA_LOG_FILTER = 1, 2
# Native contrast is exponential: +100 multiplies by about 4.4313.
CONTRAST_EXPONENT = 0.0148885


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
        black, white = self.black / 10000, self.white / 10000
        factor, offset = exp(CONTRAST_EXPONENT * self.contrast), 0.375 * self.brightness / 100

        def level(value, gamma):
            v = min(1.0, max(0.0, (value / 255 - black) / (white - black))) if white > black else float(value >= 255)
            v = v ** (gamma / 10000)
            if self.flags & CA_LOG_FILTER:
                v = log(1 + 7 * v) / log(8)
            v = v * factor + offset
            if self.flags & CA_NEGATIVE:
                v = 1 - v
            return floor(min(1.0, max(0.0, v)) * 255 + 0.5)

        return tuple(tuple(level(value, gamma) for value in range(256)) for gamma in self.gamma)

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
