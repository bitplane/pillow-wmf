"""Legacy device-dependent bitmap storage, independent of DIB headers."""

from dataclasses import dataclass
from struct import pack, unpack_from

from .bitmap import DEFAULT_MAX_BITMAP_PIXELS, RGBBitmap, field_color, validate_masks
from .gdi import UnsupportedOperation
from .wmf.binary import FormatError, ResourceLimitError
from .wmf.objects import BitmapData


@dataclass(frozen=True)
class Bitmap16Layout:
    width: int
    height: int
    depth: int
    stride: int
    data: bytes
    offset: int

    @property
    def complete(self):
        return len(self.data) >= self.offset + self.stride * self.height

    def decode(self, *, colors=None, masks=None, replicate_channels=True):
        if not self.complete:
            raise FormatError("Truncated Bitmap16 pixel array")
        if self.depth <= 8 and colors is None:
            if self.depth != 1:
                raise UnsupportedOperation("Indexed Bitmap16 requires a device colour table")
            colors = ((0, 0, 0), (255, 255, 255))
        if self.depth == 16:
            if masks is None:
                raise UnsupportedOperation("16-bit Bitmap16 requires device channel masks")
            if len(masks) != 3:
                raise ValueError("Three device channel masks required")
            validate_masks(masks, self.depth)
        elif self.depth > 16:
            masks = (0xFF0000, 0xFF00, 0xFF)
        pixels = bytearray()
        for y in range(self.height):
            start = self.offset + y * self.stride
            for x in range(self.width):
                if self.depth <= 8:
                    value = (self.data[start + x * self.depth // 8] >> (8 - self.depth - x * self.depth % 8)) & (
                        (1 << self.depth) - 1
                    )
                    if value >= len(colors):
                        raise FormatError("Bitmap16 pixel outside device colour table")
                    pixels.extend(colors[value])
                else:
                    size = self.depth // 8
                    value = int.from_bytes(self.data[start + x * size : start + (x + 1) * size], "little")
                    pixels.extend(field_color(value, mask, replicate=replicate_channels) for mask in masks)
        return RGBBitmap(self.width, self.height, bytes(pixels))


def read_bitmap16(bitmap, *, native_pattern=False, max_pixels=DEFAULT_MAX_BITMAP_PIXELS):
    if max_pixels < 0:
        raise ValueError("Bitmap pixel limit must be nonnegative")
    if bitmap.format not in ("bitmap16", "pattern16"):
        raise UnsupportedOperation("Expected a Bitmap16 or legacy pattern")
    pattern = bitmap.format == "pattern16"
    if native_pattern and not pattern:
        raise ValueError("Native pattern layout requires pattern16 storage")
    offset = (36 if native_pattern else 32) if pattern else 10
    if len(bitmap.data) < (32 if pattern else 10):
        raise FormatError("Truncated Bitmap16 header")
    _, width, height, width_bytes, planes, depth = unpack_from("<hhhhBB", bitmap.data)
    if width <= 0 or height <= 0 or planes != 1:
        raise FormatError("Invalid Bitmap16 dimensions or plane count")
    if depth not in (1, 4, 8, 16, 24, 32):
        raise UnsupportedOperation(f"Bitmap16 depth {depth}")
    if width * height > max_pixels:
        raise ResourceLimitError("Decoded bitmap pixel limit exceeded")
    stride = ((width * depth + 15) // 16) * 2
    if pattern:
        # CreateBitmapIndirect consumes the stored row pitch; CreateBitmap
        # (used for transfer records) derives it from width and depth instead.
        if width_bytes < stride or width_bytes % 2:
            raise FormatError("Invalid Bitmap16 pattern scanline size")
        stride = width_bytes
    return Bitmap16Layout(width, height, depth, stride, bitmap.data, offset)


def encode_bitmap16(width, height, samples, *, depth=1, pattern=False, native_pattern=False):
    """Write WORD rows without a colour table.

    ``pattern=True`` writes the documented 32-byte Pattern Object header.
    Add ``native_pattern=True`` for Windows' 36-byte playback layout.
    """
    if native_pattern and not pattern:
        raise ValueError("Native pattern layout requires pattern16 storage")
    samples = tuple(samples)
    if not 0 < width <= 32767 or not 0 < height <= 32767 or len(samples) != width * height:
        raise ValueError("Invalid Bitmap16 dimensions or sample count")
    if depth not in (1, 4, 8, 16, 24, 32) or any(not 0 <= v < 1 << depth for v in samples):
        raise ValueError("Invalid Bitmap16 depth or sample")
    stride = ((width * depth + 15) // 16) * 2
    if stride > 32767:
        raise ValueError("Bitmap16 scanline size outside signed WORD range")
    reserved = bytes(26 if native_pattern else 22) if pattern else b""
    data = bytearray(pack("<hhhhBB", 0, width, height, stride, 1, depth) + reserved)
    for y in range(height):
        row = bytearray(stride)
        for x, value in enumerate(samples[y * width : (y + 1) * width]):
            if depth < 8:
                row[x * depth // 8] |= value << (8 - depth - x * depth % 8)
            else:
                size = depth // 8
                row[x * size : (x + 1) * size] = value.to_bytes(size, "little")
        data.extend(row)
    return BitmapData("pattern16" if pattern else "bitmap16", bytes(data))
