"""Native source scan fixup, before HALFTONE resampling.

FixupColorScan detects alternating 2x2 cells. Extended checker runs collapse to
their rounded mean; otherwise the brighter diagonal is blended with its four
surrounding samples. Decisions use original scans, writes accumulate in scan
order. Border lookahead reflects the adjacent row/pixel, not the edge itself.
"""

from .bitmap import RGBBitmap


def fixup_bitmap(bitmap, left=0, top=0, right=None, bottom=None):
    right = bitmap.width if right is None else right
    bottom = bitmap.height if bottom is None else bottom
    if right - left < 2 or bottom - top < 2:
        return bitmap
    pixels = bytearray(bitmap.pixels)

    def raw(x, y):
        x = 2 * left - x if x < left else 2 * (right - 1) - x if x >= right else x
        y = 2 * top - y if y < top else 2 * (bottom - 1) - y if y >= bottom else y
        return bitmap.pixel(x, y)

    def put(x, y, color):
        offset = (y * bitmap.width + x) * 3
        pixels[offset : offset + 3] = bytes(color)

    def blend(x, y, neighbours):
        offset = (y * bitmap.width + x) * 3
        put(x, y, tuple((12 * pixels[offset + c] + sum(n[c] for n in neighbours) + 8) >> 4 for c in range(3)))

    for y in range(top + 1, bottom):
        for x in range(left, right - 1):
            a, b = raw(x, y - 1), raw(x + 1, y - 1)
            c, d = raw(x, y), raw(x + 1, y)
            if a == b or a != d or b != c:
                continue
            horizontal = raw(x - 1, y - 1) == b and raw(x - 1, y) == a and raw(x + 2, y - 1) == a and raw(x + 2, y) == b
            vertical = raw(x, y - 2) == b and raw(x + 1, y - 2) == a and raw(x, y + 1) == a and raw(x + 1, y + 1) == b
            if horizontal or vertical:
                average = tuple((u + v + 1) >> 1 for u, v in zip(a, b, strict=True))
                for px, py in ((x, y - 1), (x + 1, y - 1), (x, y), (x + 1, y)):
                    put(px, py, average)
            elif 4 * a[0] + 8 * a[1] + a[2] >= 4 * b[0] + 8 * b[1] + b[2]:
                blend(x, y - 1, (raw(x, y + 1), raw(x + 2, y - 1), b, c))
                blend(x + 1, y, (raw(x + 1, y - 2), raw(x - 1, y), b, c))
            else:
                blend(x + 1, y - 1, (raw(x + 1, y + 1), raw(x - 1, y - 1), a, d))
                blend(x, y, (raw(x, y - 2), raw(x + 2, y), a, d))
    return RGBBitmap(bitmap.width, bitmap.height, bytes(pixels))
