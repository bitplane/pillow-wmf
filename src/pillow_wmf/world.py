"""World transform arithmetic as GDI performs it, in binary32."""

import struct

from .mapping import IDENTITY_TRANSFORM
from .numeric import float32

Transform = tuple[float, float, float, float, float, float]

MWT_IDENTITY = 1
MWT_LEFTMULTIPLY = 2
MWT_RIGHTMULTIPLY = 3
MWT_SET = 4


def fits_long(value: float) -> bool:
    """Whether GDI's float-to-long conversion accepts ``value``: magnitude below 2**32."""
    exponent = (struct.unpack("<I", struct.pack("<f", value))[0] >> 23) & 0xFF
    return exponent < 159


def multiply(first: Transform, second: Transform, *, checked: bool = True) -> Transform | None:
    """``first`` then ``second`` as native GDI multiplies them, in binary32.

    Without off-diagonal terms on either side the diagonal is a single
    product. Each offset is the second's off-diagonal term on the first's
    other offset, plus the second's offset, plus the diagonal product, in
    that order; a first with no offset passes the second's through. A
    checked product fails (None) when an offset reaches 2**32.
    """
    a11, a12, a21, a22, adx, ady = first
    b11, b12, b21, b22, bdx, bdy = second
    f = float32
    if not (a12 or a21 or b12 or b21):
        m11, m12, m21, m22 = f(b11 * a11), 0.0, 0.0, f(b22 * a22)
    else:
        m11 = f(f(b21 * a12) + f(b11 * a11))
        m12 = f(f(b22 * a12) + f(b12 * a11))
        m21 = f(f(b21 * a22) + f(b11 * a21))
        m22 = f(f(b22 * a22) + f(b12 * a21))
    if not adx and not ady:
        return m11, m12, m21, m22, bdx, bdy
    dx = f(f(f(b21 * ady) + bdx) + f(b11 * adx))
    dy = f(f(f(b22 * ady) + bdy) + f(b12 * adx))
    if checked and not (fits_long(dx) and fits_long(dy)):
        return None
    return m11, m12, m21, m22, dx, dy


def in_range(transform: Transform) -> bool:
    """GDI's acceptance of a world transform: invertible, judged in binary32."""
    m11, m12, m21, m22 = transform[:4]
    if not m12 and not m21:
        return bool(m11) and bool(m22)
    if not m11 and not m22:
        return bool(m12) and bool(m21)
    return float32(float32(m22 * m11) - float32(m12 * m21)) != 0


def modified(current: Transform, mode: int, matrix: Transform) -> Transform | None:
    """ModifyWorldTransform on a DC holding ``current``; None when it fails."""
    if mode == MWT_IDENTITY or (mode == MWT_SET and matrix == IDENTITY_TRANSFORM):
        return IDENTITY_TRANSFORM
    if mode == MWT_SET:
        result = matrix
    elif mode in (MWT_LEFTMULTIPLY, MWT_RIGHTMULTIPLY):
        if current == IDENTITY_TRANSFORM:
            result = matrix
        elif mode == MWT_LEFTMULTIPLY:
            result = multiply(matrix, current)
        else:
            result = multiply(current, matrix)
    else:
        return None
    return result if result is not None and in_range(result) else None
