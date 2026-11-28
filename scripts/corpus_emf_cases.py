"""EMF boundary cases observed in external EMF corpora.

Each case is a small EMF on a 64x64 reference-pixel canvas: geometric pens of
zero width, AlphaBlend calls with nonzero BlendFlags (as Windows applications
write them) and records whose size field is invalid after valid drawing.
"""

import struct

from emf_feature_fixtures import argb_dib, source_fields

from pillow_wmf.emf import Metafile, bitmaps, fixed, variable
from pillow_wmf.mapping import REFERENCE_DEVICE

SIZE = 64
PS_GEOMETRIC, PS_DASH, PS_ENDCAP_FLAT, PS_JOIN_MITER = 0x00010000, 1, 0x0200, 0x2000
BS_SOLID = 0


def metafile(records):
    (pixels_x, pixels_y), (mm_x, mm_y) = REFERENCE_DEVICE.pixels, REFERENCE_DEVICE.millimetres
    frame = (0, 0, round(SIZE * mm_x * 100 / pixels_x), round(SIZE * mm_y * 100 / pixels_y))
    return Metafile.build(records, frame=frame, bounds=(0, 0, SIZE - 1, SIZE - 1)).to_bytes()


def zero_width_pen(style):
    """Lines and a closed stroked path drawn with a zero-width geometric pen."""
    pen = bitmaps.ExtCreatePen(1, 0, 0, 0, 0, PS_GEOMETRIC | style, 0, BS_SOLID, 0x000080, 0)
    return metafile(
        [
            pen,
            fixed.SelectObject(1),
            fixed.MoveToEx(4, 4),
            fixed.LineTo(59, 20),
            variable.Polyline16((0, 0, 0, 0), ((4, 30), (30, 26), (59, 34))),
            fixed.BeginPath(),
            fixed.MoveToEx(10, 40),
            variable.PolylineTo16((0, 0, 0, 0), ((50, 40), (50, 58), (10, 58))),
            fixed.CloseFigure(),
            fixed.EndPath(),
            fixed.StrokePath(0, 0, -1, -1),
        ]
    )


def alpha_blend(flags, per_pixel):
    """A blend over a filled square with the given BlendFlags byte."""
    fields, data = source_fields(bitmaps.AlphaBlend, argb_dib(16, 12) if per_pixel else _solid_dib())
    blend = (0x01FF0000 if per_pixel else 0x00800000) | flags << 8
    fields |= {"src_width": 16, "src_height": 12, "blend": blend}
    return metafile(
        [
            fixed.CreateBrushIndirect(1, BS_SOLID, 0x00C000, 0),
            fixed.SelectObject(1),
            fixed.Rectangle(0, 0, 40, 40),
            bitmaps.AlphaBlend(**fields | {"x": 8, "y": 8, "width": 48, "height": 36}, data=data),
        ]
    )


def _solid_dib():
    header = struct.pack("<IiiHHIIiiII", 40, 16, 12, 1, 24, 0, 16 * 12 * 3, 0, 0, 0, 0)
    return header, bytes((0, 0, 255)) * (16 * 12)


def bad_record(size):
    """A rectangle, a record whose size field is ``size``, then a second rectangle."""
    data = bytearray(metafile([fixed.Rectangle(4, 4, 30, 30), fixed.SetBkMode(1), fixed.Rectangle(34, 34, 60, 60)]))
    struct.pack_into("<I", data, _find_record(data, 18) + 4, size)  # EMR_SETBKMODE
    return bytes(data)


def _find_record(data, kind):
    position = 0
    while position < len(data):
        record, size = struct.unpack_from("<II", data, position)
        if record == kind:
            return position
        position += size
    raise ValueError(kind)


CASES = {
    "zero-width-pen-solid": lambda: zero_width_pen(0),
    "zero-width-pen-dash": lambda: zero_width_pen(PS_DASH),
    "zero-width-pen-flat-miter": lambda: zero_width_pen(PS_ENDCAP_FLAT | PS_JOIN_MITER),
    **{
        f"alpha-blend-flags-{flags:02x}-{'pixel' if per_pixel else 'constant'}": (
            lambda flags=flags, per_pixel=per_pixel: alpha_blend(flags, per_pixel)
        )
        for flags in (0x80, 0x01, 0x02, 0x40, 0xFF)
        for per_pixel in (True, False)
    },
    "bad-record-huge-size": lambda: bad_record(0xFFFF0127),
    "bad-record-unaligned-size": lambda: bad_record(10),
    "bad-record-short-size": lambda: bad_record(4),
    "bad-record-zero-size": lambda: bad_record(0),
    "bad-record-past-end": lambda: bad_record(0x1000),
}
