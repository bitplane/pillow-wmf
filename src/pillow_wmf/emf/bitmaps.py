"""Bitmap transfers, masked and blended transfers, bitmap brushes and extended pens.

Each record addresses a BitmapInfo header and pixel bits by record offset.
Both stay undecoded bytes here.
"""

import struct
from dataclasses import dataclass
from typing import ClassVar

from ..binary import FormatError, Limits, Reader, pack
from .constants import RecordType
from .records import ENVELOPE_SIZE, OffsetRecord, define, register

BOUNDS = ("bounds_left", "bounds_top", "bounds_right", "bounds_bottom")
SOURCE = ("bitmap_offset", "bitmap_size", "bits_offset", "bits_size")
SOURCE_XFORM = ("src_m11", "src_m12", "src_m21", "src_m22", "src_dx", "src_dy")


class BitmapRecord(OffsetRecord):
    @property
    def bitmap_info(self) -> bytes:
        """The BitmapInfo header and colour table, or b"" when absent."""
        return self.blob(self.bitmap_offset, self.bitmap_size)

    @property
    def bits(self) -> bytes:
        return self.blob(self.bits_offset, self.bits_size)


class MaskedBitmapRecord(BitmapRecord):
    @property
    def mask_info(self) -> bytes:
        """The mask's BitmapInfo, or b"" when the record has no mask."""
        return self.blob(self.mask_offset, self.mask_size)

    @property
    def mask_bits(self) -> bytes:
        return self.blob(self.mask_bits_offset, self.mask_bits_size)


BLIT = (*BOUNDS, "x", "y", "width", "height", "rop", "src_x", "src_y", *SOURCE_XFORM, "background", "usage", *SOURCE)
SOURCE_BLOCK = (*SOURCE_XFORM, "background", "usage", *SOURCE)
MASK = ("mask_x", "mask_y", "mask_usage", "mask_offset", "mask_size", "mask_bits_offset", "mask_bits_size")

# (class name, record type, struct layout, field names), MS-EMF 2.3.1 and 2.3.7
TABLE = (
    ("BitBlt", RecordType.BITBLT, "4i4iI2i6fII4I", BLIT),
    ("StretchBlt", RecordType.STRETCHBLT, "4i4iI2i6fII4I2i", (*BLIT, "src_width", "src_height")),
    (
        "StretchDIBits",
        RecordType.STRETCHDIBITS,
        "4i2i4i4III2i",
        (*BOUNDS, "x", "y", "src_x", "src_y", "src_width", "src_height", *SOURCE, "usage", "rop", "width", "height"),
    ),
    (
        "SetDIBitsToDevice",
        RecordType.SETDIBITSTODEVICE,
        "4i2i4i4I3I",
        (*BOUNDS, "x", "y", "src_x", "src_y", "src_width", "src_height", *SOURCE, "usage", "start_scan", "scan_count"),
    ),
    ("CreateMonoBrush", RecordType.CREATEMONOBRUSH, "6I", ("object_index", "usage", *SOURCE)),
    ("CreateDIBPatternBrushPt", RecordType.CREATEDIBPATTERNBRUSHPT, "6I", ("object_index", "usage", *SOURCE)),
)

for _row in TABLE:
    globals()[_row[0]] = define(__name__, *_row, base=BitmapRecord)

MaskBlt = define(
    __name__,
    "MaskBlt",
    RecordType.MASKBLT,
    "4i4iI2i6fII4I2iI4I",
    (*BOUNDS, "x", "y", "width", "height", "rop", "src_x", "src_y", *SOURCE_BLOCK, *MASK),
    base=MaskedBitmapRecord,
)
PlgBlt = define(
    __name__,
    "PlgBlt",
    RecordType.PLGBLT,
    "4i6i4i6fII4I2iI4I",
    (*BOUNDS, "x0", "y0", "x1", "y1", "x2", "y2", "src_x", "src_y", "src_width", "src_height", *SOURCE_BLOCK, *MASK),
    base=MaskedBitmapRecord,
)
AlphaBlend = define(
    __name__,
    "AlphaBlend",
    RecordType.ALPHABLEND,
    "4i4iI2i6fII4I2i",
    (*BOUNDS, "x", "y", "width", "height", "blend", "src_x", "src_y", *SOURCE_BLOCK, "src_width", "src_height"),
    base=BitmapRecord,
)
TransparentBlt = define(
    __name__,
    "TransparentBlt",
    RecordType.TRANSPARENTBLT,
    "4i4iI2i6fII4I2i",
    (*BOUNDS, "x", "y", "width", "height", "transparent", "src_x", "src_y", *SOURCE_BLOCK, "src_width", "src_height"),
    base=BitmapRecord,
)


@register
@dataclass(frozen=True)
class ExtCreatePen(BitmapRecord):
    """EMR_EXTCREATEPEN with its LogPenEx; a pattern brush bitmap may follow."""

    kind: ClassVar[RecordType] = RecordType.EXTCREATEPEN
    object_index: int
    bitmap_offset: int
    bitmap_size: int
    bits_offset: int
    bits_size: int
    style: int
    width: int
    brush_style: int
    color: int
    hatch: int
    style_entries: tuple[int, ...] = ()
    data: bytes = b""
    wire_layout: ClassVar[str] = "5I5I"
    fields: ClassVar[tuple[str, ...]] = (
        "object_index",
        *SOURCE,
        "style",
        "width",
        "brush_style",
        "color",
        "hatch",
    )

    def data_offset(self) -> int:
        return ENVELOPE_SIZE + struct.calcsize("<" + self.wire_layout) + 4 + 4 * len(self.style_entries)

    def payload(self) -> bytes:
        entries = pack(f"I{len(self.style_entries)}I", len(self.style_entries), *self.style_entries)
        return pack(self.wire_layout, *(getattr(self, name) for name in self.fields)) + entries + self.data

    @classmethod
    def read(cls, reader: Reader, limits: Limits):
        values = dict(zip(cls.fields, reader.unpack(cls.wire_layout), strict=True))
        count = reader.unpack("I")[0]
        if count > reader.remaining // 4:
            raise FormatError("Style entries exceed record")
        return cls(**values, style_entries=reader.unpack(f"{count}I"), data=reader.rest())
