"""Storage precision shared by GDI arithmetic, not a universal rounding rule."""

from struct import Struct

_BINARY32 = Struct("<f")


def float32(value: float) -> float:
    """Round one arithmetic result to IEEE-754 binary32."""
    return _BINARY32.unpack(_BINARY32.pack(value))[0]
