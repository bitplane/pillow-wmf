"""EMF fixtures for every remaining drawing, state and transfer feature.

Each drawing uses the 128-unit design grid of generate-emf-fixtures.py. Features
whose output depends on the playback transform are also recorded at a
non-integer frame scale.
"""

import math
import struct

from pillow_wmf.emf import Metafile, bitmaps, fixed, system, variable

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


def transfers(d):
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x80C080)
    d.add(fixed.Rectangle(0, 0, d.extent + 1, d.extent + 1))
    source = rgb_dib(16, 12, gradient)
    mask = mono_dib(16, 12, lambda x, y: (x // 4 + y // 4) % 2, ((0, 0, 0), (255, 255, 255)))
    # One (offset, size) pair per block: source info, source bits, mask info, mask bits.
    (bmi, bits, minfo, mbits), data = offset_fields(bitmaps.MaskBlt, source[0], source[1], mask[0], mask[1])
    fields = dict.fromkeys(bitmaps.MaskBlt.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "background": 0xFFFFFF}
    # MAKEROP4(SRCCOPY, DSTCOPY): the source where the mask is 1, the destination elsewhere.
    fields |= {"x": d.u(4), "y": d.u(4), "width": 16, "height": 12, "rop": 0xAACC0020}
    fields |= {"bitmap_offset": bmi[0], "bitmap_size": bmi[1], "bits_offset": bits[0], "bits_size": bits[1]}
    fields |= {"mask_offset": minfo[0], "mask_size": minfo[1], "mask_bits_offset": mbits[0], "mask_bits_size": mbits[1]}
    d.add(bitmaps.MaskBlt(**fields, data=data))
    unmasked = {"x": d.u(44), "mask_size": 0, "mask_bits_size": 0, "mask_offset": 0, "mask_bits_offset": 0}
    d.add(bitmaps.MaskBlt(**fields | unmasked, data=data))
    (bmi, bits, minfo, mbits), data = offset_fields(bitmaps.PlgBlt, source[0], source[1], mask[0], mask[1])
    fields = dict.fromkeys(bitmaps.PlgBlt.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "background": 0xFFFFFF}
    fields |= {"x0": d.u(96), "y0": d.u(4), "x1": d.u(124), "y1": d.u(14), "x2": d.u(86), "y2": d.u(30)}
    fields |= {"src_width": 16, "src_height": 12}
    fields |= {"bitmap_offset": bmi[0], "bitmap_size": bmi[1], "bits_offset": bits[0], "bits_size": bits[1]}
    d.add(bitmaps.PlgBlt(**fields, data=data))
    d.add(
        bitmaps.PlgBlt(
            **fields
            | {
                "y0": d.u(36),
                "y1": d.u(46),
                "y2": d.u(62),
                "mask_offset": minfo[0],
                "mask_size": minfo[1],
                "mask_bits_offset": mbits[0],
                "mask_bits_size": mbits[1],
            },
            data=data,
        )
    )
    alpha = argb_dib(16, 12)
    (bmi, bits), data = offset_fields(bitmaps.AlphaBlend, *alpha)
    fields = dict.fromkeys(bitmaps.AlphaBlend.fields, 0) | {
        "src_m11": 1.0,
        "src_m22": 1.0,
        "src_width": 16,
        "src_height": 12,
    }
    fields |= {"bitmap_offset": bmi[0], "bitmap_size": bmi[1], "bits_offset": bits[0], "bits_size": bits[1]}
    d.add(
        bitmaps.AlphaBlend(
            **fields | {"x": d.u(4), "y": d.u(40), "width": d.u(30), "height": d.u(22), "blend": 0x01FF0000}, data=data
        )
    )
    (bmi, bits), opaque = offset_fields(bitmaps.AlphaBlend, *source)
    fields |= {"bitmap_offset": bmi[0], "bitmap_size": bmi[1], "bits_offset": bits[0], "bits_size": bits[1]}
    d.add(
        bitmaps.AlphaBlend(
            **fields | {"x": d.u(40), "y": d.u(40), "width": d.u(30), "height": d.u(22), "blend": 0x00800000},
            data=opaque,
        )
    )
    (bmi, bits), data = offset_fields(bitmaps.TransparentBlt, *source)
    fields = dict.fromkeys(bitmaps.TransparentBlt.fields, 0) | {
        "src_m11": 1.0,
        "src_m22": 1.0,
        "src_width": 16,
        "src_height": 12,
    }
    fields |= {"bitmap_offset": bmi[0], "bitmap_size": bmi[1], "bits_offset": bits[0], "bits_size": bits[1]}
    key = gradient(5, 5)
    fields |= {
        "x": d.u(4),
        "y": d.u(70),
        "width": d.u(40),
        "height": d.u(30),
        "transparent": key[0] | key[1] << 8 | key[2] << 16,
    }
    d.add(bitmaps.TransparentBlt(**fields, data=data))
    vertices = ((d.u(50), d.u(68), 0xFF00, 0, 0, 0), (d.u(80), d.u(90), 0, 0, 0xFF00, 0))
    d.add(variable.GradientFill((0, 0, 0, 0), 0, vertices, ((0, 1),)))
    vertices = ((d.u(84), d.u(68), 0xFF00, 0xFF00, 0, 0), (d.u(124), d.u(90), 0, 0x8000, 0xFF00, 0))
    d.add(variable.GradientFill((0, 0, 0, 0), 1, vertices, ((0, 1),)))
    vertices = (
        (d.u(50), d.u(124), 0xFF00, 0, 0, 0),
        (d.u(84), d.u(96), 0, 0xFF00, 0, 0),
        (d.u(124), d.u(124), 0, 0, 0xFF00, 0),
    )
    d.add(variable.GradientFill((0, 0, 0, 0), 2, vertices, ((0, 1, 2),)))


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


def state_records(d):
    """Records that should not change a bitmap DC's output, each followed by drawing."""
    d.add(fixed.SetICMMode(2), fixed.SetMiterLimit(4), fixed.SetMapperFlags(1))
    d.add(fixed.SetColorAdjustment(24, 0, 0, 10000, 10000, 10000, 0, 10000, 50, -50, 0, 0))
    d.add(system.CreateColorSpace(5, struct.pack("<5I", 0x50534F43, 0x400, 328, 0x73524742, 4) + bytes(308)))
    d.add(fixed.SetColorSpace(5), fixed.DeleteColorSpace(5), fixed.ColorCorrectPalette(1, 0, 0, 0))
    d.add(system.SetICMProfileA(0, b"sRGB\0\0\0\0"), system.ColorMatchToTargetW(1, 0, b"", b""))
    d.add(fixed.ForceUFIMapping(1, 2), system.SetLinkedUFIs(((1, 2),)))
    d.add(system.GlsRecord(bytes(8)), system.PixelFormat(bytes(40)))
    d.add(
        system.DrawEscape(0x1000, bytes(4)),
        system.ExtEscape(0x1000, bytes(4)),
        system.NamedEscape(0x1000, b"x\0\0\0", b""),
    )
    d.brush(BS_SOLID, 0x2040C0)
    d.add(fixed.Rectangle(*d.rect(10, 10, 118, 60)), fixed.SetStretchBltMode(HALFTONE))
    info, bits = rgb_dib(16, 12, gradient)
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)
    d.add(
        bitmaps.StretchDIBits(
            0,
            0,
            0,
            0,
            d.u(10),
            d.u(66),
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
            d.u(108),
            d.u(52),
            info + bits,
        )
    )


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
    ("transfers", transfers, (128, 51)),
    ("palettes", palettes, (128,)),
    ("flood-fill", flood_fills, (128, 51)),
    ("layout", layout, (128,)),
    ("rotation", rotation, (128, 51)),
    ("save-levels", save_levels, (128,)),
    ("comments", comments, (128,)),
    ("state-records", state_records, (128,)),
)
SCALE_NAMES = {128: "unit", 51: "up-2-5"}


def cases(drawing_class):
    for name, draw, extents in FEATURES:
        for extent in extents:
            drawing = drawing_class(extent)
            draw(drawing)
            yield f"emf-{name}-{SCALE_NAMES[extent]}", drawing.metafile()
