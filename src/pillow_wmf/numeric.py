"""Storage precision shared by GDI arithmetic, not a universal rounding rule."""

from struct import Struct

_BINARY32 = Struct("<f")
_WORD = Struct("<I")


def float32(value: float) -> float:
    """Round one arithmetic result to IEEE-754 binary32."""
    return _BINARY32.unpack(_BINARY32.pack(value))[0]


def efloat_sqrt(value: float) -> float:
    """GDI's single-precision square root: the mantissa's root truncated to 24 bits."""
    if value <= 0:
        return 0.0
    bits = _WORD.unpack(_BINARY32.pack(value))[0]
    exponent = bits >> 23 & 0xFF
    odd = (exponent - 1) & 1
    mantissa = (bits & 0x7FFFFF | 0x800000) << (8 if odd else 7)
    exponent = (exponent + 0x7E + (odd ^ 1)) >> 1
    root = remainder = 0
    for _ in range(24):
        remainder = remainder << 2 | mantissa >> 30 & 3
        mantissa = mantissa << 2 & 0xFFFFFFFF
        trial = root << 2 | 1
        root <<= 1
        if trial <= remainder:
            root |= 1
            remainder -= trial
    return _BINARY32.unpack(_WORD.pack(exponent << 23 | root & 0x7FFFFF))[0]
