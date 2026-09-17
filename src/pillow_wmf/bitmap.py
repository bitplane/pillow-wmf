"""Packed DIB codecs, separate from WMF record framing and brush sampling."""

from dataclasses import dataclass
from struct import pack

from .wmf.objects import BitmapData


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
