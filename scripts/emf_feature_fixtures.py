"""EMF fixtures for every remaining drawing, state and transfer feature.

Each drawing uses the 128-unit design grid of generate-emf-fixtures.py. Features
whose output depends on the playback transform are also recorded at a
non-integer frame scale.
"""

import math
import struct

from pillow_wmf.emf import Metafile, bitmaps, fixed, system, text, variable
from pillow_wmf.emf.objects import LogFont
from pillow_wmf.mapping import ReferenceDevice

PS_SOLID, PS_DASH, PS_DOT, PS_USERSTYLE, PS_ALTERNATE, PS_NULL = 0, 1, 2, 7, 8, 5
PS_GEOMETRIC = 0x00010000
PS_ENDCAP_ROUND, PS_ENDCAP_SQUARE, PS_ENDCAP_FLAT = 0x0000, 0x0100, 0x0200
PS_JOIN_ROUND, PS_JOIN_BEVEL, PS_JOIN_MITER = 0x0000, 0x1000, 0x2000
BS_SOLID, BS_NULL, BS_HATCHED, BS_DIBPATTERN = 0, 1, 2, 5
HS_HORIZONTAL, HS_BDIAGONAL, HS_DIAGCROSS = 0, 3, 5
DIB_RGB_COLORS, DIB_PAL_COLORS, DIB_PAL_MONO = 0, 1, 2
TRANSPARENT, OPAQUE = 1, 2
ALTERNATE, WINDING = 1, 2
AD_CLOCKWISE = 2
PT_CLOSEFIGURE, PT_LINETO, PT_BEZIERTO, PT_MOVETO = 1, 2, 4, 6
RGN_AND, RGN_OR, RGN_XOR, RGN_DIFF, RGN_COPY = 1, 2, 3, 4, 5
SRCCOPY, PATCOPY, SRCINVERT, DSTINVERT = 0x00CC0020, 0x00F00021, 0x00660046, 0x00550009
STOCK = 0x80000000
DC_BRUSH, DC_PEN, DEFAULT_PALETTE = STOCK | 18, STOCK | 19, STOCK | 15
HALFTONE = 4


def rgb_dib(width, height, colour):
    """A bottom-up 24-bit DIB split into (BitmapInfo, bits)."""
    stride = (width * 3 + 3) & ~3
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, stride * height, 0, 0, 0, 0)
    rows = []
    for y in range(height - 1, -1, -1):
        row = b"".join(bytes(reversed(colour(x, y))) for x in range(width))
        rows.append(row + bytes(stride - len(row)))
    return header, b"".join(rows)


def gradient(x, y):
    return (x * 8) % 256, (y * 10) % 256, ((x + y) * 5 + 40) % 256


def argb_dib(width, height):
    """A bottom-up 32-bit DIB with premultiplied alpha rising left to right."""
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)
    rows = []
    for y in range(height - 1, -1, -1):
        for x in range(width):
            alpha = round(255 * x / (width - 1))
            red, green, blue = 255, (y * 20) % 256, 0
            rows.append(bytes((blue * alpha // 255, green * alpha // 255, red * alpha // 255, alpha)))
    return header, b"".join(rows)


def mono_dib(width, height, bit, colours=((0, 0, 128), (255, 255, 0))):
    stride = ((width + 31) // 32) * 4
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 1, 0, stride * height, 0, 0, 2, 0)
    table = b"".join(bytes((b, g, r, 0)) for r, g, b in colours)
    rows = []
    for y in range(height - 1, -1, -1):
        value = 0
        for x in range(width):
            value |= bit(x, y) << (stride * 8 - 1 - x)
        rows.append(value.to_bytes(stride, "big"))
    return header + table, b"".join(rows)


def region_data(rectangles):
    left = min(r[0] for r in rectangles)
    top = min(r[1] for r in rectangles)
    right = max(r[2] for r in rectangles)
    bottom = max(r[3] for r in rectangles)
    header = struct.pack("<4I4i", 32, 1, len(rectangles), 16 * len(rectangles), left, top, right, bottom)
    return header + b"".join(struct.pack("<4i", *r) for r in rectangles)


def offset_fields(cls, *blocks, extra=0):
    """Offsets and sizes for (info, bits) blocks placed after the fixed fields."""
    offset = 8 + struct.calcsize("<" + cls.wire_layout) + extra
    values, data = [], b""
    for block in blocks:
        values.append((offset + len(data), len(block)))
        data += block
    return values, data


def background_modes(d):
    d.pen(PS_DASH, 0, 0x0000C0)
    d.brush(BS_HATCHED, 0x008000, HS_DIAGCROSS)
    d.add(fixed.SetBkColor(0x80FFFF), fixed.SetBkMode(OPAQUE))
    d.add(fixed.Rectangle(*d.rect(8, 8, 60, 60)))
    d.add(fixed.SetBkMode(TRANSPARENT))
    d.add(fixed.Rectangle(*d.rect(68, 8, 120, 60)))
    d.add(fixed.SetBkColor(0xFF8080), fixed.SetBkMode(OPAQUE), fixed.SetROP2(7))
    d.add(fixed.Ellipse(*d.rect(30, 30, 98, 98)))
    d.add(fixed.SetROP2(13), fixed.SetTextColor(0x0000FF))
    info, bits = mono_dib(8, 8, lambda x, y: (x + y) % 3 == 0)
    d.select(lambda slot: bitmaps.CreateMonoBrush(slot, DIB_PAL_MONO, *_brush_offsets(info, bits)))
    d.add(fixed.Rectangle(*d.rect(8, 68, 60, 120)))
    d.add(fixed.SetBkMode(TRANSPARENT))
    d.add(fixed.Rectangle(*d.rect(68, 68, 120, 120)))


def _brush_offsets(info, bits):
    offset = 8 + struct.calcsize("<" + bitmaps.CreateMonoBrush.wire_layout)
    return offset, len(info), offset + len(info), len(bits), info + bits


def fill_modes(d):
    star = [
        (64 + 50 * math.cos(math.radians(90 + 144 * i)), 60 - 50 * math.sin(math.radians(90 + 144 * i)))
        for i in range(5)
    ]
    points = tuple((d.u(x - 30), d.u(y)) for x, y in star)
    d.brush(BS_SOLID, 0xC08000)
    d.add(fixed.SetPolyFillMode(ALTERNATE), variable.Polygon((0, 0, 0, 0), points))
    d.add(fixed.SetPolyFillMode(WINDING), variable.Polygon16((0, 0, 0, 0), tuple((x + d.u(60), y) for x, y in points)))
    square = ((10, 80), (60, 80), (60, 125), (10, 125))
    inner = ((25, 90), (25, 115), (45, 115), (45, 90))
    same = ((30, 95), (50, 95), (50, 120), (30, 120))
    figures = tuple(tuple((d.u(x), d.u(y)) for x, y in figure) for figure in (square, inner))
    d.add(fixed.SetPolyFillMode(ALTERNATE), variable.PolyPolygon((0, 0, 0, 0), figures))
    figures = tuple(tuple((d.u(x + 64), d.u(y)) for x, y in figure) for figure in (square, same))
    d.add(fixed.SetPolyFillMode(WINDING), variable.PolyPolygon16((0, 0, 0, 0), figures))
    d.add(variable.Polyline((0, 0, 0, 0), ((d.u(4), d.u(126)), (d.u(124), d.u(70)))))


def curves(d):
    def pts(*values):
        return tuple((d.u(x), d.u(y)) for x, y in values)

    d.pen(PS_SOLID, 0, 0x000000)
    d.add(variable.PolyBezier((0, 0, 0, 0), pts((4, 20), (20, 0), (40, 40), (56, 12))))
    d.add(
        variable.PolyBezier16((0, 0, 0, 0), pts((64, 20), (80, 0), (100, 40), (120, 12), (124, 30), (90, 36), (70, 30)))
    )
    d.add(fixed.MoveToEx(d.u(4), d.u(44)))
    d.add(variable.PolyBezierTo((0, 0, 0, 0), pts((20, 34), (30, 60), (50, 44))))
    d.add(variable.PolylineTo((0, 0, 0, 0), pts((58, 56), (40, 60))))
    d.add(variable.PolyBezierTo16((0, 0, 0, 0), pts((30, 70), (10, 50), (6, 62))))
    d.add(fixed.MoveToEx(d.u(70), d.u(44)), variable.PolylineTo16((0, 0, 0, 0), pts((120, 44), (95, 60))))
    d.add(variable.PolyPolyline((0, 0, 0, 0), (pts((64, 64), (80, 70), (64, 76)), pts((90, 64), (100, 76)))))
    d.add(
        fixed.SetROP2(7), variable.PolyPolyline16((0, 0, 0, 0), (pts((104, 64), (124, 76)), pts((104, 76), (124, 64))))
    )
    d.add(fixed.SetROP2(13))
    draw = pts((4, 84), (20, 84), (30, 100), (10, 110), (20, 90), (4, 100))
    types = bytes((PT_MOVETO, PT_LINETO, PT_BEZIERTO, PT_BEZIERTO, PT_BEZIERTO, PT_LINETO | PT_CLOSEFIGURE))
    d.add(variable.PolyDraw((0, 0, 0, 0), draw, types))
    draw = pts((34, 84), (50, 84), (50, 100), (40, 106), (34, 96))
    d.add(variable.PolyDraw16((0, 0, 0, 0), draw, bytes((PT_MOVETO, PT_LINETO, PT_LINETO, PT_MOVETO, PT_LINETO))))
    d.add(fixed.MoveToEx(d.u(60), d.u(90)), fixed.AngleArc(d.u(80), d.u(96), d.u(14), 30.0, 240.0))
    d.add(fixed.LineTo(d.u(124), d.u(84)))
    d.add(
        fixed.ArcTo(*d.rect(100, 84, 124, 108), d.u(124), d.u(96), d.u(100), d.u(96)), fixed.LineTo(d.u(110), d.u(126))
    )
    d.add(fixed.SetArcDirection(AD_CLOCKWISE))
    d.brush(BS_SOLID, 0x80C0FF)
    d.add(fixed.Arc(*d.rect(4, 108, 28, 126), *d.rect(28, 117, 4, 108)))
    d.add(fixed.Pie(*d.rect(32, 108, 56, 126), *d.rect(56, 108, 32, 126)))
    d.add(fixed.Chord(*d.rect(60, 108, 84, 126), *d.rect(84, 112, 60, 126)))
    d.add(fixed.Ellipse(*d.rect(88, 110, 98, 124)), fixed.RoundRect(*d.rect(100, 110, 112, 124), d.u(4), d.u(4)))


def paths(d):
    def pts(*values):
        return tuple((d.u(x), d.u(y)) for x, y in values)

    d.pen(PS_SOLID, 0, 0x000000)
    d.brush(BS_SOLID, 0x60A0FF)
    d.add(fixed.BeginPath(), fixed.MoveToEx(d.u(4), d.u(4)), fixed.LineTo(d.u(40), d.u(10)))
    d.add(variable.PolyBezierTo((0, 0, 0, 0), pts((50, 30), (10, 40), (8, 20))), fixed.CloseFigure())
    d.add(fixed.Ellipse(*d.rect(20, 14, 34, 28)), fixed.EndPath(), fixed.FillPath(*d.rect(0, 0, 0, 0)))
    d.add(fixed.BeginPath(), fixed.Rectangle(*d.rect(48, 4, 80, 36)), fixed.Ellipse(*d.rect(56, 12, 72, 28)))
    d.add(fixed.EndPath(), fixed.StrokeAndFillPath(*d.rect(0, 0, 0, 0)))
    d.add(fixed.SetPolyFillMode(WINDING), fixed.BeginPath(), fixed.RoundRect(*d.rect(88, 4, 124, 36), d.u(10), d.u(10)))
    d.add(fixed.Pie(*d.rect(94, 10, 118, 30), *d.rect(118, 20, 94, 10)), fixed.EndPath(), fixed.FillPath(0, 0, 0, 0))
    d.add(fixed.BeginPath(), fixed.Arc(*d.rect(4, 44, 40, 76), *d.rect(40, 60, 4, 44)), fixed.EndPath())
    d.add(fixed.StrokePath(0, 0, 0, 0))
    d.add(fixed.BeginPath(), variable.PolyBezier((0, 0, 0, 0), pts((48, 60), (60, 30), (80, 90), (84, 50))))
    d.add(fixed.EndPath(), fixed.FlattenPath(), fixed.StrokePath(0, 0, 0, 0))
    style = PS_GEOMETRIC | PS_ENDCAP_FLAT | PS_JOIN_MITER
    d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, style, d.u(6), BS_SOLID, 0x008000, 0))
    d.add(fixed.BeginPath(), fixed.MoveToEx(d.u(92), d.u(46)), fixed.LineTo(d.u(110), d.u(74)))
    d.add(fixed.LineTo(d.u(122), d.u(46)), fixed.EndPath(), fixed.WidenPath())
    d.pen(PS_SOLID, 0, 0x000000)
    d.add(fixed.StrokeAndFillPath(0, 0, 0, 0))
    d.add(fixed.BeginPath(), fixed.Ellipse(*d.rect(8, 84, 56, 124)), fixed.EndPath(), fixed.SelectClipPath(RGN_COPY))
    d.brush(BS_HATCHED, 0x800000, HS_DIAGCROSS)
    d.add(fixed.Rectangle(*d.rect(0, 80, 64, 128)))
    d.add(fixed.BeginPath(), fixed.Rectangle(*d.rect(20, 96, 120, 110)), fixed.EndPath(), fixed.SelectClipPath(RGN_OR))
    d.brush(BS_SOLID, 0x00C0C0)
    d.add(fixed.Rectangle(*d.rect(60, 80, 128, 128)))
    d.add(fixed.BeginPath(), fixed.Rectangle(*d.rect(0, 0, 128, 128)), fixed.AbortPath(), fixed.FillPath(0, 0, 0, 0))


def extended_pens(d):
    def line(points, x, y):
        coordinates = tuple((d.u(px + x), d.u(py + y)) for px, py in points)
        d.add(variable.Polyline((0, 0, 0, 0), coordinates))

    vee = ((0, 0), (12, 22), (24, 0))
    for column, cap in enumerate((PS_ENDCAP_ROUND, PS_ENDCAP_SQUARE, PS_ENDCAP_FLAT)):
        for row, join in enumerate((PS_JOIN_ROUND, PS_JOIN_BEVEL, PS_JOIN_MITER)):
            style = PS_GEOMETRIC | cap | join
            d.select(lambda slot, style=style: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, style, d.u(5), 0, 0x803000, 0))
            line(vee, 6 + 40 * column, 6 + 28 * row)
    d.add(fixed.SetMiterLimit(1))
    style = PS_GEOMETRIC | PS_ENDCAP_FLAT | PS_JOIN_MITER
    d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, style, d.u(4), 0, 0x000080, 0))
    line(((0, 0), (10, 14), (20, 0)), 4, 92)
    d.add(fixed.SetMiterLimit(10))
    line(((0, 0), (10, 14), (20, 0)), 28, 92)
    user = PS_GEOMETRIC | PS_USERSTYLE | PS_ENDCAP_FLAT
    d.select(
        lambda slot: bitmaps.ExtCreatePen(
            slot, 0, 0, 0, 0, user, d.u(3), 0, 0xC00000, 0, (d.u(6), d.u(3), d.u(2), d.u(3))
        )
    )
    line(((0, 0), (40, 0)), 52, 92)
    d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, PS_ALTERNATE, 1, 0, 0x000000, 0))
    line(((0, 0), (40, 0), (40, 8)), 52, 100)
    dashed = PS_GEOMETRIC | PS_DASH | PS_ENDCAP_ROUND
    d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, dashed, d.u(3), 0, 0x008080, 0))
    line(((0, 0), (40, 8)), 52, 112)
    cosmetic = PS_USERSTYLE
    d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, cosmetic, 1, 0, 0x800080, 0, (4, 2)))
    line(((0, 0), (24, 0)), 98, 92)
    d.select(
        lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, PS_GEOMETRIC, d.u(6), BS_HATCHED, 0x0000FF, HS_BDIAGONAL)
    )
    line(((0, 0), (24, 20)), 98, 100)
    info, bits = rgb_dib(4, 4, lambda x, y: (255, 0, 0) if (x + y) % 2 else (0, 0, 255))
    offset = 8 + struct.calcsize("<" + bitmaps.ExtCreatePen.wire_layout) + 4
    style = PS_GEOMETRIC | PS_ENDCAP_FLAT
    pattern = bitmaps.ExtCreatePen
    d.select(
        lambda slot: pattern(
            slot,
            offset,
            len(info),
            offset + len(info),
            len(bits),
            style,
            d.u(6),
            BS_DIBPATTERN,
            DIB_RGB_COLORS,
            0,
            (),
            info + bits,
        )
    )
    line(((0, 0), (110, 0)), 6, 124)


def brushes(d):
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_HATCHED, 0x000080, HS_DIAGCROSS)
    d.add(fixed.Rectangle(*d.rect(4, 4, 40, 40)), fixed.SetBrushOrgEx(3, 5), fixed.Rectangle(*d.rect(44, 4, 80, 40)))
    info, bits = rgb_dib(5, 3, gradient)
    offset = 8 + struct.calcsize("<" + bitmaps.CreateDIBPatternBrushPt.wire_layout)
    d.select(
        lambda slot: bitmaps.CreateDIBPatternBrushPt(
            slot, DIB_RGB_COLORS, offset, len(info), offset + len(info), len(bits), info + bits
        )
    )
    d.add(fixed.Rectangle(*d.rect(84, 4, 124, 40)), fixed.SetBrushOrgEx(0, 0))
    for index in range(6):
        d.add(fixed.SelectObject(STOCK | index), fixed.Rectangle(*d.rect(4 + 20 * index, 46, 22 + 20 * index, 64)))
    for index in range(6, 9):
        d.add(fixed.SelectObject(STOCK | index), fixed.SelectObject(STOCK | 1))
        d.add(fixed.Rectangle(*d.rect(4 + 20 * (index - 6), 70, 22 + 20 * (index - 6), 88)))
    d.add(fixed.SelectObject(DC_BRUSH), fixed.SelectObject(DC_PEN), fixed.Rectangle(*d.rect(64, 70, 100, 88)))
    info, bits = mono_dib(8, 8, lambda x, y: x == y or x == 7 - y)
    d.select(lambda slot: bitmaps.CreateMonoBrush(slot, DIB_PAL_MONO, *_brush_offsets(info, bits)))
    d.add(fixed.SetTextColor(0x0000C0), fixed.SetBkColor(0xC0FFC0), fixed.Rectangle(*d.rect(4, 94, 60, 124)))
    d.add(fixed.SetBrushOrgEx(2, 1), fixed.Rectangle(*d.rect(64, 94, 124, 124)))


def clip_regions(d):
    d.brush(BS_SOLID, 0x2080E0)
    region = variable.ExtSelectClipRgn
    for index, mode in enumerate((RGN_AND, RGN_OR, RGN_XOR, RGN_DIFF)):
        x, y = 4 + 64 * (index % 2), 4 + 44 * (index // 2)
        d.add(fixed.SaveDC(), region(RGN_COPY, region_data([d.rect(x, y, x + 40, y + 30)])))
        d.add(region(mode, region_data([d.rect(x + 20, y + 10, x + 58, y + 40)])))
        d.add(fixed.Rectangle(0, 0, d.extent, d.extent), fixed.RestoreDC(-1))
    d.add(fixed.SaveDC(), fixed.IntersectClipRect(*d.rect(4, 92, 60, 124)), fixed.SetMetaRgn())
    d.add(fixed.IntersectClipRect(*d.rect(30, 80, 128, 110)), fixed.Rectangle(0, 0, d.extent, d.extent))
    d.add(region(RGN_COPY), fixed.Ellipse(*d.rect(0, 88, 70, 128)), fixed.RestoreDC(-1))
    d.add(fixed.SaveDC(), fixed.IntersectClipRect(*d.rect(64, 92, 90, 120)), fixed.OffsetClipRgn(d.u(30), d.u(4)))
    d.add(fixed.Ellipse(*d.rect(60, 88, 128, 128)), fixed.RestoreDC(1))
    d.add(fixed.SaveDC(), fixed.SaveDC(), fixed.IntersectClipRect(0, 0, 1, 1), fixed.RestoreDC(1))
    d.add(fixed.Rectangle(*d.rect(100, 78, 124, 88)))


def regions(d):
    d.add(
        fixed.CreateBrushIndirect(1, BS_SOLID, 0x00A000, 0),
        fixed.CreateBrushIndirect(2, BS_HATCHED, 0xA00000, HS_HORIZONTAL),
    )
    shape = [(4, 4, 40, 20), (10, 20, 60, 40), (30, 40, 44, 58)]

    def placed(dx, dy):
        return region_data([d.rect(x + dx, y + dy, r + dx, b + dy) for x, y, r, b in shape])

    d.add(variable.FillRgn(bounds=(0, 0, 0, 0), brush=1, region=placed(0, 0)))
    d.add(variable.FrameRgn(bounds=(0, 0, 0, 0), brush=2, width=3, height=2, region=placed(64, 0)))
    d.brush(BS_SOLID, 0x0080FF)
    d.add(variable.PaintRgn(bounds=(0, 0, 0, 0), region=placed(0, 64)))
    d.add(fixed.Rectangle(*d.rect(60, 60, 124, 124)))
    d.add(variable.InvertRgn(bounds=(0, 0, 0, 0), region=placed(50, 64)))


def transfer_background(d):
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x80C080)
    d.add(fixed.Rectangle(0, 0, d.extent + 1, d.extent + 1))


SOURCE = rgb_dib(16, 12, gradient)
MASK = mono_dib(16, 12, lambda x, y: (x // 4 + y // 4) % 2, ((0, 0, 0), (255, 255, 255)))


def source_fields(cls, blocks):
    """Zeroed fields with an identity source transform and the blocks' offsets."""
    pairs, data = offset_fields(cls, *blocks)
    fields = dict.fromkeys(cls.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "background": 0xFFFFFF}
    names = ("bitmap_offset", "bitmap_size", "bits_offset", "bits_size")
    names += ("mask_offset", "mask_size", "mask_bits_offset", "mask_bits_size")
    for index, (offset, size) in enumerate(pairs):
        fields |= {names[2 * index]: offset, names[2 * index + 1]: size}
    return fields, data


def mask_blt(masked):
    def draw(d):
        transfer_background(d)
        fields, data = source_fields(bitmaps.MaskBlt, (*SOURCE, *MASK) if masked else SOURCE)
        # MAKEROP4(SRCCOPY, DSTCOPY): the source where the mask is 1, the destination elsewhere.
        fields |= {"x": d.u(8), "y": d.u(8), "width": 16, "height": 12, "rop": 0xAACC0020, "src_x": 1}
        d.add(bitmaps.MaskBlt(**fields, data=data))
        d.add(bitmaps.MaskBlt(**fields | {"x": d.u(64), "rop": 0xCCAA0029 if masked else SRCINVERT}, data=data))

    return draw


def plg_blt(masked):
    def draw(d):
        transfer_background(d)
        fields, data = source_fields(bitmaps.PlgBlt, (*SOURCE, *MASK) if masked else SOURCE)
        fields |= {"x0": d.u(30), "y0": d.u(8), "x1": d.u(110), "y1": d.u(40), "x2": d.u(10), "y2": d.u(70)}
        d.add(bitmaps.PlgBlt(**fields | {"src_width": 16, "src_height": 12}, data=data))
        fields |= {"x0": d.u(120), "y0": d.u(120), "x1": d.u(70), "y1": d.u(120), "x2": d.u(120), "y2": d.u(80)}
        d.add(bitmaps.PlgBlt(**fields | {"src_x": 2, "src_y": 1, "src_width": 10, "src_height": 8}, data=data))

    return draw


def alpha_blend(per_pixel):
    def draw(d):
        transfer_background(d)
        fields, data = source_fields(bitmaps.AlphaBlend, argb_dib(16, 12) if per_pixel else SOURCE)
        blend = 0x01FF0000 if per_pixel else 0x00800000  # AC_SRC_ALPHA, or a constant half.
        fields |= {"src_width": 16, "src_height": 12, "blend": blend}
        d.add(bitmaps.AlphaBlend(**fields | {"x": d.u(8), "y": d.u(8), "width": d.u(48), "height": d.u(36)}, data=data))
        d.add(bitmaps.AlphaBlend(**fields | {"x": d.u(64), "y": d.u(60), "width": 16, "height": 12}, data=data))

    return draw


def transparent_blt(d):
    transfer_background(d)
    fields, data = source_fields(bitmaps.TransparentBlt, SOURCE)
    red, green, blue = gradient(5, 5)
    fields |= {"src_width": 16, "src_height": 12, "transparent": red | green << 8 | blue << 16}
    d.add(bitmaps.TransparentBlt(**fields | {"x": d.u(8), "y": d.u(8), "width": d.u(48), "height": d.u(36)}, data=data))
    d.add(bitmaps.TransparentBlt(**fields | {"x": d.u(64), "y": d.u(60), "width": 16, "height": 12}, data=data))


def source_transforms(d):
    """BitBlt and StretchBlt records whose source DC had a world transform.

    The source rectangle is logical in the recorded source transform: scales
    and mirrors stretch it; a rotation or shear is expected to fail.
    """
    transfer_background(d)
    d.add(fixed.SetStretchBltMode(3))  # COLORONCOLOR
    fields, data = source_fields(bitmaps.BitBlt, SOURCE)
    blits = (
        # (x, y, width, height, src_x, src_y, (m11, m12, m21, m22, dx, dy))
        (4, 4, 32, 24, 0, 0, (0.5, 0, 0, 0.5, 0, 0)),
        (44, 4, 8, 6, 0, 0, (2, 0, 0, 2, 0, 0)),
        (60, 4, 10, 8, 0, 0, (1, 0, 0, 1, 4, 2)),
        (76, 4, 10, 8, 3, 1, (1, 0, 0, 1, 2, 1)),
        (92, 4, 16, 12, 0, 0, (-1, 0, 0, 1, 16, 0)),
        (4, 36, 16, 12, 0, 0, (1, 0, 0, -1, 0, 12)),
        (24, 36, 20, 8, 0, 0, (0.75, 0, 0, 1.5, 0, 0)),
        (48, 36, 13, 9, 1, 1, (1.2, 0, 0, 1.25, 0.5, 0.4)),
        (68, 36, 16, 12, 0, 0, (0.866, 0.5, -0.5, 0.866, 6, 0)),
        (88, 36, 16, 12, 0, 0, (1, 0, 0.5, 1, 0, 0)),
    )
    for x, y, width, height, src_x, src_y, xform in blits:
        place = {"x": d.u(x), "y": d.u(y), "width": d.u(width), "height": d.u(height), "src_x": src_x, "src_y": src_y}
        transform = dict(zip(bitmaps.SOURCE_XFORM, xform, strict=True))
        d.add(bitmaps.BitBlt(**fields | place | transform | {"rop": SRCCOPY}, data=data))
    fields, data = source_fields(bitmaps.StretchBlt, SOURCE)
    stretches = (
        # (x, y, width, height, src_x, src_y, src_width, src_height, transform)
        (4, 60, 48, 36, 0, 0, 16, 12, (0.5, 0, 0, 0.5, 0, 0)),
        (56, 60, 16, 12, 0, 0, 8, 6, (2, 0, 0, 2, 0, 0)),
        (76, 60, 24, 18, 2, 2, 12, 8, (1, 0, 0, 1, -1, -1)),
        (104, 60, 20, 16, 0, 0, 16, 12, (-1, 0, 0, -1, 16, 12)),
        (4, 100, 30, 20, 0, 0, 10, 10, (1.5, 0, 0, 1.2, 0, 0)),
        (40, 100, 24, 18, 0, 0, 16, 12, (0.866, 0.5, -0.5, 0.866, 6, 0)),
    )
    for x, y, width, height, src_x, src_y, src_width, src_height, xform in stretches:
        place = {"x": d.u(x), "y": d.u(y), "width": d.u(width), "height": d.u(height), "src_x": src_x, "src_y": src_y}
        place |= {"src_width": src_width, "src_height": src_height}
        transform = dict(zip(bitmaps.SOURCE_XFORM, xform, strict=True))
        d.add(bitmaps.StretchBlt(**fields | place | transform | {"rop": SRCCOPY}, data=data))
    # A transformed source with a ternary operation.
    place = {"x": d.u(70), "y": d.u(100), "width": d.u(32), "height": d.u(24), "rop": SRCINVERT}
    d.add(
        bitmaps.StretchBlt(
            **fields | place | {"src_m11": 0.5, "src_m22": 0.5, "src_width": 32, "src_height": 24}, data=data
        )
    )


def palette_dib(depth, width, height, indexes, sample):
    """A bottom-up DIB whose colour table is WORD logical palette indexes."""
    stride = ((width * depth + 31) // 32) * 4
    header = struct.pack("<IiiHHIIiiII", 40, width, height, 1, depth, 0, stride * height, 0, 0, len(indexes), 0)
    rows = []
    for y in range(height - 1, -1, -1):
        value = 0
        for x in range(width):
            value |= sample(x, y) << (stride * 8 - depth * (x + 1))
        rows.append(value.to_bytes(stride, "big"))
    return header + struct.pack(f"<{len(indexes)}H", *indexes), b"".join(rows)


def palette_sources(d):
    """Transfers whose source colour table indexes the selected logical palette."""
    transfer_background(d)
    entries = ((255, 0, 0, 0), (0, 160, 0, 0), (0, 0, 255, 0), (255, 255, 0, 0), (128, 0, 128, 0))
    d.add(variable.CreatePalette(1, entries), fixed.SelectPalette(1), fixed.RealizePalette())
    sources = (
        palette_dib(8, 8, 6, (4, 3, 2, 1, 0, 9), lambda x, y: (x + y) % 6),
        palette_dib(4, 8, 6, (1, 2, 7, 300), lambda x, y: (x // 2 + y) % 4),
        palette_dib(1, 8, 6, (2, 3), lambda x, y: (x + y // 2) % 2),
        palette_dib(8, 8, 6, tuple(range(8)), lambda x, y: (x * 3 + y) % 8),
    )

    def transfers(top):
        for column, source in enumerate(sources):
            fields, data = source_fields(bitmaps.BitBlt, source)
            place = {"x": d.u(4 + 30 * column), "y": d.u(top), "width": 8, "height": 6, "usage": DIB_PAL_COLORS}
            d.add(bitmaps.BitBlt(**fields | place | {"rop": SRCCOPY}, data=data))
            fields, data = source_fields(bitmaps.StretchBlt, source)
            place |= {"y": d.u(top + 10), "width": d.u(24), "height": d.u(18), "src_width": 8, "src_height": 6}
            d.add(bitmaps.StretchBlt(**fields | place | {"rop": SRCCOPY}, data=data))

    transfers(4)
    d.add(fixed.SelectPalette(DEFAULT_PALETTE), fixed.RealizePalette())
    transfers(40)
    d.add(fixed.SelectPalette(1), variable.SetPaletteEntries(1, 0, ((0, 0, 0, 0), (255, 255, 255, 0))))
    transfers(76)


def blend_sources(d):
    """AlphaBlend, TransparentBlt, MaskBlt and PlgBlt with a scaled, a palette-indexed
    and a rotated source, one column each."""
    transfer_background(d)
    d.add(fixed.SetStretchBltMode(3))  # COLORONCOLOR
    scaled = {"src_m11": 0.5, "src_m22": 0.5}
    rotated = {"src_m11": 0.866, "src_m12": 0.5, "src_m21": -0.5, "src_m22": 0.866, "src_dx": 6.0}
    indexed = palette_dib(8, 16, 12, (4, 3, 2, 1, 0, 9), lambda x, y: (x // 2 + y // 2) % 6)
    columns = (({**scaled}, SOURCE, 32, 24), ({"usage": DIB_PAL_COLORS}, indexed, 16, 12), (rotated, SOURCE, 16, 12))
    red, green, blue = gradient(5, 5)
    for column, (change, source, src_width, src_height) in enumerate(columns):
        x = d.u(4 + 40 * column)
        size = {"width": d.u(32), "height": d.u(24), "src_width": src_width, "src_height": src_height}
        fields, data = source_fields(bitmaps.AlphaBlend, source)
        d.add(bitmaps.AlphaBlend(**fields | change | size | {"x": x, "y": d.u(4), "blend": 0x00C00000}, data=data))
        fields, data = source_fields(bitmaps.TransparentBlt, source)
        key = {"transparent": red | green << 8 | blue << 16 if source is SOURCE else 0x000080}
        d.add(bitmaps.TransparentBlt(**fields | change | size | key | {"x": x, "y": d.u(36)}, data=data))
        fields, data = source_fields(bitmaps.MaskBlt, (*source, *MASK))
        place = {"x": x, "y": d.u(68), "width": d.u(16), "height": d.u(12), "rop": 0xAACC0020}
        d.add(bitmaps.MaskBlt(**fields | change | place, data=data))
        fields, data = source_fields(bitmaps.PlgBlt, source)
        corners = {"x0": x, "y0": d.u(100), "x1": x + d.u(32), "y1": d.u(104), "x2": x + d.u(4), "y2": d.u(124)}
        d.add(
            bitmaps.PlgBlt(**fields | change | corners | {"src_width": src_width, "src_height": src_height}, data=data)
        )


def scan_bands(d):
    """SetDIBitsToDevice records carrying partial scan bands of a 16x12 DIB.

    Each record holds the full-height header and only its band's scan lines,
    as a band-by-band caller passes them.
    """
    transfer_background(d)
    stride = 16 * 3
    pixels = {y: b"".join(bytes(reversed(gradient(x, y))) for x in range(16)) for y in range(12)}
    bands = (
        # (x, y, src_x, src_y, src_width, src_height, start, count, top_down)
        (4, 4, 0, 0, 16, 12, 0, 4, False),
        (24, 4, 0, 0, 16, 12, 4, 4, False),
        (44, 4, 0, 0, 16, 12, 8, 8, False),
        (64, 4, 2, 3, 10, 6, 2, 5, False),
        (84, 4, 0, 0, 16, 12, 3, 20, False),
        (4, 40, 0, 0, 16, 12, 0, 4, True),
        (24, 40, 0, 0, 16, 12, 5, 4, True),
        (44, 40, 1, 2, 12, 8, 2, 6, True),
    )
    for x, y, src_x, src_y, src_width, src_height, start, count, top_down in bands:
        height = -12 if top_down else 12
        info = struct.pack("<IiiHHIIiiII", 40, 16, height, 1, 24, 0, 0, 0, 0, 0, 0)
        # Scan line n is row n from the top of a top-down DIB, else from the bottom.
        lines = range(start, min(start + count, 12))
        bits = b"".join(pixels[line if top_down else 11 - line] for line in lines)
        bits += bytes(stride * (count - len(lines)))
        offset = 8 + struct.calcsize("<" + bitmaps.SetDIBitsToDevice.wire_layout)
        placement = (d.u(x), d.u(y), src_x, src_y, src_width, src_height)
        blocks = (offset, len(info), offset + len(info), len(bits), 0, start, count)
        d.add(bitmaps.SetDIBitsToDevice(0, 0, 0, 0, *placement, *blocks, info + bits))


def offset_ties(d):
    """OffsetClipRgn offsets that scale to exact half pixels, one cell each.

    A clip rectangle is set and offset under a scaling world transform, then
    a cell-sized rectangle is filled through it under the identity.
    """
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x2060C0)
    cases = (
        # (m11, m22, offset x, offset y)
        (0.5, 0.5, 1, 1),
        (0.5, 0.5, -1, -1),
        (0.5, 0.5, 3, -3),
        (0.5, 0.5, 5, 7),
        (2.5, 1.5, 1, 1),
        (2.5, 1.5, -1, -1),
        (2.5, 1.5, 3, 3),
        (-0.5, 0.5, 1, 1),
        (1.5, -2.5, -1, 3),
        (1.25, 0.75, 2, -2),
        (0.25, 0.25, 2, 6),
        (0.25, 0.25, -2, -6),
    )
    for index, (m11, m22, offset_x, offset_y) in enumerate(cases):
        left, top = 4 + 31 * (index % 4), 4 + 40 * (index // 4)
        # The clip covers device (left + 6, top + 6) to (left + 18, top + 22).
        corners = [((left + 6 + dx) / m11, (top + 6 + dy) / m22) for dx, dy in ((0, 0), (12, 16))]
        (x0, y0), (x1, y1) = (tuple(round(value) for value in corner) for corner in corners)
        d.add(fixed.SaveDC(), fixed.SetWorldTransform(m11, 0.0, 0.0, m22, 0.0, 0.0))
        d.add(fixed.IntersectClipRect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)))
        d.add(fixed.OffsetClipRgn(offset_x, offset_y))
        d.add(fixed.SetWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))
        d.add(fixed.Rectangle(left, top, left + 30, top + 36), fixed.RestoreDC(-1))


def top_down_dib(width, height, colour):
    """A top-down 24-bit DIB split into (BitmapInfo, bits)."""
    stride = (width * 3 + 3) & ~3
    header = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 24, 0, stride * height, 0, 0, 0, 0)
    rows = (b"".join(bytes(reversed(colour(x, y))) for x in range(width)) for y in range(height))
    return header, b"".join(row + bytes(stride - len(row)) for row in rows)


def hues(x, y):
    """Many distinct colours, so HALFTONE filters rather than replicates."""
    return (x * 37 + y * 11) % 256, (x * 13 + y * 41) % 256, (x * 23 + y * 29 + 90) % 256


def color_engine(orientation, transfers):
    """HALFTONE StretchDIBits through the colour engine (colourfulness, tint, illuminant)."""
    dib = top_down_dib if orientation == "top-down" else rgb_dib

    def draw(d):
        d.add(fixed.SetStretchBltMode(HALFTONE))
        for adjustment, clip, (x, y, width, height), (src_x, src_y, src_width, src_height), source in transfers:
            colorfulness, tint, illuminant = adjustment
            d.add(
                fixed.SaveDC(),
                fixed.SetColorAdjustment(24, 0, illuminant, 10000, 10000, 10000, 0, 10000, 0, 0, colorfulness, tint),
            )
            if clip:
                d.add(fixed.IntersectClipRect(*clip))
            info, bits = dib(*source)
            offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
            placement = (x, y, src_x, src_y, src_width, src_height, offset, len(info), offset + len(info), len(bits))
            d.add(bitmaps.StretchDIBits(0, 0, 0, 0, *placement, 0, SRCCOPY, width, height, info + bits))
            d.add(fixed.RestoreDC(-1))

    return draw


SMALL, WIDE = (16, 12, gradient), (50, 50, hues)
ENGINE_REPLICATED = (
    ((60, 0, 0), None, (2, 2, 64, 48), (0, 0, 16, 12), SMALL),
    ((0, -40, 0), None, (66, 2, 48, 36), (0, 0, 16, 12), SMALL),
    ((0, 0, 1), None, (2, 52, 64, 48), (3, 2, 10, 8), SMALL),
    ((30, 20, 8), (70, 60, 110, 110), (66, 52, 60, 72), (0, 0, 10, 12), SMALL),
)
ENGINE_FILTERED = (((40, -30, 0), None, (1, 1, 125, 125), (0, 0, 50, 50), WIDE),)
ENGINE_OFFSET = (((40, -30, 0), (10, 10, 110, 118), (0, 0, 120, 120), (5, 4, 40, 40), WIDE),)
ENGINE_REDUCED = (
    ((50, 0, 0), None, (4, 4, 30, 30), (0, 0, 50, 50), WIDE),
    ((0, 30, 2), None, (40, 4, 41, 36), (0, 0, 50, 50), WIDE),
)
ENGINE_LARGE = (((-50, 60, 0), None, (2, 2, 120, 108), (0, 0, 16, 12), (16, 12, hues)),)


def gradients(d):
    vertices = ((d.u(4), d.u(4), 0xFF00, 0, 0, 0), (d.u(60), d.u(40), 0, 0, 0xFF00, 0))
    d.add(variable.GradientFill((0, 0, 0, 0), 0, vertices, ((0, 1),)))
    vertices = ((d.u(68), d.u(4), 0xFF00, 0xFF00, 0, 0), (d.u(124), d.u(40), 0, 0x8000, 0xFF00, 0))
    d.add(variable.GradientFill((0, 0, 0, 0), 1, vertices, ((0, 1),)))
    corners = ((4, 124), (64, 50), (124, 124), (64, 90))
    colours = ((0xFF00, 0, 0), (0, 0xFF00, 0), (0, 0, 0xFF00), (0xFF00, 0xFF00, 0xFF00))
    vertices = tuple((d.u(x), d.u(y), *colour, 0) for (x, y), colour in zip(corners, colours, strict=True))
    d.add(variable.GradientFill((0, 0, 0, 0), 2, vertices, ((0, 1, 3), (1, 2, 3))))


def gradient_edges(d):
    """GradientFill edge conditions: flat edges, clamped channels, tiny and huge shapes."""

    def triangle(points, colours):
        vertices = tuple((x, y, *colour, 0) for (x, y), colour in zip(points, colours, strict=True))
        d.add(variable.GradientFill((0, 0, 0, 0), 2, vertices, ((0, 1, 2),)))

    odd = ((0x1234, 0xFEDC, 0x0F0F), (0xF0F0, 0x2468, 0x8642), (0x7777, 0x0101, 0xFF00))
    triangle(((4, 4), (60, 4), (30, 40)), odd)  # flat top
    triangle(((70, 4), (100, 40), (66, 40)), odd)  # flat bottom
    triangle(((4, 46), (60, 50), (20, 80)), ((0xFFFF, 0, 0xFF80), (0, 0xFFFF, 0x80), (0xFF01, 0xFFFF, 0)))
    triangle(((110, 46), (112, 47), (111, 50)), odd)
    triangle(((115, 46), (125, 46), (120, 46)), odd)  # degenerate
    vertices = ((66, 46, 0xFFFF, 0x1234, 0x0001, 0), (124, 60, 0x0101, 0xFEFE, 0xFFFF, 0))
    d.add(variable.GradientFill((0, 0, 0, 0), 0, vertices, ((0, 1),)))
    vertices = ((66, 62, 0x1357, 0xFFFF, 0x2468, 0), (124, 86, 0xFFFF, 0x0102, 0x9ABC, 0))
    d.add(fixed.SaveDC(), fixed.IntersectClipRect(70, 64, 120, 84))
    d.add(variable.GradientFill((0, 0, 0, 0), 1, vertices, ((0, 1),)), fixed.RestoreDC(-1))
    triangle(
        ((-20000, 90), (30000, 100), (64, 30000)), ((0xFF00, 0, 0x1000), (0, 0xFF00, 0x8000), (0x4000, 0x4000, 0xFF00))
    )


def rotated_frames(d):
    """FrameRgn under rotating, shearing and general world transforms."""
    d.add(
        fixed.CreateBrushIndirect(1, BS_SOLID, 0xA00000, 0),
        fixed.CreateBrushIndirect(2, BS_HATCHED, 0x0060C0, HS_DIAGCROSS),
    )
    shapes = (
        [(0, 0, 30, 20)],
        [(0, 0, 14, 10), (0, 10, 34, 22)],
        [(0, 0, 30, 6), (0, 6, 8, 18), (22, 6, 30, 18), (0, 18, 30, 24)],
    )
    cases = (
        ((0.9063, 0.4226, -0.4226, 0.9063, 18.0, 2.0), 0, 1, (1, 1)),
        ((0.9063, 0.4226, -0.4226, 0.9063, 70.0, 2.0), 1, 2, (3, 2)),
        ((1.0, 0.0, 0.5, 1.0, 4.0, 46.0), 2, 1, (2, 5)),
        ((0.9, 0.35, -0.2, 1.1, 70.0, 44.0), 1, 1, (4, 4)),
        ((0.7071, -0.7071, 0.7071, 0.7071, 10.0, 104.0), 2, 2, (6, 3)),
        ((1.2, 0.3, 0.1, 0.8, 70.0, 88.0), 0, 1, (2, 7)),
    )
    d.add(fixed.SetMiterLimit(2))
    for index, (transform, shape, brush, (width, height)) in enumerate(cases):
        if index == 3:
            d.add(fixed.SetMiterLimit(10))
        region = region_data(list(shape_rects for shape_rects in shapes[shape]))
        d.add(fixed.SetWorldTransform(*transform))
        d.add(variable.FrameRgn(bounds=(0, 0, 0, 0), brush=brush, width=width, height=height, region=region))
    d.add(fixed.SetWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0))


def palettes(d):
    entries = ((255, 0, 0, 0), (0, 160, 0, 0), (0, 0, 255, 0), (255, 255, 0, 0))
    d.add(variable.CreatePalette(1, entries), fixed.SelectPalette(1), fixed.RealizePalette())
    for index in range(4):
        d.brush(BS_SOLID, 0x01000000 | index)
        d.add(fixed.Rectangle(*d.rect(4 + 30 * index, 4, 30 + 30 * index, 30)))
    d.add(variable.SetPaletteEntries(1, 1, ((128, 0, 128, 0),)), fixed.ResizePalette(1, 6), fixed.RealizePalette())
    d.brush(BS_SOLID, 0x01000001)
    d.add(fixed.Rectangle(*d.rect(4, 36, 30, 62)))
    # A 2x2 8-bit DIB whose two colour-table entries are logical palette indexes.
    info = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 8, 0, 8, 0, 0, 2, 0)
    indexes = struct.pack("<2H", 2, 3)
    bits = bytes((0, 1, 0, 0, 1, 0, 0, 0))
    offset = 8 + struct.calcsize("<" + bitmaps.CreateDIBPatternBrushPt.wire_layout)
    full = info + indexes
    d.select(
        lambda slot: bitmaps.CreateDIBPatternBrushPt(
            slot, DIB_PAL_COLORS, offset, len(full), offset + len(full), len(bits), full + bits
        )
    )
    d.add(fixed.Rectangle(*d.rect(36, 36, 90, 62)))
    d.add(fixed.SelectPalette(DEFAULT_PALETTE), fixed.RealizePalette())
    d.brush(BS_SOLID, 0x01000002)
    d.add(fixed.Rectangle(*d.rect(4, 70, 60, 120)))
    d.add(variable.Eof(((0, 0, 0, 0), (255, 255, 255, 0))))


def flood_fills(d):
    d.pen(PS_SOLID, 0, 0x000000)
    d.add(fixed.Ellipse(*d.rect(8, 8, 120, 120)), fixed.Rectangle(*d.rect(40, 40, 88, 88)))
    d.brush(BS_SOLID, 0x00C0FF)
    d.add(fixed.ExtFloodFill(d.u(20), d.u(64), 0x000000, 0))
    d.brush(BS_HATCHED, 0xC00000, HS_DIAGCROSS)
    d.add(fixed.ExtFloodFill(d.u(64), d.u(64), 0xFFFFFF, 1))


def layout(d):
    d.add(fixed.SetLayout(1))
    d.brush(BS_SOLID, 0x00C000)
    d.add(fixed.Rectangle(*d.rect(4, 4, 50, 40)), fixed.Ellipse(*d.rect(60, 10, 120, 50)))
    d.add(fixed.Arc(*d.rect(4, 60, 60, 120), *d.rect(60, 90, 4, 60)), fixed.LineTo(d.u(120), d.u(124)))


def rotation(d):
    angle = math.radians(25)
    cos, sin = math.cos(angle), math.sin(angle)
    d.add(fixed.SetWorldTransform(cos, sin, -sin, cos, d.u(40), d.u(-10)))
    d.pen(PS_SOLID, d.u(3), 0x000080)
    d.brush(BS_HATCHED, 0x008000, HS_DIAGCROSS)
    d.add(fixed.Rectangle(*d.rect(10, 10, 60, 40)), fixed.Ellipse(*d.rect(10, 50, 60, 80)))
    d.add(
        fixed.Pie(*d.rect(64, 10, 100, 46), *d.rect(100, 28, 64, 10)), fixed.RoundRect(*d.rect(64, 50, 100, 80), 10, 10)
    )
    d.pen(PS_SOLID, 0, 0xC00000)
    d.add(fixed.MoveToEx(d.u(0), d.u(90)), fixed.LineTo(d.u(90), d.u(90)))
    d.add(fixed.ModifyWorldTransform(1.0, 0.0, 0.4, 1.0, 0.0, 0.0, 2))
    info, bits = rgb_dib(16, 12, gradient)
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
    d.add(
        bitmaps.StretchDIBits(
            0,
            0,
            0,
            0,
            d.u(10),
            d.u(96),
            0,
            0,
            16,
            12,
            offset,
            len(info),
            offset + len(info),
            len(bits),
            0,
            SRCCOPY,
            d.u(40),
            d.u(24),
            info + bits,
        )
    )


def save_levels(d):
    d.brush(BS_SOLID, 0xFF0000)
    d.add(fixed.SaveDC())
    d.brush(BS_SOLID, 0x00FF00)
    d.add(fixed.SaveDC())
    d.brush(BS_SOLID, 0x0000FF)
    d.add(fixed.SaveDC(), fixed.Rectangle(*d.rect(4, 4, 40, 40)))
    d.add(fixed.RestoreDC(2), fixed.Rectangle(*d.rect(44, 4, 80, 40)))
    d.add(fixed.RestoreDC(1), fixed.Rectangle(*d.rect(84, 4, 120, 40)))
    d.add(fixed.RestoreDC(5), fixed.RestoreDC(0), fixed.Rectangle(*d.rect(4, 44, 40, 80)))
    d.add(fixed.SaveDC(), fixed.SetMapMode(8), fixed.SetWindowExtEx(2, 2), fixed.SetViewportExtEx(1, 1))
    d.add(fixed.RestoreDC(-1), fixed.Rectangle(*d.rect(44, 44, 80, 80)))


def comments(d):
    embedded = Metafile.build([fixed.Rectangle(0, 0, 100, 100)], frame=(0, 0, 2000, 2000)).to_bytes()
    multiformats = struct.pack("<II4iI", 0x43494447, 0x40000004, 0, 0, 100, 100, 1)
    multiformats += struct.pack("<4I", 0x464D4520, 0x00010000, len(embedded), 8 + 16 + 4 + 16) + embedded
    d.add(variable.Comment(multiformats))
    begin = struct.pack("<II4iI", 0x43494447, 2, 0, 0, 10, 10, 2) + "g\0".encode("utf-16-le")
    d.add(variable.Comment(begin), variable.Comment(struct.pack("<II", 0x43494447, 3)))
    d.add(variable.Comment(b"EMF+" + struct.pack("<HHII", 0x4001, 1, 28, 16) + bytes(16)))
    d.brush(BS_SOLID, 0x0080FF)
    d.add(fixed.Rectangle(*d.rect(20, 20, 108, 108)))


def _stretch_dib(d, left, top, bounds, source):
    """A StretchDIBits of ``source`` at design (left, top), 1:1, with explicit record bounds."""
    info, bits = source
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
    width, height = struct.unpack_from("<ii", info, 4)
    fields = (d.u(left), d.u(top), 0, 0, width, abs(height), offset, len(info), offset + len(info), len(bits))
    d.add(bitmaps.StretchDIBits(*bounds, *fields, 0, SRCCOPY, width, abs(height), info + bits))


def record_culling(dense):
    """Transfers and region painting whose record bounds miss the clip box.

    Native playback skips these records when their non-empty bounds lie
    wholly outside the clip box, widened by a margin, that it reads before
    the first record. Each record draws inside the picture whatever its
    bounds say, so only culling leaves a gap.
    """

    def draw(d):
        if dense:
            d.device = ReferenceDevice((4096, 3072), (271, 203), dpi=None)
        source = rgb_dib(12, 9, gradient)
        edge = d.u(128)
        # Far outside; reversed (empty) bounds are never culled.
        _stretch_dib(d, 4, 4, (500, 500, 520, 520), source)
        _stretch_dib(d, 24, 4, (520, 520, 500, 500), source)
        # At and just past the widened box's leading and trailing edges.
        for column, offset in enumerate(range(-1, -7, -1)):
            _stretch_dib(d, 4 + 20 * column, 20, (-20, -20, offset, offset), source)
        for column, offset in enumerate(range(1, 7)):
            _stretch_dib(d, 4 + 20 * column, 36, (edge + offset, 0, edge + offset + 5, 5), source)
            _stretch_dib(d, 4 + 20 * column, 52, (0, edge + offset, 5, edge + offset + 5), source)
        d.brush(BS_SOLID, 0x2080C0)
        region = region_data(((d.u(4), d.u(72), d.u(40), d.u(100)),))
        brush = d.slot
        d.add(variable.FillRgn(bounds=(600, 0, 700, 10), brush=brush, region=region))
        region = region_data(((d.u(48), d.u(72), d.u(84), d.u(100)),))
        d.add(variable.PaintRgn(bounds=(-1, -1, -1, -1), region=region))
        region = region_data(((d.u(92), d.u(72), d.u(124), d.u(100)),))
        d.add(variable.InvertRgn(bounds=(0, -30, 10, -3), region=region))
        blit = dict.fromkeys(bitmaps.BitBlt.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "data": b""}
        blit |= {"x": d.u(4), "y": d.u(106), "width": d.u(56), "height": d.u(18), "rop": PATCOPY}
        d.add(bitmaps.BitBlt(**blit | dict(zip(bitmaps.BOUNDS, (0, edge + 2, 10, edge + 9), strict=True))))
        blit |= {"x": d.u(68)}
        d.add(bitmaps.BitBlt(**blit | dict(zip(bitmaps.BOUNDS, (-9, 0, -1, 10), strict=True))))

    return draw


def nested_reset(d):
    """An embedded metafile drawing with the attributes native playback resets.

    The outer metafile changes every attribute playback resets, selects a
    hatched brush and wide pen, and clips; the embedded metafile then draws
    with its defaults, and removes its own clip to reach the outer one.
    """
    d.brush(BS_SOLID, 0xC0C0C0)
    d.add(fixed.Rectangle(*d.rect(0, 0, 64, 128)))
    d.brush(BS_HATCHED, 0x0000C0, HS_DIAGCROSS)
    d.pen(PS_SOLID, 3, 0x00C000)
    d.add(
        fixed.SetBkColor(0x80FFFF),
        fixed.SetTextColor(0xFF0000),
        fixed.SetBkMode(TRANSPARENT),
        fixed.SetPolyFillMode(WINDING),
        fixed.SetROP2(7),
        fixed.SetStretchBltMode(HALFTONE),
        fixed.SetBrushOrgEx(3, 5),
        fixed.SetMiterLimit(1),
        fixed.SetArcDirection(AD_CLOCKWISE),
        fixed.MoveToEx(d.u(120), d.u(30)),
        fixed.IntersectClipRect(*d.rect(4, 4, 124, 124)),
    )
    star = [
        (30 + 24 * math.cos(math.radians(90 + 144 * i)), 32 - 24 * math.sin(math.radians(90 + 144 * i)))
        for i in range(5)
    ]
    inner = [
        fixed.Rectangle(70, 8, 120, 30),
        fixed.LineTo(60, 60),
        fixed.Arc(70, 36, 120, 76, 120, 56, 70, 56),
        fixed.CreateBrushIndirect(1, BS_HATCHED, 0x008000, HS_BDIAGONAL),
        fixed.SelectObject(1),
        variable.Polygon((0, 0, 0, 0), tuple((round(x), round(y)) for x, y in star)),
        fixed.Rectangle(8, 64, 60, 96),
        bitmaps.ExtCreatePen(2, 0, 0, 0, 0, PS_GEOMETRIC | PS_JOIN_MITER | PS_ENDCAP_FLAT, 6, BS_SOLID, 0x800080, 0),
        fixed.SelectObject(2),
        variable.Polyline((0, 0, 0, 0), ((70, 120), (80, 84), (90, 120))),
        variable.ExtSelectClipRgn(RGN_COPY),
        fixed.SelectObject(STOCK | 8),
        fixed.CreateBrushIndirect(3, BS_SOLID, 0xC08040, 0),
        fixed.SelectObject(3),
        fixed.Rectangle(100, 84, 140, 140),
    ]
    embedded = Metafile.build(inner, frame=(0, 0, 3388, 3383)).to_bytes()
    left, top, right, bottom = d.rect(0, 0, 128, 128)
    multiformats = struct.pack("<II4iI", 0x43494447, 0x40000004, left, top, right, bottom, 1)
    multiformats += struct.pack("<4I", 0x464D4520, 0x00010000, len(embedded), 8 + 16 + 4 + 16) + embedded
    d.add(variable.Comment(multiformats))
    # The outer state is back after the embedded metafile.
    d.add(fixed.LineTo(d.u(100), d.u(124)))


def transform_limits(d):
    """Native playback's transform arithmetic at its limits.

    A chain of left-multiplying ModifyWorldTransform records is applied to
    the target's transform directly, so its rounding differs from composing
    the world transform first; one stroke crosses that difference. A world
    offset that overflows once fitted, and a matrix that is singular only in
    single precision, leave the transform unchanged. ScaleViewportExtEx
    wraps its 32-bit product.
    """
    import random

    random.seed(0)
    scale = random.uniform(0.002, 0.006)
    d.add(
        fixed.SaveDC(), fixed.SetWorldTransform(scale, 0.0, 0.0, scale, random.uniform(10, 40), random.uniform(10, 40))
    )
    for _ in range(30):
        angle = random.uniform(-0.2, 0.2)
        stretch = random.uniform(0.98, 1.02)
        offsets = random.uniform(-3, 3), random.uniform(-3, 3)
        rotation = (math.cos(angle) * stretch, math.sin(angle), -math.sin(angle), math.cos(angle))
        d.add(fixed.ModifyWorldTransform(*rotation, *offsets, 2))
    points = tuple(
        (round(9000 + 8000 * math.cos(t * 0.37)), round(9000 + 8000 * math.sin(t * 0.53))) for t in range(1500)
    )
    d.pen(PS_SOLID, 0, 0x2080C0)
    d.add(variable.Polyline((0, 0, 0, 0), points), fixed.RestoreDC(-1))
    d.brush(BS_SOLID, 0x00A000)
    d.add(fixed.SaveDC(), fixed.SetWorldTransform(1.0, 0.0, 0.0, 1.0, 3e9, 0.0), fixed.Rectangle(2, 30, 12, 40))
    d.add(fixed.SetWorldTransform(3.0, 1.0, 1.0, 1 / 3, 0.0, 0.0), fixed.Rectangle(16, 30, 26, 40), fixed.RestoreDC(-1))
    d.add(fixed.SaveDC(), fixed.SetMapMode(8), fixed.SetWindowExtEx(1, 1), fixed.SetViewportExtEx(65536, 65536))
    d.add(fixed.ScaleViewportExtEx(65537, 65536, 65537, 65536), fixed.Rectangle(30, 30, 40, 40), fixed.RestoreDC(-1))


def gradient_rop2(d):
    """GradientFill over a coloured ground under several ROP2 modes."""
    transfer_background(d)
    for column, mode in enumerate((7, 6, 15, 9)):  # XORPEN, NOT, WHITE, MASKPEN
        left = 4 + 31 * column
        d.add(fixed.SetROP2(mode))
        vertices = ((d.u(left), d.u(4), 0xFF00, 0x2000, 0, 0), (d.u(left + 27), d.u(60), 0, 0x8000, 0xFF00, 0))
        d.add(variable.GradientFill((0, 0, 0, 0), 0, vertices, ((0, 1),)))
        corners = ((left, 68), (left + 27, 80), (left + 8, 124))
        colours = ((0xFF00, 0, 0), (0, 0xFF00, 0), (0, 0, 0xFF00))
        vertices = tuple((d.u(x), d.u(y), *colour, 0) for (x, y), colour in zip(corners, colours, strict=True))
        d.add(variable.GradientFill((0, 0, 0, 0), 2, vertices, ((0, 1, 2),)))


def rotated_insideframe(d):
    """PS_INSIDEFRAME shapes under a rotating and a shearing world transform."""
    transforms = (
        (
            math.cos(math.radians(20)),
            math.sin(math.radians(20)),
            -math.sin(math.radians(20)),
            math.cos(math.radians(20)),
        ),
        (1.0, 0.0, 0.45, 1.0),
    )
    for row, matrix in enumerate(transforms):
        d.add(fixed.SetWorldTransform(*matrix, d.u(6), d.u(4 + 62 * row)))
        for column, width in enumerate((1, 6, 9)):
            d.pen(6, d.u(width), (0x800000, 0x008000, 0x000080)[column])  # PS_INSIDEFRAME
            d.brush(BS_HATCHED, 0x0080C0, HS_DIAGCROSS)
            left = 4 + 38 * column
            d.add(fixed.Rectangle(*d.rect(left, 2, left + 30, 18)))
            d.add(fixed.Ellipse(*d.rect(left, 22, left + 30, 38)))
            d.add(fixed.RoundRect(*d.rect(left, 40, left + 14, 56), d.u(8), d.u(6)))
            d.add(fixed.Pie(*d.rect(left + 16, 40, left + 32, 56), *d.rect(left + 32, 48, left + 16, 40)))
    d.add(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1))


def widened_curves(d):
    """Wide pens along curves, widened paths filled by alternation, inside-frame paths."""

    def pts(*values):
        return tuple((d.u(x), d.u(y)) for x, y in values)

    def ext_pen(style, width, color):
        d.select(lambda slot: bitmaps.ExtCreatePen(slot, 0, 0, 0, 0, PS_GEOMETRIC | style, d.u(width), 0, color, 0))

    d.brush(BS_NULL, 0, 0)
    styles = (
        PS_JOIN_MITER | PS_ENDCAP_FLAT,
        PS_JOIN_BEVEL | PS_ENDCAP_SQUARE,
        PS_JOIN_MITER | PS_ENDCAP_ROUND,
        PS_JOIN_ROUND | PS_ENDCAP_FLAT,
    )
    for column, style in enumerate(styles):
        left = 4 + 31 * column
        ext_pen(style, 5, (0x800000, 0x008000, 0x000080, 0x808000)[column])
        d.add(fixed.Ellipse(*d.rect(left, 4, left + 26, 22)))
        d.add(fixed.Pie(*d.rect(left, 24, left + 26, 44), *d.rect(left + 26, 30, left, 26)))
        d.add(variable.PolyBezier((0, 0, 0, 0), pts((left + 2, 58), (left + 8, 40), (left + 24, 70), (left + 24, 48))))
    # Widened paths filled and clipped by alternation keep the widener's
    # self-overlapping contours.
    d.add(fixed.SetPolyFillMode(ALTERNATE))
    d.brush(BS_SOLID, 0x2060C0)
    for column, style in enumerate((PS_JOIN_MITER | PS_ENDCAP_FLAT, PS_JOIN_ROUND | PS_ENDCAP_ROUND)):
        left = 4 + 32 * column
        ext_pen(style, 7, 0)
        d.add(fixed.BeginPath(), fixed.Ellipse(*d.rect(left, 72, left + 28, 92)), fixed.EndPath(), fixed.WidenPath())
        d.add(fixed.FillPath(0, 0, 0, 0))
    d.pen(PS_SOLID, d.u(7), 0)
    d.add(fixed.BeginPath(), variable.PolyBezier((0, 0, 0, 0), pts((70, 76), (76, 64), (96, 100), (100, 74))))
    d.add(fixed.EndPath(), fixed.WidenPath(), fixed.FillPath(0, 0, 0, 0))
    d.add(fixed.SaveDC())
    ext_pen(PS_JOIN_MITER | PS_ENDCAP_FLAT, 6, 0)
    d.add(fixed.BeginPath(), fixed.Pie(*d.rect(104, 70, 126, 94), *d.rect(126, 82, 104, 70)), fixed.EndPath())
    d.add(fixed.WidenPath(), fixed.SelectClipPath(RGN_COPY))
    d.brush(BS_HATCHED, 0xC02020, HS_DIAGCROSS)
    d.add(fixed.Rectangle(*d.rect(100, 66, 128, 98)))
    d.add(fixed.RestoreDC(-1))
    # Inside-frame pens inset the shapes a path is built from; a box narrower
    # than the pen keeps its full size, and a covered pie adds nothing, so
    # SelectClipPath fails and keeps the clip.
    d.pen(6, d.u(7), 0x008080)  # PS_INSIDEFRAME
    d.brush(BS_SOLID, 0xC0C000)
    d.add(fixed.BeginPath(), fixed.Rectangle(*d.rect(4, 100, 30, 124)), fixed.Ellipse(*d.rect(34, 100, 60, 124)))
    d.add(fixed.Rectangle(*d.rect(64, 100, 69, 124)), fixed.EndPath(), fixed.StrokeAndFillPath(0, 0, 0, 0))
    d.add(fixed.SaveDC(), fixed.IntersectClipRect(*d.rect(72, 98, 126, 126)))
    d.add(fixed.BeginPath(), fixed.Pie(*d.rect(80, 100, 85, 124), *d.rect(85, 100, 80, 110)), fixed.EndPath())
    d.add(fixed.SelectClipPath(RGN_AND))
    d.brush(BS_HATCHED, 0x404040, HS_BDIAGONAL)
    d.add(fixed.Rectangle(*d.rect(70, 96, 128, 128)))
    d.add(fixed.RestoreDC(-1))


def dashed_curves(d):
    """Styled wide pens along curves, widened dashes filled by alternation, inside-frame ArcTo."""

    def pts(*values):
        return tuple((d.u(x), d.u(y)) for x, y in values)

    def ext_pen(style, width, color, user=()):
        d.select(
            lambda slot: bitmaps.ExtCreatePen(
                slot, 0, 0, 0, 0, PS_GEOMETRIC | style, d.u(width), 0, color, 0, tuple(d.u(v) for v in user)
            )
        )

    d.brush(BS_NULL, 0, 0)
    styles = (
        (PS_DASH | PS_JOIN_MITER | PS_ENDCAP_FLAT, ()),
        (PS_DOT | PS_JOIN_BEVEL | PS_ENDCAP_SQUARE, ()),
        (PS_USERSTYLE | PS_JOIN_MITER | PS_ENDCAP_FLAT, (14, 4, 6, 4)),
        (PS_USERSTYLE | PS_JOIN_ROUND | PS_ENDCAP_ROUND, (10, 6)),
    )
    for column, (style, user) in enumerate(styles):
        left = 4 + 31 * column
        ext_pen(style, 4, (0x800000, 0x008000, 0x000080, 0x808000)[column], user)
        d.add(fixed.Ellipse(*d.rect(left, 4, left + 26, 22)))
        d.add(fixed.Pie(*d.rect(left, 24, left + 26, 44), *d.rect(left + 26, 30, left, 26)))
        d.add(variable.PolyBezier((0, 0, 0, 0), pts((left + 2, 58), (left + 8, 40), (left + 24, 70), (left + 24, 48))))
    d.add(fixed.SetPolyFillMode(ALTERNATE))
    d.brush(BS_SOLID, 0x2060C0)
    ext_pen(PS_USERSTYLE | PS_JOIN_MITER | PS_ENDCAP_SQUARE, 6, 0, (20, 8))
    d.add(fixed.BeginPath(), fixed.Ellipse(*d.rect(4, 70, 40, 96)), fixed.EndPath(), fixed.WidenPath())
    d.add(fixed.FillPath(0, 0, 0, 0))
    # ArcTo in a path with an inside-frame pen, both directions, then a box
    # narrower than the pen.
    d.pen(6, d.u(6), 0x008080)  # PS_INSIDEFRAME
    d.brush(BS_SOLID, 0xC0C000)
    for column, direction in enumerate((1, 2)):
        left = 46 + 28 * column
        d.add(fixed.SetArcDirection(direction))
        d.add(fixed.BeginPath(), fixed.MoveToEx(d.u(left), d.u(70)))
        d.add(fixed.ArcTo(*d.rect(left + 2, 70, left + 26, 96), *d.rect(left + 26, 80, left + 2, 72)))
        d.add(fixed.CloseFigure(), fixed.EndPath(), fixed.StrokeAndFillPath(0, 0, 0, 0))
    d.add(fixed.SetArcDirection(1))
    d.add(fixed.BeginPath(), fixed.MoveToEx(d.u(104), d.u(70)))
    d.add(fixed.ArcTo(*d.rect(106, 70, 110, 96), *d.rect(110, 80, 106, 72)), fixed.LineTo(d.u(124), d.u(96)))
    d.add(fixed.EndPath(), fixed.StrokePath(0, 0, 0, 0))
    # Inside-frame chords and arcs in a path, and a covered ellipse.
    d.add(fixed.BeginPath(), fixed.Chord(*d.rect(4, 100, 34, 124), *d.rect(34, 104, 4, 120)))
    d.add(fixed.Arc(*d.rect(38, 100, 68, 124), *d.rect(68, 112, 38, 112)), fixed.CloseFigure())
    d.add(fixed.Ellipse(*d.rect(72, 100, 76, 124)), fixed.EndPath(), fixed.StrokeAndFillPath(0, 0, 0, 0))


TEXT_FACE = "Pillow WMF Test"
# Page units to 0.01 mm on the reference device in MM_TEXT, as GM_COMPATIBLE
# text records carry them.
TEXT_SCALES = (100 * 271 / 1024, 100 * 203 / 768)


def text_font(d, height, **fields):
    """Select the controlled layout font."""
    face = TEXT_FACE.encode("utf-16-le").ljust(64, b"\0")
    font = LogFont(height=height, quality=3, face_name=face, **{"weight": 400} | fields)
    return d.select(
        lambda slot: variable.ExtCreateFontIndirectW(slot, font, bytes(256) + struct.pack("<II", 0x08007664, 0))
    )


def ext_text_a(d, x, y, data, *, options=0, rectangle=None, advances=(), mode=1, scales=TEXT_SCALES):
    """An EMR_EXTTEXTOUTA record: bytes, then advances, after the fixed fields.

    Native playback always reads the rectangle field, so it is always written.
    """
    rectangle = rectangle if rectangle is not None else (0, 0, -1, -1)
    start = 8 + 52 + 16
    padded = data + bytes(-len(data) % 4)
    dx_offset = start + len(padded) if advances else 0
    blob = padded + b"".join(struct.pack("<i", value) for value in advances)
    return text.ExtTextOutA((0, 0, -1, -1), mode, *scales, x, y, len(data), start, options, rectangle, dx_offset, blob)


def text_modes(d):
    """Controlled-font ExtTextOutA in compatible and advanced records, with rectangles, advances and alignment."""
    text_font(d, -d.u(12))
    d.add(fixed.SetTextColor(0x802000), fixed.SetBkColor(0xC0E0F0))
    rows = (
        dict(mode=1),
        dict(mode=1, scales=(0.0, 0.0)),
        dict(mode=2, scales=(0.0, 0.0)),
    )
    for row, kwargs in enumerate(rows):
        y = d.u(4 + 18 * row)
        d.add(ext_text_a(d, d.u(4), y, b"AB BA", **kwargs))
        d.add(fixed.SetBkMode(2))  # OPAQUE
        rectangle = d.rect(60, 4 + 18 * row, 120, 18 + 18 * row)
        d.add(
            ext_text_a(
                d,
                d.u(64),
                y,
                b"ABBA",
                options=0x06,
                rectangle=rectangle,
                advances=tuple(d.u(v) for v in (10, 4, 13, 7)),
                **kwargs,
            )
        )
        d.add(fixed.SetBkMode(1))  # TRANSPARENT
    for column, alignment in enumerate((0x18, 0x06, 0x0A)):  # baseline; centre; right bottom
        x = d.u(20 + 40 * column)
        d.add(fixed.SetTextAlign(alignment))
        d.add(fixed.Rectangle(x - d.u(1), d.u(68), x + d.u(1), d.u(70)))
        d.add(ext_text_a(d, x, d.u(70), b"AB"))
    d.add(fixed.SetTextAlign(0))
    # Advanced records follow a non-uniform world scale.
    d.add(fixed.SetWorldTransform(1.5, 0.0, 0.0, 0.75, float(d.u(4)), float(d.u(84))))
    d.add(ext_text_a(d, 0, 0, b"ABA B", mode=2, scales=(0.0, 0.0)))
    d.add(fixed.SetBkMode(2))
    d.add(
        ext_text_a(
            d, d.u(40), d.u(20), b"BA", options=0x02, rectangle=d.rect(38, 18, 60, 40), mode=2, scales=(0.0, 0.0)
        )
    )
    d.add(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1))


def ext_text_w(d, x, y, string, *, options=0, rectangle=None, advances=(), mode=1, scales=TEXT_SCALES):
    """An EMR_EXTTEXTOUTW record with its fixed rectangle field."""
    rectangle = rectangle if rectangle is not None else (0, 0, -1, -1)
    data = string.encode("utf-16-le")
    start = 8 + 52 + 16
    padded = data + bytes(-len(data) % 4)
    dx_offset = start + len(padded) if advances else 0
    blob = padded + b"".join(struct.pack("<i", value) for value in advances)
    chars = len(data) // 2
    return text.ExtTextOutW((0, 0, -1, -1), mode, *scales, x, y, chars, start, options, rectangle, dx_offset, blob)


def poly_text(cls, entries, *, mode=1, scales=TEXT_SCALES, unit=2):
    """A PolyTextOut record; each entry is (x, y, data, options, rectangle, advances or None for offset 0).

    Playback always reads an entry's advances.
    """
    cursor = 8 + 32 + 40 * len(entries)
    blob = b""
    texts = []
    for x, y, data, options, rectangle, advances in entries:
        string_offset = cursor + len(blob) if data else 0
        blob += data + bytes(-len(data) % 4)
        dx_offset = 0
        if advances is not None:
            dx_offset = cursor + len(blob)
            blob += b"".join(struct.pack("<i", value) for value in advances)
        texts.append(text.EmrText(x, y, len(data) // unit, string_offset, options, rectangle, dx_offset))
    return cls((0, 0, -1, -1), mode, *scales, tuple(texts), blob)


def text_records(d):
    """Unicode ExtTextOutW, PolyTextOutA/W and SmallTextOut with the controlled encoding font."""
    face = "Pillow WMF Encoding".encode("utf-16-le").ljust(64, b"\0")
    font = LogFont(height=-d.u(12), weight=400, quality=3, face_name=face)
    d.select(lambda slot: variable.ExtCreateFontIndirectW(slot, font, bytes(256) + struct.pack("<II", 0x08007664, 0)))
    d.add(fixed.SetTextColor(0x802000), fixed.SetBkColor(0xC0E0F0), fixed.SetBkMode(1))
    word = "A\u00e9\u20ac\u0416B"
    d.add(ext_text_w(d, d.u(4), d.u(4), word))
    d.add(ext_text_w(d, d.u(64), d.u(4), word, advances=tuple(d.u(v) for v in (12, 6, 14, 9, 10))))
    d.add(ext_text_w(d, d.u(4), d.u(20), word, mode=2, scales=(0.0, 0.0)))
    # ETO_NO_RECT leaves the fixed layout, rectangle included, in place.
    narrow = ext_text_a(d, d.u(64), d.u(20), b"A\xe9B", options=0x100, advances=tuple(d.u(v) for v in (9, 13, 9)))
    d.add(narrow)
    w = lambda value: value.encode("utf-16-le")  # noqa: E731
    d.add(fixed.SetBkMode(2))
    d.add(
        poly_text(
            text.PolyTextOutW,
            (
                (d.u(4), d.u(36), w("B\u0416A"), 0, (0, 0, -1, -1), tuple(d.u(v) for v in (8, 12, 8))),
                (d.u(40), d.u(36), w("\u20acA"), 0x02, d.rect(38, 36, 60, 50), tuple(d.u(v) for v in (14, 9))),
                (d.u(64), d.u(36), b"", 0x02, d.rect(64, 38, 72, 46), ()),
            ),
        )
    )
    d.add(fixed.SetBkMode(1))
    d.add(
        poly_text(
            text.PolyTextOutA,
            (
                (d.u(80), d.u(36), b"\xe9A", 0x100, (0, 0, -1, -1), (d.u(8), d.u(8))),
                (d.u(100), d.u(36), b"BA", 0, (0, 0, -1, -1), (d.u(9), d.u(9))),
            ),
            unit=1,
        )
    )
    # Small records widen 8-bit characters to UTF-16 code units.
    small = text.SmallTextOut
    d.add(small(d.u(4), d.u(54), 0x300, 1, *TEXT_SCALES, None, b"A\xe9B", None))
    d.add(fixed.SetBkMode(2))
    d.add(small(d.u(40), d.u(54), 0x002, 1, *TEXT_SCALES, d.rect(40, 54, 70, 68), w("\u0416\u20ac")))
    d.add(fixed.SetBkMode(1))
    d.add(small(d.u(80), d.u(54), 0x100, 2, 0.0, 0.0, None, w("BA\u00e9")))
    # Current-position output: ExtTextOutW, then PolyTextOutW.
    d.add(fixed.SetTextAlign(1), fixed.MoveToEx(d.u(4), d.u(72)))
    d.add(ext_text_w(d, 0, 0, "AB"))
    d.add(
        poly_text(
            text.PolyTextOutW,
            (
                (0, 0, w("BA"), 0, (0, 0, -1, -1), (d.u(9), d.u(9))),
                (d.u(90), d.u(90), w("A"), 0, (0, 0, -1, -1), (d.u(9),)),
            ),
        )
    )
    d.add(ext_text_w(d, 0, 0, "\u0416"))
    d.add(fixed.SetTextAlign(0))
    # A zero advance offset addresses the record's own header.
    d.add(poly_text(text.PolyTextOutW, ((d.u(4), d.u(88), w("AB"), 0, (0, 0, -1, -1), None),)))


def text_transforms(d):
    """Controlled-font text under non-uniform, mirrored and rotating world transforms, in both record modes."""
    d.add(fixed.SetTextColor(0x802000), fixed.SetBkMode(1))
    transforms = (
        (1.5, 0.0, 0.0, 0.75),  # non-uniform
        (-1.0, 0.0, 0.0, 1.0),  # mirrored
        (0.9, 0.4, -0.4, 0.9),  # rotating
        (1.0, 0.0, 0.45, 1.0),  # shearing
    )
    for row, matrix in enumerate(transforms):
        for column, (mode, scales, escapement) in enumerate(
            ((1, TEXT_SCALES, 0), (1, (13.0, 40.0), 0), (2, (0.0, 0.0), 0), (1, TEXT_SCALES, 300))
        ):
            text_font(d, -d.u(10), escapement=escapement, orientation=escapement)
            x = 6 + 31 * column + (24 if matrix[0] < 0 else 0)
            d.add(fixed.SetWorldTransform(*matrix, float(d.u(x)), float(d.u(6 + 31 * row))))
            d.add(ext_text_a(d, 0, 0, b"AB A", mode=mode, scales=scales))
            d.add(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1))


def text_transform_styles(d):
    """Opaque, decorated, current-position, paired-advance and synthetic text under rotation, shear and mirroring."""
    d.add(fixed.SetTextColor(0x802000), fixed.SetBkColor(0xC0E0F0))
    transforms = ((0.9, 0.4, -0.4, 0.9), (1.0, 0.0, 0.45, 1.0), (-1.0, 0.0, 0.0, 1.0))
    rows = (
        ("opaque", {}, 1),
        ("decorated", {"underline": 1, "strikeout": 1}, 1),
        ("current-position", {}, 1),
        ("paired", {}, 1),
        ("synthetic", {"weight": 700, "italic": 1}, 1),
        ("escapement", {"escapement": 300}, 2),
        ("default-height", {}, 1),
    )
    for column, matrix in enumerate(transforms):
        for row, (kind, fields, mode) in enumerate(rows):
            scales = TEXT_SCALES if mode == 1 else (0.0, 0.0)
            height = 0 if kind == "default-height" else -d.u(8)
            text_font(d, height, **fields)
            x = 6 + 42 * column + (30 if matrix[0] < 0 else 0)
            d.add(fixed.SetWorldTransform(*matrix, float(d.u(x)), float(d.u(4 + 17 * row))))
            if kind == "opaque":
                d.add(fixed.SetBkMode(2))
                d.add(ext_text_a(d, 0, 0, b"AB A", mode=mode, scales=scales))
                d.add(fixed.SetBkMode(1))
            elif kind == "current-position":
                d.add(fixed.SetTextAlign(1), fixed.MoveToEx(0, 0))
                d.add(ext_text_a(d, 0, 0, b"AB", mode=mode, scales=scales))
                d.add(ext_text_a(d, 0, 0, b"BA", mode=mode, scales=scales))
                d.add(fixed.SetTextAlign(0))
            elif kind == "paired":
                pairs = tuple(d.u(v) for v in (7, 2, 9, -3, 6, 4))
                d.add(ext_text_a(d, 0, 0, b"ABA", options=0x2000, advances=pairs, mode=mode, scales=scales))
            else:
                d.add(ext_text_a(d, 0, 0, b"AB A", mode=mode, scales=scales))
            d.add(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 1))


def rotated_color_adjustment(d):
    """HALFTONE stretches with colour adjustment under a rotating transform."""
    transfer_background(d)
    d.add(fixed.SetStretchBltMode(HALFTONE))
    angle = math.radians(15)
    d.add(fixed.SetWorldTransform(math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), d.u(20), 0.0))
    adjustments = (
        (24, 0, 0, 10000, 10000, 10000, 0, 10000, 30, 20, 0, 0),
        (24, 0, 0, 10000, 10000, 10000, 0, 10000, 0, 0, 40, -30),
    )
    for row, adjustment in enumerate(adjustments):
        d.add(fixed.SetColorAdjustment(*adjustment))
        info, bits = SOURCE
        offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
        fields = (d.u(8), d.u(8 + 56 * row), 0, 0, 16, 12, offset, len(info), offset + len(info), len(bits), 0, SRCCOPY)
        d.add(bitmaps.StretchDIBits(0, 0, 0, 0, *fields, d.u(48), d.u(36), info + bits))
        fields, data = source_fields(bitmaps.StretchBlt, SOURCE)
        fields |= {"x": d.u(64), "y": d.u(8 + 56 * row), "width": d.u(40), "height": d.u(30)}
        d.add(bitmaps.StretchBlt(**fields | {"rop": SRCCOPY, "src_width": 16, "src_height": 12}, data=data))


def plgblt_mirrored_masks(d):
    """Masked PlgBlt onto parallelograms mirrored on one axis of the source."""
    transfer_background(d)
    fields, data = source_fields(bitmaps.PlgBlt, (*SOURCE, *MASK))
    fields |= {"src_width": 16, "src_height": 12}
    corners = (
        ((60, 8), (8, 8), (60, 44)),  # mirrored horizontally
        ((68, 44), (120, 44), (68, 8)),  # mirrored vertically
        ((50, 60), (8, 70), (60, 110)),  # mirrored and sheared
        ((80, 120), (124, 110), (70, 70)),  # flipped and sheared
    )
    for (x0, y0), (x1, y1), (x2, y2) in corners:
        placed = {"x0": d.u(x0), "y0": d.u(y0), "x1": d.u(x1), "y1": d.u(y1), "x2": d.u(x2), "y2": d.u(y2)}
        d.add(bitmaps.PlgBlt(**fields | placed, data=data))


def _rle8(rows):
    """RLE8 bits for rows given bottom-up as lists of (count, index) runs."""
    data = b""
    for runs in rows:
        data += b"".join(bytes((count, index)) for count, index in runs) + b"\0\0"
    data += b"\0\1"
    return data + bytes(-len(data) % 4)


def rle_bands(d):
    """SetDIBitsToDevice of an RLE8 DIB, whole and in partial bands."""
    transfer_background(d)
    palette = b"".join(bytes((b, g, r, 0)) for r, g, b in ((200, 30, 30), (30, 160, 30), (30, 30, 200), (230, 200, 40)))
    # Bottom-up rows of a 12x8 DIB; the second row leaves its end unwritten.
    rows = [[(12, y % 4)] if y != 1 else [(5, 1)] for y in range(8)]
    bits = _rle8(rows)
    info = struct.pack("<IiiHHIIiiII", 40, 12, 8, 1, 8, 1, len(bits), 0, 0, 4, 0) + palette
    offset = 8 + struct.calcsize("<" + bitmaps.SetDIBitsToDevice.wire_layout)
    for column, (start, count) in enumerate(((0, 8), (0, 4), (2, 3), (5, 6))):
        placement = (d.u(4 + 30 * column), d.u(10), 0, 0, 12, 8)
        blocks = (offset, len(info), offset + len(info), len(bits), 0, start, count)
        d.add(bitmaps.SetDIBitsToDevice(0, 0, 0, 0, *placement, *blocks, info + bits))
    placement = (d.u(4), d.u(60), 2, 1, 8, 5)
    blocks = (offset, len(info), offset + len(info), len(bits), 0, 1, 6)
    d.add(bitmaps.SetDIBitsToDevice(0, 0, 0, 0, *placement, *blocks, info + bits))


def invalid_modes(d):
    """Out-of-range mode values for ROP2, fill, stretch, background and arc direction.

    Each row starts from a valid mode, sets an out-of-range value and then
    draws something whose appearance shows the mode in effect.
    """
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x30A0E0)
    for column in range(8):
        d.add(fixed.Rectangle(*d.rect(column * 16, 0, column * 16 + 8, 128)))
    d.brush(BS_SOLID, 0x0000C0)
    for column, value in enumerate((0, 17, 23, 29, 0x107, 0x10D, 0xFFFFFFFF, 255)):
        d.add(
            fixed.SetROP2(7), fixed.SetROP2(value), fixed.Rectangle(*d.rect(2 + 16 * column, 2, 14 + 16 * column, 24))
        )
    d.add(fixed.SetROP2(13))
    star = [
        (8 + 7 * math.cos(math.radians(90 + 144 * i)), 36 - 7 * math.sin(math.radians(90 + 144 * i))) for i in range(5)
    ]
    d.brush(BS_SOLID, 0x008000)
    for column, value in enumerate((0, 3, 0x101, 0x102, 0xFFFFFFFF)):
        points = tuple((d.u(x + 16 * column), d.u(y)) for x, y in star)
        d.add(fixed.SetPolyFillMode(2), fixed.SetPolyFillMode(value), variable.Polygon((0, 0, 0, 0), points))
    d.add(fixed.SetPolyFillMode(1))
    info, bits = rgb_dib(16, 16, lambda x, y: (255, 255, 255) if (x + y) % 2 else (40, 40, 160))
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
    for column, value in enumerate((0, 5, 0x101, 0x104, 0xFFFFFFFF)):
        d.add(fixed.SetStretchBltMode(3), fixed.SetStretchBltMode(value))
        fields = (
            d.u(2 + 16 * column),
            d.u(48),
            0,
            0,
            16,
            16,
            offset,
            len(info),
            offset + len(info),
            len(bits),
            0,
            SRCCOPY,
        )
        d.add(bitmaps.StretchDIBits(0, 0, 0, 0, *fields, 5, 5, info + bits))
    d.add(fixed.SetStretchBltMode(3))
    d.brush(BS_HATCHED, 0x800080, HS_DIAGCROSS)
    d.add(fixed.SetBkColor(0x00FFFF))
    for column, value in enumerate((0, 3, 0x101, 0x102, 0xFFFFFFFF)):
        d.add(
            fixed.SetBkMode(1),
            fixed.SetBkMode(value),
            fixed.Rectangle(*d.rect(2 + 16 * column, 66, 14 + 16 * column, 86)),
        )
    d.add(fixed.SetBkMode(2))
    d.pen(PS_SOLID, 0, 0x000000)
    for column, value in enumerate((0, 3, 0x101, 0xFFFFFFFF)):
        box = d.rect(2 + 16 * column, 92, 14 + 16 * column, 104)
        d.add(fixed.SetArcDirection(2), fixed.SetArcDirection(value))
        d.add(fixed.Arc(*box, box[2], (box[1] + box[3]) // 2, box[0], box[1]))
    d.add(fixed.SetArcDirection(1))


def color_adjustment_combos(d):
    """Colour adjustment steps in combination, on every channel level.

    The source holds all 256 levels in each channel; each panel stretches it
    2x in HALFTONE under one combination of reference black and white,
    per-channel gamma, the log filter, contrast, brightness and negative.
    """
    info, bits = rgb_dib(16, 16, lambda x, y: (16 * y + x, 255 - (16 * y + x), (7 * (16 * y + x)) % 256))
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
    d.add(fixed.SetStretchBltMode(HALFTONE))
    combos = (
        # (flags, rg, gg, bg, black, white, contrast, brightness)
        (0, 18000, 8000, 25000, 0, 10000, 40, 0),
        (0, 15000, 15000, 15000, 0, 10000, 0, 30),
        (2, 10000, 10000, 10000, 0, 10000, -30, 20),  # CA_LOG_FILTER
        (1, 12000, 9000, 10000, 0, 10000, 25, -15),  # CA_NEGATIVE
        (0, 10000, 10000, 10000, 1000, 8500, 35, 10),
        (3, 20000, 6500, 13000, 800, 9000, -45, 40),
        (2, 25000, 25000, 25000, 2000, 7000, 0, 0),
        (1, 10000, 10000, 10000, 3000, 6000, -100, -100),
    )
    for index, (flags, rg, gg, bg, black, white, contrast, brightness) in enumerate(combos):
        d.add(fixed.SetColorAdjustment(24, flags, 0, rg, gg, bg, black, white, contrast, brightness, 0, 0))
        x, y = 32 * (index % 4), 32 * (index // 4)
        fields = (x, y, 0, 0, 16, 16, offset, len(info), offset + len(info), len(bits), 0, SRCCOPY)
        d.add(bitmaps.StretchDIBits(0, 0, 0, 0, *fields, 32, 32, info + bits))


def background_mode_values(d):
    """Raw SetBkMode values with each primitive that draws a background.

    Rows set 0, 1, 2, 3, 0x101 and 0xFFFF; columns draw a hatched PatBlt, a
    hatched Rectangle, a hatched Polygon, a hatched FillRgn, a hatched
    PATCOPY BitBlt and a dashed cosmetic line.
    """
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x30A0E0)
    d.add(fixed.Rectangle(0, 0, d.extent + 1, d.extent + 1))
    d.add(fixed.SetBkColor(0x00FFFF))
    hatch = d.brush(BS_HATCHED, 0x800080, HS_DIAGCROSS)
    blit = dict.fromkeys(bitmaps.BitBlt.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "data": b""}
    for row, value in enumerate((0, 1, 2, 3, 0x101, 0xFFFF)):
        top = 2 + 21 * row
        d.add(fixed.SetBkMode(value))
        d.add(bitmaps.BitBlt(**blit | {"x": 2, "y": top, "width": 18, "height": 18, "rop": PATCOPY}))
        d.add(fixed.Rectangle(23, top, 41, top + 18))
        d.add(variable.Polygon((0, 0, 0, 0), ((44, top), (62, top), (53, top + 18))))
        region = region_data(((65, top, 83, top + 18),))
        d.add(variable.FillRgn(bounds=(0, 0, 0, 0), brush=hatch, region=region))
        d.add(bitmaps.BitBlt(**blit | {"x": 86, "y": top, "width": 18, "height": 18, "rop": 0x005A0049}))  # PATINVERT
        d.add(fixed.SelectObject(STOCK | 7))
        dash = d.pen(PS_DASH, 0, 0x000000)
        d.add(fixed.MoveToEx(107, top + 4), fixed.LineTo(126, top + 4), fixed.MoveToEx(107, top + 12))
        d.add(fixed.LineTo(126, top + 12), fixed.SelectObject(STOCK | 8), fixed.DeleteObject(dash))


def state_record(*records):
    """Records that should not change a bitmap DC's output, followed by drawing."""

    def draw(d):
        d.add(*records)
        d.brush(BS_SOLID, 0x2040C0)
        d.add(fixed.Rectangle(*d.rect(10, 10, 118, 60)), fixed.SetStretchBltMode(HALFTONE))
        info, bits = rgb_dib(16, 12, gradient)
        offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
        stretch = (d.u(10), d.u(66), 0, 0, 16, 12, offset, len(info), offset + len(info), len(bits), 0, SRCCOPY)
        d.add(bitmaps.StretchDIBits(0, 0, 0, 0, *stretch, d.u(108), d.u(52), info + bits))

    return draw


COLOR_SPACE = struct.pack("<5I", 0x50534F43, 0x400, 328, 0x73524742, 4) + bytes(308)
STATE_RECORDS = {
    "icm-on": (fixed.SetICMMode(2),),
    "icm-off": (fixed.SetICMMode(1),),
    "miter-limit": (fixed.SetMiterLimit(4),),
    "mapper-flags": (fixed.SetMapperFlags(1),),
    "color-adjustment": (fixed.SetColorAdjustment(24, 0, 0, 10000, 10000, 10000, 0, 10000, 50, -50, 0, 0),),
    "color-space": (system.CreateColorSpace(5, COLOR_SPACE), fixed.SetColorSpace(5), fixed.DeleteColorSpace(5)),
    "color-correct-palette": (fixed.ColorCorrectPalette(1, 0, 0, 0),),
    "icm-profile": (system.SetICMProfileA(0, b"sRGB\0\0\0\0"),),
    "color-match": (system.ColorMatchToTargetW(1, 0, b"", b""),),
    "font-mapping": (fixed.ForceUFIMapping(1, 2), system.SetLinkedUFIs(((1, 2),))),
    "opengl": (system.GlsRecord(bytes(8)), system.GlsBoundedRecord((0, 0, 1, 1), bytes(8))),
    "pixel-format": (system.PixelFormat(bytes(40)),),
    "escapes": (system.DrawEscape(0x1000, bytes(4)), system.ExtEscape(0x1000, bytes(4))),
    "named-escape": (system.NamedEscape(0x1000, b"x\0\0\0", b""),),
}


# (name, draw, extents): 128 plays 1:1, 51 at a non-integer 2.5x.
FEATURES = (
    ("background", background_modes, (128, 51)),
    ("fill-modes", fill_modes, (128, 51)),
    ("curves", curves, (128, 51)),
    ("paths", paths, (128, 51)),
    ("extended-pens", extended_pens, (128, 51)),
    ("brushes", brushes, (128, 51)),
    ("clip-regions", clip_regions, (128, 51)),
    ("regions", regions, (128, 51)),
    ("maskblt", mask_blt(True), (128, 51)),
    ("maskblt-unmasked", mask_blt(False), (128,)),
    ("plgblt", plg_blt(False), (128, 51)),
    ("plgblt-masked", plg_blt(True), (128,)),
    ("alphablend", alpha_blend(True), (128, 51)),
    ("alphablend-constant", alpha_blend(False), (128,)),
    ("transparentblt", transparent_blt, (128, 51)),
    ("source-transforms", source_transforms, (128, 51)),
    ("palette-sources", palette_sources, (128,)),
    ("blend-sources", blend_sources, (128,)),
    ("scan-bands", scan_bands, (128, 51)),
    ("offset-ties", offset_ties, (128,)),
    *(
        (f"color-engine-{name}-{orientation}", color_engine(orientation, transfers), (128,))
        for name, transfers in (
            ("replicated", ENGINE_REPLICATED),
            ("filtered", ENGINE_FILTERED),
            ("offset", ENGINE_OFFSET),
            ("reduced", ENGINE_REDUCED),
            ("large", ENGINE_LARGE),
        )
        for orientation in ("top-down", "bottom-up")
    ),
    ("gradientfill", gradients, (128, 51)),
    ("gradient-edges", gradient_edges, (128,)),
    ("rotated-frames", rotated_frames, (128, 51)),
    ("palettes", palettes, (128,)),
    ("flood-fill", flood_fills, (128, 51)),
    ("layout", layout, (128,)),
    ("rotation", rotation, (128, 51)),
    ("save-levels", save_levels, (128,)),
    ("comments", comments, (128,)),
    ("record-culling", record_culling(False), (128, 51)),
    ("record-culling-dense", record_culling(True), (128,)),
    ("nested-reset", nested_reset, (128,)),
    ("transform-limits", transform_limits, (51,)),
    ("gradient-rop2", gradient_rop2, (128,)),
    ("rotated-insideframe", rotated_insideframe, (128, 51)),
    ("rotated-color-adjustment", rotated_color_adjustment, (128,)),
    ("widened-curves", widened_curves, (128, 51)),
    ("dashed-curves", dashed_curves, (128, 51)),
    ("text-modes", text_modes, (128, 51)),
    ("text-transforms", text_transforms, (128, 51)),
    ("text-records", text_records, (128, 51)),
    ("text-transform-styles", text_transform_styles, (128, 51)),
    ("plgblt-mirrored-masks", plgblt_mirrored_masks, (128,)),
    ("rle-bands", rle_bands, (128,)),
    ("invalid-modes", invalid_modes, (128,)),
    ("color-adjustment-combos", color_adjustment_combos, (128,)),
    ("background-mode-values", background_mode_values, (128,)),
    *((f"state-{name}", state_record(*records), (128,)) for name, records in STATE_RECORDS.items()),
)
SCALE_NAMES = {128: "unit", 51: "up-2-5"}


def cases(drawing_class):
    for name, draw, extents in FEATURES:
        for extent in extents:
            drawing = drawing_class(extent)
            draw(drawing)
            yield f"emf-{name}-{SCALE_NAMES[extent]}", drawing.metafile()
