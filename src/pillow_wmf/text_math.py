"""Shared fixed-point font rotation for glyph realization and placement."""

from .gdi_math import sincos_degrees
from .mapping import rounded


def text_rotation(escapement):
    """Share the font scaler's 16.16 rotation with baseline placement."""
    angle = (escapement + 1800) % 3600 - 1800
    sine, cosine = sincos_degrees(angle / 10, accurate=bool(angle % 900))
    return rounded(sine * 65536) / 65536, rounded(cosine * 65536) / 65536
