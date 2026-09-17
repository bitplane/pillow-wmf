"""Packed DIB codecs, separate from WMF record framing and brush sampling."""

from dataclasses import dataclass
from struct import pack, pack_into, unpack_from

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


def encode_dib(width, height, samples, *, depth, colors=(), masks=None, header_size=40, top_down=False, rle=False):
    """Record exact integer pixels, without quantization or palette selection.

    Indexed samples are table indexes; direct-colour samples are packed words
    in the requested RGB/mask layout. Samples are supplied top-to-bottom.
    """
    samples = tuple(samples)
    if width <= 0 or height <= 0 or len(samples) != width * height:
        raise ValueError("Invalid DIB dimensions or sample count")
    if depth not in (1, 4, 8, 16, 24, 32) or any(not 0 <= s < 1 << depth for s in samples):
        raise ValueError("Invalid DIB sample depth or value")
    if header_size not in (12, 40, 108, 124):
        raise ValueError("Invalid DIB header size")
    if header_size == 12 and (top_down or masks or rle or depth not in (1, 4, 8, 24) or max(width, height) > 65535):
        raise ValueError("Unsupported Core DIB representation")
    if depth <= 8 and (not 0 < len(colors) <= 1 << depth or any(s >= len(colors) for s in samples)):
        raise ValueError("DIB sample outside colour table")
    if any(len(c) != 3 or any(not 0 <= v <= 255 for v in c) for c in colors):
        raise ValueError("Invalid DIB colour table")
    if masks is not None and (depth not in (16, 32) or len(masks) != 3):
        raise ValueError("Bitfields require three masks and 16/32-bit pixels")
    if rle and (depth not in (4, 8) or top_down or masks):
        raise ValueError("RLE requires bottom-up indexed pixels")
    compression = (1 if depth == 8 else 2) if rle else 3 if masks else 0
    payload = bytearray()
    for y in range(height) if top_down else range(height - 1, -1, -1):
        row = samples[y * width : (y + 1) * width]
        if rle:
            # Deterministic encoded runs. More elaborate absolute/delta streams
            # can still be recorded losslessly through BitmapData.
            x = 0
            while x < width:
                end = x + 1
                while end < min(width, x + 255) and row[end] == row[x]:
                    end += 1
                payload.extend((end - x, row[x] if depth == 8 else row[x] * 17))
                x = end
            payload.extend((0, 0))
        else:
            packed = bytearray(((width * depth + 31) // 32) * 4)
            for x, value in enumerate(row):
                if depth < 8:
                    packed[x * depth // 8] |= value << (8 - depth - x * depth % 8)
                else:
                    start = x * (depth // 8)
                    packed[start : start + depth // 8] = value.to_bytes(depth // 8, "little")
            payload.extend(packed)
    if rle:
        payload.extend((0, 1))
    if header_size == 12:
        header = pack("<IHHHH", 12, width, height, 1, depth)
        table = tuple(colors) + ((0, 0, 0),) * ((1 << depth) - len(colors)) if depth <= 8 else tuple(colors)
        return BitmapData("dib", header + bytes(v for r, g, b in table for v in (b, g, r)) + payload)
    header = bytearray(header_size)
    pack_into(
        "<IiiHHIIiiII",
        header,
        0,
        header_size,
        width,
        -height if top_down else height,
        1,
        depth,
        compression,
        len(payload),
        0,
        0,
        len(colors),
        0,
    )
    if header_size >= 108:
        pack_into("<I", header, 56, 0x73524742)  # LCS_sRGB; no external profile.
    if masks:
        if header_size == 40:
            header.extend(pack("<III", *masks))
        else:
            pack_into("<III", header, 40, *masks)
    return BitmapData("dib", bytes(header) + bytes(v for r, g, b in colors for v in (b, g, r, 0)) + payload)


@dataclass(frozen=True)
class DIB24:
    """Validated packed layout, before choosing full-image or scan-band decoding."""

    width: int
    height: int
    top_down: bool
    data: bytes
    offset: int

    @property
    def complete(self) -> bool:
        """Whether the packed object contains the entire declared image."""
        return len(self.data) >= self.offset + ((self.width * 3 + 3) & ~3) * self.height

    def decode(self, rows: int | None = None) -> RGBBitmap:
        """Decode rows from the beginning of the pixel buffer, not a row offset."""
        rows = self.height if rows is None else rows
        if not 0 < rows <= self.height:
            raise ValueError("DIB row count outside image")
        stride = (self.width * 3 + 3) & ~3
        if self.offset + stride * rows > len(self.data):
            raise FormatError("Truncated DIB colour table or pixel array")
        pixels = bytearray(self.width * rows * 3)
        for y in range(rows):
            source_y = y if self.top_down else rows - 1 - y
            start = self.offset + source_y * stride
            row = bytearray(self.data[start : start + self.width * 3])
            row[0::3], row[2::3] = row[2::3], row[0::3]
            pixels[y * self.width * 3 : (y + 1) * self.width * 3] = row
        return RGBBitmap(self.width, rows, bytes(pixels))


def read_dib24(bitmap: BitmapData, *, color_usage: int = 0, max_pixels: int = DEFAULT_MAX_BITMAP_PIXELS) -> DIB24:
    """Validate the supported packed DIB layout without allocating pixels.

    Initially: BITMAPINFOHEADER, BI_RGB, 24 bpp and DIB_RGB_COLORS. Other
    formats remain explicit unsupported operations, not guessed RGB pixels.
    The decoder checks the required pixel extent; bands may omit other rows.
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
    offset = header_size + colors * 4
    # biSizeImage may be zero for BI_RGB. Compute the required extent rather
    # than trusting it as an allocation size or assuming a BMP file header.
    if offset > len(data):
        raise FormatError("Truncated DIB colour table")
    return DIB24(width, height, signed_height < 0, data, offset)


def decode_dib(bitmap: BitmapData, *, color_usage: int = 0, max_pixels: int = DEFAULT_MAX_BITMAP_PIXELS) -> RGBBitmap:
    """Decode a complete packed DIB into immutable top-down RGB pixels."""
    return read_dib24(bitmap, color_usage=color_usage, max_pixels=max_pixels).decode()
