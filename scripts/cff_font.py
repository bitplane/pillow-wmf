"""Build the controlled CFF-outline OpenType face.

The outlines are original test geometry, not extracted from another font:
A and B repeat the layout font's shapes (``test_font.py``) as unhinted CFF
charstrings, C is a ring of four cubic arcs around a square hole, and D, E
and F are thin diagonal strokes, a hairline frame and a narrow wedge, so
PostScript-outline faces can be tested against the TrueType face.
FontTools is a development dependency; tests use the committed OTF.
"""

from io import BytesIO
from pathlib import Path

FAMILY = "Pillow WMF CFF"
FONT_PATH = Path(__file__).resolve().parents[1] / "test/fonts/cff.otf"
# Counterclockwise outer contours fill CFF outlines (the reverse of TrueType).
POLYGONS = {
    "A": [((50, 0), (550, 0), (550, 200), (250, 200), (250, 700), (50, 700))],
    "B": [((-50, -200), (150, -200), (150, 0), (300, 0), (300, 500), (-50, 500))],
    # Two thin diagonal strokes (a V) and a hairline bar: dropouts.
    "D": [
        ((40, 700), (290, 0), (310, 0), (560, 700), (530, 700), (300, 40), (70, 700)),
        ((40, 330), (560, 330), (560, 350), (40, 350)),
    ],
    # A hairline frame: walls 25 units thick.
    "E": [
        ((40, 0), (540, 0), (540, 600), (40, 600)),
        ((65, 575), (515, 575), (515, 25), (65, 25)),
    ],
    # A narrow wedge and a shallow sliver.
    "F": [((40, 0), (90, 0), (60, 700)), ((120, 300), (600, 330), (600, 345), (120, 315))],
}
ADVANCES = {".notdef": 500, "space": 300, "A": 600, "B": 450, "C": 640, "D": 600, "E": 580, "F": 640}


def _ring(pen):
    # Four cubic quarter arcs around (320, 330) with radius 300, then a square hole.
    k = round(300 * 0.5523)
    cx, cy, r = 320, 330, 300
    pen.moveTo((cx + r, cy))
    pen.curveTo((cx + r, cy + k), (cx + k, cy + r), (cx, cy + r))
    pen.curveTo((cx - k, cy + r), (cx - r, cy + k), (cx - r, cy))
    pen.curveTo((cx - r, cy - k), (cx - k, cy - r), (cx, cy - r))
    pen.curveTo((cx + k, cy - r), (cx + r, cy - k), (cx + r, cy))
    pen.closePath()
    pen.moveTo((cx - 100, cy - 100))
    for point in ((cx - 100, cy + 100), (cx + 100, cy + 100), (cx + 100, cy - 100)):
        pen.lineTo(point)
    pen.closePath()


def font_bytes():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen

    order = [".notdef", "space", "A", "B", "C", "D", "E", "F"]
    builder = FontBuilder(1000, isTTF=False)
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({32: "space", **{ord(name): name for name in order[2:]}})
    charstrings, bearings = {}, {}
    for name in order:
        pen = T2CharStringPen(ADVANCES[name], None)
        if name == ".notdef":
            polygons = [((0, 0), (400, 0), (400, 500), (0, 500))]
        else:
            polygons = POLYGONS.get(name, [])
        for points in polygons:
            pen.moveTo(points[0])
            for point in points[1:]:
                pen.lineTo(point)
            pen.closePath()
        if name == "C":
            _ring(pen)
        charstrings[name] = pen.getCharString()
        xs = [x for points in polygons for x, _ in points] or ([20] if name == "C" else [0])
        bearings[name] = min(xs)
    builder.setupCFF(
        "PillowWMFCFF-Regular", {"FullName": FAMILY, "FamilyName": FAMILY, "Weight": "Regular"}, charstrings, {}
    )
    builder.setupHorizontalMetrics({name: (ADVANCES[name], bearings[name]) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200, lineGap=100)
    builder.setupNameTable(
        {
            "familyName": FAMILY,
            "styleName": "Regular",
            "uniqueFontIdentifier": "PillowWMFCFF-Regular-1",
            "fullName": FAMILY,
            "psName": "PillowWMFCFF-Regular",
            "version": "Version 1.000",
            "licenseDescription": "Original test geometry dedicated to the public domain under CC0 1.0.",
            "licenseInfoURL": "https://creativecommons.org/publicdomain/zero/1.0/",
        }
    )
    builder.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        sTypoLineGap=100,
        usWinAscent=900,
        usWinDescent=300,
        fsType=0,
        fsSelection=0x40,
        ulCodePageRange1=1,
        ulCodePageRange2=0,
    )
    builder.setupPost()
    builder.font["head"].created = builder.font["head"].modified = 3786912000
    stream = BytesIO()
    builder.save(stream)
    return stream.getvalue()


if __name__ == "__main__":
    FONT_PATH.write_bytes(font_bytes())
    print(FONT_PATH)
