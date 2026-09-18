"""Build the project's small, unhinted font for layout experiments.

The outlines are original test geometry, not extracted from another font.
FontTools is a development dependency; native probes use the committed TTF.
"""

from io import BytesIO
from pathlib import Path

FAMILY = "Pillow WMF Test"
FONT_PATH = Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf"


def font_bytes():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    # Different widths, an overhang, a descender and a blank distinguish ink
    # bounds from advances. Clockwise contours are filled TrueType outlines.
    outlines = {
        ".notdef": ((0, 0), (0, 500), (400, 500), (400, 0)),
        "space": (),
        "A": ((50, 0), (50, 700), (250, 700), (250, 200), (550, 200), (550, 0)),
        "B": ((-50, -200), (-50, 500), (300, 500), (300, 0), (150, 0), (150, -200)),
    }
    advances = {".notdef": 500, "space": 300, "A": 600, "B": 450}
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder(list(outlines))
    builder.setupCharacterMap({32: "space", 65: "A", 66: "B"})
    glyphs = {}
    for name, points in outlines.items():
        pen = TTGlyphPen(None)
        if points:
            pen.moveTo(points[0])
            for point in points[1:]:
                pen.lineTo(point)
            pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics(
        {name: (advances[name], min((x for x, _ in points), default=0)) for name, points in outlines.items()}
    )
    builder.setupHorizontalHeader(ascent=800, descent=-200, lineGap=100)
    builder.setupNameTable(
        {
            "familyName": FAMILY,
            "styleName": "Regular",
            "uniqueFontIdentifier": "PillowWMFTest-Regular-1",
            "fullName": FAMILY,
            "psName": "PillowWMFTest-Regular",
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
    # Fixed timestamps keep fixture regeneration byte-for-byte deterministic.
    builder.font["head"].created = builder.font["head"].modified = 3786912000
    stream = BytesIO()
    builder.save(stream)
    return stream.getvalue()


if __name__ == "__main__":
    FONT_PATH.parent.mkdir(parents=True, exist_ok=True)
    FONT_PATH.write_bytes(font_bytes())
    print(FONT_PATH)
