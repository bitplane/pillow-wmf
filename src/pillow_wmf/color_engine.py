"""The colour engine native HALFTONE stretching uses for colourfulness, tint and illuminants.

These adjustments mix channels, so native GDI realizes them with a colour
map instead of per-channel tables:

1. Each source pixel is quantized to 5 bits per channel with an ordered
   dither anchored at source pixel (0, 0). A channel byte ``v`` becomes
   ``(256 + round(v * 7935 / 255) - d) >> 8`` with one threshold ``d`` per
   pixel from a 66 x 65 table (``DITHER``) shared by the three channels.
2. The three 5-bit indexes select one of 32**3 map entries. Each entry is
   the node colour ``(r, g, b) / 31`` converted to CIE XYZ with the sRGB
   primaries and the adjustment's illuminant as white, then to CIE L*u*v*,
   where colourfulness scales and tint rotates the chroma, and back to XYZ
   and sRGB under the D65 device white. Out-of-gamut results are rescaled
   into range, and channels are rounded to bytes.
3. The per-channel tables of ``ColorAdjustment`` (gamma, contrast and the
   rest) then apply to the mapped colours.

The arithmetic is the engine's fixed point: decimals scaled by 10**6
(FD6), with magnitudes rounded half up. Cube roots go through FD6 base-10
logarithms, interpolated per tenth of a mantissa unit between six-digit
values of log10. The thresholds reproduce native output for every 8-bit
sample; ``probe-windows-color-engine.py`` measures them.
"""

from __future__ import annotations

import bisect
import math
from functools import cache

from .bitmap import RGBBitmap

ONE = 1_000_000

# CIE x, y chromaticities in units of 1e-4: sRGB red, green, blue and white.
SRGB = ((6400, 3300), (3000, 6000), (1500, 600), (3127, 3290))
# COLORADJUSTMENT illuminants 1..8: A, B, C, D50, D55, D65, D75 and F2.
# Native B is (0.3489, 0.3520) rather than the tabulated (0.3484, 0.3516).
ILLUMINANTS = (
    (4476, 4074),
    (3489, 3520),
    (3101, 3162),
    (3457, 3585),
    (3324, 3474),
    (3127, 3290),
    (2990, 3149),
    (3721, 3751),
)
DEFAULT_ILLUMINANT = 6

DITHER = bytes.fromhex(
    "018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab0181"
    "20a1088929a9038323a30b8b2aab0101c141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc141"
    "e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc1c131b1119138b9199933b312933bba1b9b31b1"
    "119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b3131f071"
    "d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af071d151"
    "f979d859f373d253fa7bdb5af0f00d8d2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d8d2dac"
    "058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d0dcd4ced6dc445e564ce4fef6fc747e667cd4ced6d"
    "c445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cdcd3dbd1c9d"
    "34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b5"
    "15943fbf1f9f37b616973d3dfd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475"
    "d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fdfd048423a40b8c2cac018222a20a8a2aaa048423a40b8c"
    "2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa0404c444e364cb4c"
    "ec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6b"
    "c242e262ca49e96ac4c434b314943bbc1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a34b314943bbc1c9b"
    "31b212923aba199a34b314943bbc1c9b31b212923aba199a3434f474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5c"
    "f272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af4f40f9030b0088827a8"
    "0e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e"
    "2dae058626a50f0fd050f070c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d050f070c748e868ce4e"
    "ed6ec645e666d050f070c748e868ce4eed6ec645e666d0d040c020a038b818983ebd1e9e36b6169640c020a038b818983ebd"
    "1e9e36b6169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b616964040fe80df60f778d858fe7e"
    "de5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5e"
    "f676d556fefe018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab018120a1088929a9038323a3"
    "0b8b2aab018120a1088929a9038323a30b8b2aab0101c141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363"
    "cb4beb6bc141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc1c131b1119138b9199933b31293"
    "3bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba"
    "1b9b3131f071d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7b"
    "db5af071d151f979d859f373d253fa7bdb5af0f00d8d2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf0787"
    "27a70d8d2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d0dcd4ced6dc445e564ce4fef6fc747"
    "e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667"
    "cdcd3dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b61697"
    "3dbd1c9d34b515943fbf1f9f37b616973d3dfd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757"
    "fd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fdfd048423a40b8c2cac018222a20a8a2aaa"
    "048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa0404"
    "c444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444"
    "e364cb4cec6bc242e262ca49e96ac4c434b314943bbc1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a34b3"
    "14943bbc1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a3434f474d453fc7cdc5cf272d252fa7ada5af474"
    "d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af4f40f90"
    "30b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0"
    "088827a80e8e2dae058626a50f0fd050f070c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d050f070"
    "c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d0d040c020a038b818983ebd1e9e36b6169640c020a0"
    "38b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b616964040fe80df60"
    "f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778"
    "d858fe7ede5ef676d556fefe018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab018120a10889"
    "29a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab0101c141e161c949e969c342e363cb4beb6bc141e161c949"
    "e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc1c131b1119138b9"
    "199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b91999"
    "33b312933bba1b9b3131f071d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af071d151f979d859"
    "f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af0f00d8d2dac058525a50f8f2faf078727a70d8d2dac058525a5"
    "0f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d0dcd4ced6dc445e564"
    "ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4f"
    "ef6fc747e667cdcd3dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf"
    "1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973d3dfd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7f"
    "df5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fdfd048423a40b8c2cac0182"
    "22a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a2"
    "0a8a2aaa0404c444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262"
    "ca49e96ac444e364cb4cec6bc242e262ca49e96ac4c434b314943bbc1c9b31b212923aba199a34b314943bbc1c9b31b21292"
    "3aba199a34b314943bbc1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a3434f474d453fc7cdc5cf272d252"
    "fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7a"
    "da5af4f40f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae0586"
    "26a50f9030b0088827a80e8e2dae058626a50f0fd050f070c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645"
    "e666d050f070c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d0d040c020a038b818983ebd1e9e36b6"
    "169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b61696"
    "4040fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556"
    "fe80df60f778d858fe7ede5ef676d556fefe018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab"
    "018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab0101c141e161c949e969c342e363cb4beb6b"
    "c141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc141e161c949e969c342e363cb4beb6bc1c1"
    "31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1119138b9199933b312933bba1b9b31b1"
    "119138b9199933b312933bba1b9b3131f071d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af071"
    "d151f979d859f373d253fa7bdb5af071d151f979d859f373d253fa7bdb5af0f00d8d2dac058525a50f8f2faf078727a70d8d"
    "2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d8d2dac058525a50f8f2faf078727a70d0dcd4c"
    "ed6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6dc445e564ce4fef6fc747e667cd4ced6d"
    "c445e564ce4fef6fc747e667cdcd3dbd1c9d34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973dbd1c9d"
    "34b515943fbf1f9f37b616973dbd1c9d34b515943fbf1f9f37b616973d3dfd7ddc5df475d555fe7fdf5ff777d757fd7ddc5d"
    "f475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fd7ddc5df475d555fe7fdf5ff777d757fdfd048423a4"
    "0b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c2cac018222a20a8a2aaa048423a40b8c"
    "2cac018222a20a8a2aaa0404c444e364cb4cec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac444e364cb4c"
    "ec6bc242e262ca49e96ac444e364cb4cec6bc242e262ca49e96ac4c434b314943bbc1c9b31b212923aba199a34b314943bbc"
    "1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a34b314943bbc1c9b31b212923aba199a3434f474d453fc7c"
    "dc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5cf272d252fa7ada5af474d453fc7cdc5c"
    "f272d252fa7ada5af4f40f9030b0088827a80e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f9030b0088827a8"
    "0e8e2dae058626a50f9030b0088827a80e8e2dae058626a50f0fd050f070c748e868ce4eed6ec645e666d050f070c748e868"
    "ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d050f070c748e868ce4eed6ec645e666d0d040c020a038b81898"
    "3ebd1e9e36b6169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd1e9e36b6169640c020a038b818983ebd"
    "1e9e36b616964040fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7ede5ef676d556fe80df60f778d858fe7e"
    "de5ef676d556fe80df60f778d858fe7ede5ef676d556fefe018120a1088929a9038323a30b8b2aab018120a1088929a90383"
    "23a30b8b2aab018120a1088929a9038323a30b8b2aab018120a1088929a9038323a30b8b2aab0101"
)
DITHER_WIDTH, DITHER_HEIGHT = 66, 65


def uses_engine(colorfulness: int, tint: int, illuminant: int) -> bool:
    """Whether native stretching maps colours through the engine."""
    return bool(colorfulness or tint or illuminant not in (0, DEFAULT_ILLUMINANT))


# FD6 arithmetic -----------------------------------------------------------------


def _signed(negative, value):
    return -value if negative else value


def mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    negative = (a < 0) != (b < 0)
    a, b = abs(a), abs(b)
    if a == ONE or b == ONE:
        return _signed(negative, a * b // ONE)
    return _signed(negative, (a * b + 500_000) // ONE)


def div(a: int, b: int) -> int:
    if b == 0:
        return -0x80000000 if a < 0 else 0x7FFFFFFF
    negative = b < 0
    b = abs(b)
    if b == ONE:
        return _signed(negative, a)
    if a == 0:
        return 0
    if a < 0:
        negative, a = not negative, -a
    if a == b:
        return _signed(negative, ONE)
    return _signed(negative, (a * ONE + (b >> 1)) // b)


def div_int(a: int, b: int) -> int:
    """An FD6 value over a plain integer, rounded half up."""
    negative = b < 0
    b = abs(b)
    if a == 0:
        return 0
    if a < 0:
        negative, a = not negative, -a
    return _signed(negative, ((b >> 1) + a) // b)


def dot(products, divisor: int = 0) -> int:
    """A sum of FD6 products over 10**6, or over ``divisor`` when one is given."""
    total = sum(a * b for a, b in products)
    negative = total < 0
    total = abs(total)
    if divisor in (0, ONE):
        return _signed(negative, (total + 500_000) // ONE)
    if divisor < 0:
        divisor, negative = -divisor, not negative
    return _signed(negative, (total + (divisor >> 1)) // divisor)


def _mantissa(value: float) -> int:
    return round(math.log10(value) * ONE)


# Six-digit log10 of 1.00 .. 9.99 and, within each, of each tenth step.
MANTISSA = tuple(_mantissa((100 + i) / 100) for i in range(900))
STEPS = tuple(
    tuple(_mantissa((100 + i + (k + 1) / 10) / 100) - _mantissa((100 + i + k / 10) / 100) for k in range(10))
    for i in range(900)
)


def log10(x: int) -> int:
    """The FD6 base-10 logarithm of a positive FD6 value."""
    if x < 1:
        return -6 * ONE
    if x >= 1000 * ONE:
        exponent, n = 3, div_int(x, 10)
    else:
        exponent = len(str(x)) - 7
        n = x * 10 ** (2 - exponent)
    index, fraction = divmod(n, ONE)
    steps = STEPS[index - 100]
    result = MANTISSA[index - 100]
    if fraction:
        tenth = fraction // 100_000
        result += ((steps[tenth] * (fraction % 100_000) >> 1) + 25_000) // 50_000 + sum(steps[:tenth])
    return result + exponent * ONE


def antilog(value: int) -> int:
    """The FD6 power of ten of an FD6 logarithm below one."""
    if value < -5_999_999:
        return 1
    exponent = 0
    if value < 0:
        exponent = -((999_999 - value) // ONE)
        value -= exponent * ONE
    result = ONE
    if value:
        low = bisect.bisect_right(MANTISSA, value) - 1
        fraction = 0
        remainder = value - MANTISSA[low]
        if remainder:
            count = 0
            for step in STEPS[low]:
                remainder -= step
                if remainder <= 0:
                    break
                count += 1
            fraction = count * 100_000
            if remainder:
                fraction += ((step >> 1) + (remainder + step) * 100_000) // step
            else:
                fraction += 100_000
        result = fraction + (low + 100) * ONE
        exponent -= 2
    if exponent < 0:
        scale = 10**-exponent
        return (scale // 2 + result) // scale
    return result * 10**exponent


def cube_root(x: int) -> int:
    return antilog(div_int(log10(x), 3)) if x > 0 else 0


# Colour spaces --------------------------------------------------------------------


def _inverse(matrix):
    """Gauss-Jordan inversion with partial pivoting in FD6."""
    a = [list(row) for row in matrix]
    b = [[ONE if i == j else 0 for j in range(3)] for i in range(3)]
    for column in range(3):
        pivot = column
        for row in range(column + 1, 3):
            if abs(a[row][column]) > abs(a[pivot][column]):
                pivot = row
        if a[pivot][column] == 0:
            continue
        a[column], a[pivot] = a[pivot], a[column]
        b[column], b[pivot] = b[pivot], b[column]
        value = a[column][column]
        a[column] = [div(v, value) for v in a[column]]
        b[column] = [div(v, value) for v in b[column]]
        for row in range(3):
            factor = a[row][column]
            if row != column and factor:
                a[row] = [a[row][k] - mul(a[column][k], factor) for k in range(3)]
                b[row] = [b[row][k] - mul(b[column][k], factor) for k in range(3)]
    return b


def _space(white, *, inverse=False):
    """sRGB primaries with ``white``: the RGB-to-XYZ matrix (or its inverse) and u'n, v'n."""
    (xr, yr), (xg, yg), (xb, yb) = ((x * 100, y * 100) for x, y in SRGB[:3])
    xw, yw = (v * 100 for v in white)
    determinant = dot([(xr, yg - yb), (xg, yb - yr), (xb, yr - yg)], ONE)
    divisor = mul(yw, determinant)
    sr = dot([(xw, yg - yb), (-yw, xg - xb), (xg, yb), (-xb, yg)], divisor)
    sg = dot([(xw, yb - yr), (-yw, xb - xr), (-xr, yb), (xb, yr)], divisor)
    sb = dot([(xw, yr - yg), (-yw, xr - xg), (xr, yg), (-xg, yr)], divisor)
    matrix = (
        (mul(xr, sr), mul(xg, sg), mul(xb, sb)),
        (mul(yr, sr), mul(yg, sg), mul(yb, sb)),
        (mul(ONE - yr - xr, sr), mul(ONE - yg - xg, sg), mul(ONE - yb - xb, sb)),
    )
    wx, wy, wz = (sum(row) for row in matrix)
    if wy != ONE:
        wx, wz = (div(wx, wy), div(wz, wy)) if wy else (0, 0)
        wy = ONE
    denominator = wx + (wz + wy * 5) * 3
    return (_inverse(matrix) if inverse else matrix), div(wx * 4, denominator), div(wy * 9, denominator)


SINES = tuple(round(math.sin(math.radians(degree)) * ONE) for degree in range(91))


def _tint(tint):
    """The sine and cosine of a tint's chroma rotation, 0.6 degrees per step."""
    negative = tint < 0
    tenths = abs(tint) * 6
    whole, tenth = divmod(tenths, 10)
    sine = SINES[whole]
    if tenth:
        sine += ((SINES[whole + 1] - sine) * tenth + 5) // 10
        whole, tenth = whole + 1, 10 - tenth
    cosine = SINES[90 - whole]
    if tenth:
        cosine += ((SINES[91 - whole] - cosine) * tenth + 5) // 10
    return (sine if negative else -sine), cosine


def _rescale(rgb):
    low, high = min(rgb), max(rgb)
    if high <= ONE and low >= 0:
        return rgb
    if low >= ONE:
        return [ONE] * 3
    if high < 1:
        return [0] * 3
    high = max(high, ONE)
    offset = min(low, 0)
    return [div(v - offset, high - offset) for v in rgb]


@cache
def colour_map(colorfulness: int, tint: int, illuminant: int) -> bytes:
    """The 32**3 mapped colours as RGB bytes, red index fastest."""
    white = ILLUMINANTS[(illuminant or DEFAULT_ILLUMINANT) - 1]
    source, u_source, v_source = _space(white)
    device, u_device, v_device = _space(SRGB[3], inverse=True)
    chroma = colorfulness * 10_000 + ONE
    sine, cosine = _tint(tint) if tint else (0, ONE)
    terms = 2 if tint else 1
    first = (mul(chroma, cosine), mul(chroma, -sine))
    second = (mul(chroma, cosine), mul(chroma, sine))
    channels = [
        [tuple(mul(source[row][channel], div(i, 31)) for row in range(3)) for i in range(32)] for channel in range(3)
    ]
    result = bytearray()
    for b in range(32):
        for g in range(32):
            for r in range(32):
                x, y, z = (channels[0][r][k] + channels[1][g][k] + channels[2][b][k] for k in range(3))
                denominator = x + (z + y * 5) * 3
                u, v = div(x * 4, denominator), div(y * 9, denominator)
                lightness = mul(y, 9_033_000) if y < 8857 else mul(cube_root(y), 1_160_000) - 160_000
                scale = lightness * 13
                us, vs = mul(scale, u - u_source), mul(scale, v - v_source)
                du = dot(list(zip(first, (us, vs), strict=True))[:terms], scale)
                dv = dot(list(zip(second, (vs, us), strict=True))[:terms], scale)
                v_new = v_device + dv
                q = 0x7FF89EC0 if v_new < 0 else div(y * 9, v_new)
                if q < 0:
                    q = 0x7FF89EC0
                u_new = u_device + du
                x_new = 0 if u_new < 0 else div_int(mul(q, u_new), 4)
                z_new = div_int(q - 15 * y - x_new, 3)
                rgb = _rescale([dot(zip(row, (x_new, y, z_new), strict=True)) for row in device])
                result += bytes(mul(c, 255) for c in rgb)
    return bytes(result)


INDEX = tuple(256 + round(v * 7935 / 255) for v in range(256))


class MappedBitmap:
    """A source bitmap seen through the engine, dithered as native scans are read.

    Each read scan advances the dither one row. ``row_offset`` counts the
    scans read before source row 0; rows outside the bitmap repeat its
    nearest edge row, each with its own dither row.
    """

    virtual_rows = True

    def __init__(self, bitmap: RGBBitmap, table: bytes, row_offset: int):
        self.bitmap, self.table, self.row_offset = bitmap, table, row_offset
        self.width, self.height = bitmap.width, bitmap.height
        self.rows: dict[int, bytes] = {}

    def row(self, y: int) -> bytes:
        cached = self.rows.get(y)
        if cached is None:
            source = max(0, min(self.height - 1, y))
            pixels = self.bitmap.pixels[source * self.width * 3 : (source + 1) * self.width * 3]
            phase = (y + self.row_offset) % DITHER_HEIGHT
            dither = DITHER[phase * DITHER_WIDTH : (phase + 1) * DITHER_WIDTH]
            table, result = self.table, bytearray(len(pixels))
            for x in range(self.width):
                d = dither[x % DITHER_WIDTH]
                r, g, b = ((INDEX[c] - d) >> 8 for c in pixels[x * 3 : x * 3 + 3])
                entry = (r + 32 * g + 1024 * b) * 3
                result[x * 3 : x * 3 + 3] = table[entry : entry + 3]
            cached = self.rows[y] = bytes(result)
        return cached

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        return tuple(self.row(y)[x * 3 : x * 3 + 3])

    def materialize(self) -> RGBBitmap:
        pixels = b"".join(self.row(y) for y in range(self.height))
        return RGBBitmap(self.width, self.height, pixels, self.bitmap.coverage)


def map_bitmap(bitmap: RGBBitmap, colorfulness: int, tint: int, illuminant: int, *, row_offset: int = 0):
    """``bitmap`` dithered to 5 bits per channel and mapped through the engine."""
    return MappedBitmap(bitmap, colour_map(colorfulness, tint, illuminant), row_offset)
