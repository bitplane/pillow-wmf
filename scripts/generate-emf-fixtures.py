"""Generate the EMF compatibility fixtures.

Each drawing is laid out on a 128-unit design grid and scaled to a logical
picture of ``extent`` reference-device pixels. The header frame covers that
picture, so native playback onto the 128-pixel canvas scales it by
128 / ``extent``: 1:1 (where the frame fit snaps to an exact unit scale),
up, down, and up by a non-integer factor.
"""

import argparse
import struct
from pathlib import Path

from pillow_wmf.bitmap import RGBBitmap, encode_dib24
from pillow_wmf.emf import Metafile, bitmaps, fixed, variable
from pillow_wmf.mapping import REFERENCE_DEVICE

FIXTURES = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "emf"
EXTENTS = {"unit": 128, "up": 96, "down": 171, "up-2-5": 51}

PS_SOLID, PS_DASH, PS_DOT, PS_NULL = 0, 1, 2, 5
BS_SOLID, BS_HATCHED = 0, 2
HS_DIAGCROSS = 5
R2_XORPEN = 7
SRCCOPY, PATCOPY, DSTINVERT = 0x00CC0020, 0x00F00021, 0x00550009
RGN_COPY = 5


def frame(extent):
    """A frame covering ``extent`` reference pixels on both axes."""
    (pixels_x, pixels_y), (mm_x, mm_y) = REFERENCE_DEVICE.pixels, REFERENCE_DEVICE.millimetres
    return 0, 0, round(extent * mm_x * 100 / pixels_x), round(extent * mm_y * 100 / pixels_y)


class Drawing:
    """Records with explicit object slots, scaled from the 128-unit design grid."""

    def __init__(self, extent):
        self.extent = extent
        self.records = []
        self.slot = 0

    def u(self, value):
        return round(value * self.extent / 128)

    def rect(self, left, top, right, bottom):
        return self.u(left), self.u(top), self.u(right), self.u(bottom)

    def add(self, *records):
        self.records.extend(records)

    def select(self, creation):
        self.slot += 1
        self.add(creation(self.slot), fixed.SelectObject(self.slot))
        return self.slot

    def pen(self, style, width, color):
        return self.select(lambda slot: fixed.CreatePen(slot, style, width, 0, color))

    def brush(self, style, color, hatch=0):
        return self.select(lambda slot: fixed.CreateBrushIndirect(slot, style, color, hatch))

    def metafile(self):
        return Metafile.build(self.records, frame=frame(self.extent))


def shapes(d):
    d.add(fixed.Rectangle(*d.rect(8, 8, 40, 30)))
    d.add(fixed.Ellipse(*d.rect(48, 8, 80, 30)))
    d.add(fixed.RoundRect(*d.rect(88, 8, 120, 30), d.u(10), d.u(8)))
    d.pen(PS_SOLID, d.u(3), 0x0000FF)
    d.brush(BS_SOLID, 0xFF0000)
    d.add(fixed.Rectangle(*d.rect(8, 40, 40, 62)))
    d.add(fixed.Ellipse(*d.rect(48, 40, 80, 62)))
    d.pen(PS_NULL, 0, 0)
    d.brush(BS_SOLID, 0x00A000)
    d.add(fixed.Rectangle(*d.rect(88, 40, 120, 62)))
    d.pen(PS_SOLID, 0, 0x000000)
    d.brush(BS_HATCHED, 0x800080, HS_DIAGCROSS)
    d.add(fixed.Rectangle(*d.rect(8, 72, 40, 94)))
    d.add(fixed.Pie(*d.rect(48, 72, 80, 94), *d.rect(80, 72, 48, 94)))
    d.add(fixed.Chord(*d.rect(88, 72, 120, 94), *d.rect(88, 72, 120, 94)))
    d.add(fixed.Arc(*d.rect(8, 104, 40, 126), *d.rect(40, 115, 8, 104)))
    star = ((64, 104), (70, 126), (50, 112), (78, 112), (58, 126))
    d.add(variable.Polygon((0, 0, 0, 0), tuple((d.u(x), d.u(y)) for x, y in star)))
    zigzag = ((88, 126), (96, 104), (104, 126), (112, 104), (120, 126))
    d.add(variable.Polyline16((0, 0, 0, 0), tuple((d.u(x), d.u(y)) for x, y in zigzag)))


def lines(d):
    row = 6
    for style, width, color in (
        (PS_SOLID, 0, 0x000000),
        (PS_SOLID, 1, 0x0000FF),
        (PS_DASH, 1, 0x00A000),
        (PS_DOT, 0, 0xFF0000),
        (PS_SOLID, 2, 0x000080),
        (PS_SOLID, 4, 0x008080),
        (PS_SOLID, 7, 0x800000),
    ):
        d.pen(style, d.u(width) if width > 1 else width, color)
        d.add(fixed.MoveToEx(d.u(6), d.u(row)), fixed.LineTo(d.u(60), d.u(row)))
        d.add(fixed.MoveToEx(d.u(68), d.u(row + 10)), fixed.LineTo(d.u(122), d.u(row)))
        row += 16
    d.pen(PS_SOLID, 0, 0x00FFFF)
    d.add(fixed.SetROP2(R2_XORPEN))
    d.add(fixed.MoveToEx(d.u(6), d.u(120)), fixed.LineTo(d.u(122), d.u(4)))
    d.add(fixed.MoveToEx(d.u(6), d.u(4)), fixed.LineTo(d.u(122), d.u(120)))


def checker():
    colours = ((255, 0, 0), (0, 160, 0), (0, 0, 255), (255, 255, 0), (0, 0, 0), (255, 255, 255))
    pixels = bytes(value for colour in colours for value in colour)
    dib = encode_dib24(RGBBitmap(3, 2, pixels)).data
    return dib[:40], dib[40:]


def dib_transfers(d):
    info, bits = checker()
    offset = 8 + struct.calcsize("<" + bitmaps.StretchDIBits.wire_layout)

    def stretch(left, top, width, height):
        d.add(
            bitmaps.StretchDIBits(
                0,
                0,
                0,
                0,
                d.u(left),
                d.u(top),
                0,
                0,
                3,
                2,
                offset,
                len(info),
                offset + len(info),
                len(bits),
                0,
                SRCCOPY,
                d.u(width),
                d.u(height),
                info + bits,
            )
        )

    stretch(8, 8, 48, 32)
    stretch(120, 8, -48, 32)
    stretch(8, 88, 48, -32)
    stretch(72, 56, 6, 4)
    offset = 8 + struct.calcsize("<" + bitmaps.SetDIBitsToDevice.wire_layout)
    d.add(
        bitmaps.SetDIBitsToDevice(
            0,
            0,
            0,
            0,
            d.u(96),
            d.u(100),
            0,
            0,
            3,
            2,
            offset,
            len(info),
            offset + len(info),
            len(bits),
            0,
            0,
            2,
            info + bits,
        )
    )


def clipping(d):
    d.brush(BS_SOLID, 0x0080FF)
    d.add(fixed.IntersectClipRect(*d.rect(20, 20, 108, 108)))
    d.add(fixed.ExcludeClipRect(*d.rect(50, 40, 78, 88)))
    d.add(fixed.Rectangle(*d.rect(0, 0, 128, 128)))


def region_clip(d):
    """Region data is in reference-device pixels, not logical units."""
    rectangles = ((10, 10, 60, 40), (30, 50, 100, 90))
    data = struct.pack("<4I4i", 32, 1, len(rectangles), 16 * len(rectangles), 10, 10, 100, 90)
    data += b"".join(struct.pack("<4i", *rectangle) for rectangle in rectangles)
    d.add(variable.ExtSelectClipRgn(RGN_COPY, data))
    d.brush(BS_SOLID, 0x00C000)
    d.add(fixed.Rectangle(*d.rect(0, 0, 128, 128)))


def pattern_blits(d):
    d.brush(BS_SOLID, 0xC00000)
    blit = dict.fromkeys(bitmaps.BitBlt.fields, 0) | {"src_m11": 1.0, "src_m22": 1.0, "data": b""}

    def pat_blt(left, top, width, height, rop):
        d.add(
            bitmaps.BitBlt(
                **blit | {"x": d.u(left), "y": d.u(top), "width": d.u(width), "height": d.u(height), "rop": rop}
            )
        )

    pat_blt(8, 8, 60, 40, PATCOPY)
    pat_blt(40, 30, 80, 60, DSTINVERT)
    pat_blt(100, 110, -30, -12, PATCOPY)


def markers(d):
    for index in range(d.extent):
        d.add(
            fixed.SetPixelV(index, index, index + 1),
            fixed.SetPixelV(index, d.extent - 1 - index, 0x010000 * (index + 1)),
        )


CONTENT = {
    "shapes": shapes,
    "lines": lines,
    "dib": dib_transfers,
    "clip": clipping,
    "region-clip": region_clip,
    "patblt": pattern_blits,
    "markers": markers,
}


def page_cases():
    """Page mappings played at 1:1; the mapping is folded into the playback transform."""
    unit = Drawing(128)
    unit.add(fixed.SetMapMode(2))  # MM_LOMETRIC: 0.1 mm units, y up.
    unit.add(fixed.Rectangle(50, -50, 250, -200), fixed.Ellipse(150, -150, 330, -330))
    yield "emf-page-lometric", unit.metafile()
    anisotropic = Drawing(128)
    anisotropic.add(
        fixed.SetMapMode(8),
        fixed.SetWindowOrgEx(-100, 50),
        fixed.SetWindowExtEx(1000, -700),
        fixed.SetViewportOrgEx(5, 120),
        fixed.SetViewportExtEx(113, 97),
    )
    anisotropic.add(fixed.Rectangle(0, 0, 400, 300), fixed.Ellipse(300, 200, 800, 900))
    anisotropic.add(fixed.MoveToEx(-100, 50), fixed.LineTo(900, -650))
    yield "emf-page-anisotropic", anisotropic.metafile()
    isotropic = Drawing(128)
    isotropic.add(fixed.SetMapMode(7), fixed.SetWindowExtEx(200, 100), fixed.SetViewportExtEx(128, 128))
    isotropic.add(fixed.Rectangle(10, 10, 190, 90), fixed.Ellipse(20, 20, 180, 80))
    yield "emf-page-isotropic", isotropic.metafile()
    scaled = Drawing(51)
    scaled.add(fixed.SetMapMode(8), fixed.SetWindowExtEx(128, 128), fixed.SetViewportExtEx(51, 51))
    shapes_on_grid = Drawing(128)
    shapes(shapes_on_grid)
    scaled.add(*shapes_on_grid.records)
    yield "emf-page-scaled-shapes", scaled.metafile()


def cases():
    for content, draw in CONTENT.items():
        for scale, extent in EXTENTS.items():
            drawing = Drawing(extent)
            draw(drawing)
            yield f"emf-{content}-{scale}", drawing.metafile()
    yield from page_cases()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FIXTURES)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    for name, metafile in cases():
        (args.output / f"{name}.emf").write_bytes(metafile.to_bytes())
        print(name)


if __name__ == "__main__":
    main()
