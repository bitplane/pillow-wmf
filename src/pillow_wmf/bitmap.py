"""Packed DIB codecs, separate from WMF record framing and brush sampling."""

from dataclasses import dataclass
from struct import pack, unpack_from

from .gdi import UnsupportedOperation
from .wmf.binary import FormatError
from .wmf.objects import BitmapData

DEFAULT_MAX_BITMAP_PIXELS = 16_777_216


@dataclass(frozen=True)
class RGBBitmap:
    """Immutable, top-down RGB pixels; storage orientation is a codec concern."""

    width: int
    height: int
    pixels: bytes

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Bitmap dimensions must be positive")
        if not isinstance(self.pixels, bytes):
            raise TypeError("Bitmap pixels must be immutable bytes")
        if len(self.pixels) != self.width * self.height * 3:
            raise ValueError("RGB pixel length does not match bitmap dimensions")

    def pixel(self, x: int, y: int) -> tuple[int, int, int]:
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError("Bitmap pixel outside bounds")
        offset = (y * self.width + x) * 3
        return tuple(self.pixels[offset : offset + 3])

    def monochrome(self, background: tuple[int, int, int] = (255, 255, 255)) -> "RGBBitmap":
        """Realize RGB-to-mono colour-key conversion, not a brightness filter."""
        key = bytes(background)
        pixels = bytearray(len(self.pixels))
        for i in range(0, len(self.pixels), 3):
            if self.pixels[i : i + 3] == key:
                pixels[i : i + 3] = b"\xff\xff\xff"
        return RGBBitmap(self.width, self.height, bytes(pixels))


def encode_dib24(bitmap: RGBBitmap, *, top_down: bool = False) -> BitmapData:
    """Build a 40-byte BITMAPINFOHEADER and DWORD-aligned BGR scanlines."""
    width, height = bitmap.width, bitmap.height
    stride = (width * 3 + 3) & ~3
    data = bytearray(
        pack("<IiiHHIIiiII", 40, width, -height if top_down else height, 1, 24, 0, stride * height, 0, 0, 0, 0)
    )
    rows = range(height) if top_down else range(height - 1, -1, -1)
    for y in rows:
        row = bytearray(bitmap.pixels[y * width * 3 : (y + 1) * width * 3])
        row[0::3], row[2::3] = row[2::3], row[0::3]
        data.extend(row)
        data.extend(bytes(stride - width * 3))
    return BitmapData("dib", bytes(data))


def decode_dib(bitmap: BitmapData, *, color_usage: int = 0, max_pixels: int = DEFAULT_MAX_BITMAP_PIXELS) -> RGBBitmap:
    """Decode the supported packed DIB profile without altering encoded data.

    Initially: BITMAPINFOHEADER, BI_RGB, 24 bpp and DIB_RGB_COLORS. Other
    formats remain explicit unsupported operations, not guessed RGB pixels.
    Validate the complete input extent and pixel budget before allocating.
    """
    if max_pixels < 0:
        raise ValueError("Bitmap pixel limit must be nonnegative")
    if bitmap.format != "dib" or color_usage != 0:
        raise UnsupportedOperation("Only RGB-colour packed DIBs are supported")
    data = bitmap.data
    if len(data) < 4:
        raise FormatError("Truncated DIB header size")
    header_size = unpack_from("<I", data)[0]
    if header_size != 40:
        raise UnsupportedOperation(f"DIB header size {header_size}")
    if len(data) < header_size:
        raise FormatError("Truncated BITMAPINFOHEADER")
    _, width, signed_height, planes, depth, compression, _, _, _, colors, _ = unpack_from("<IiiHHIIiiII", data)
    if width <= 0 or signed_height == 0 or planes != 1:
        raise FormatError("Invalid DIB dimensions or plane count")
    if depth != 24 or compression != 0:
        raise UnsupportedOperation(f"DIB depth {depth}, compression {compression}")
    height = abs(signed_height)
    if width * height > max_pixels:
        raise FormatError("Decoded bitmap pixel limit exceeded")
    stride = (width * 3 + 3) & ~3
    offset = header_size + colors * 4
    # biSizeImage may be zero for BI_RGB. Compute the required extent rather
    # than trusting it as an allocation size or assuming a BMP file header.
    if offset + stride * height > len(data):
        raise FormatError("Truncated DIB colour table or pixel array")
    pixels = bytearray(width * height * 3)
    for y in range(height):
        source_y = y if signed_height < 0 else height - 1 - y
        start = offset + source_y * stride
        row = bytearray(data[start : start + width * 3])
        row[0::3], row[2::3] = row[2::3], row[0::3]
        pixels[y * width * 3 : (y + 1) * width * 3] = row
    return RGBBitmap(width, height, bytes(pixels))
