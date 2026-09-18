"""Bounded RLE4/RLE8 command decoding in bottom-up storage coordinates."""

from .wmf.binary import FormatError


def decode_rle(data, width, height, depth):
    if depth not in (4, 8) or width <= 0 or height <= 0:
        raise ValueError("RLE requires positive dimensions and 4/8-bit pixels")
    output = bytearray(width * height)
    coverage = bytearray(width * height)
    x = y = cursor = 0

    def take(count):
        nonlocal cursor
        if cursor + count > len(data):
            raise FormatError("Truncated DIB RLE command")
        value = data[cursor : cursor + count]
        cursor += count
        return value

    while cursor < len(data):
        count, value = take(2)
        if count:
            if depth == 8:
                values = bytes((value,)) * count
            else:
                pair = bytes((value >> 4, value & 15))
                values = (pair * ((count + 1) // 2))[:count]
        elif value == 0:
            x, y = 0, y + 1
            if y > height:
                raise FormatError("DIB RLE row outside bitmap")
            continue
        elif value == 1:
            return output, coverage
        elif value == 2:
            dx, dy = take(2)
            x, y = x + dx, y + dy
            if x > width or y >= height:
                raise FormatError("DIB RLE delta outside bitmap")
            continue
        else:
            count = value
            size = (count * depth + 7) // 8
            literal = take((size + 1) & ~1)
            if depth == 8:
                values = literal[:count]
            else:
                values = bytes(nibble for byte in literal for nibble in (byte >> 4, byte & 15))[:count]
        if x + count > width or y >= height:
            raise FormatError("DIB RLE run outside bitmap")
        output[y * width + x : y * width + x + count] = values
        coverage[y * width + x : y * width + x + count] = b"\1" * count
        x += count
    raise FormatError("Missing DIB RLE end-of-bitmap")
