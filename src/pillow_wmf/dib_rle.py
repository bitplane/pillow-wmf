"""Bounded RLE4/RLE8 command decoding in bottom-up storage coordinates."""

from .wmf.binary import FormatError


def decode_rle(data, width, height, depth, *, clip_spans=None):
    """Decode storage rows, optionally clipped during the native scan transfer.

    ``clip_spans(y)`` supplies disjoint half-open intervals in storage coordinates.
    Encoded RLE4 runs restart at their high nibble after left clipping; absolute
    runs retain their source phase. Clipping an already decoded bitmap differs.
    """
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
        encoded = bool(count)
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
        spans = ((0, width),) if clip_spans is None else clip_spans(y)
        for left, right in spans:
            left, right = max(x, left), min(x + count, right)
            if left >= right:
                continue
            source_offset = 0 if encoded else left - x
            start, stop = y * width + left, y * width + right
            output[start:stop] = values[source_offset : source_offset + right - left]
            coverage[start:stop] = b"\1" * (right - left)
        x += count
    raise FormatError("Missing DIB RLE end-of-bitmap")
