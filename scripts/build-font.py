"""Build the packaged, metric-compatible Wingdings subset from Noto outlines."""

import argparse
from pathlib import Path

from pillow_wmf.wingdings import FALLBACK_FAMILY, decode_wingdings

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/fonts/NotoSansSymbols2-Regular.ttf"
METRICS = ROOT / "src/fonts/wingdings-metrics.txt"
OUTPUT = ROOT / "src/pillow_wmf/fonts/PillowWMFWingdingsFallback.ttf"


def build_font(data, metrics):
    """Fit supplied Unicode outlines to Wingdings design-space metrics.

    One affine rule applies to every mapped glyph, independently of the WMF,
    requested size and canvas. This preserves legacy placement/advances, not
    the original artwork. The derivative is renamed and retains Noto's OFL.
    """
    from io import BytesIO

    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.pens.transformPen import TransformPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont

    with TTFont(BytesIO(data)) as source:
        glyph_set = source.getGlyphSet()
        cmap = source.getBestCmap()
        outlines, widths, encoding = {}, {}, {}

        def outline(name, transform):
            recording = DecomposingRecordingPen(glyph_set)
            glyph_set[name].draw(recording)
            pen = TTGlyphPen(None)
            recording.replay(TransformPen(pen, transform))
            return pen.glyph()

        em_scale = 2048 / source["head"].unitsPerEm
        outlines[".notdef"] = outline(".notdef", (em_scale, 0, 0, em_scale, 0, 0))
        widths[".notdef"] = tuple(round(v * em_scale) for v in source["hmtx"][".notdef"])
        for line in metrics.splitlines():
            if not line or line.startswith("#"):
                continue
            byte, *values = line.split()
            codepoint = ord(decode_wingdings(bytes([int(byte, 16)])))
            if codepoint not in cmap:
                continue
            advance, left, bottom, right, top = map(int, values)
            name = cmap[codepoint]
            glyph = source["glyf"][name]
            if glyph.numberOfContours:
                sx = (right - left) / (glyph.xMax - glyph.xMin)
                sy = (top - bottom) / (glyph.yMax - glyph.yMin)
                transform = (sx, 0, 0, sy, left - glyph.xMin * sx, bottom - glyph.yMin * sy)
            else:
                transform = (em_scale, 0, 0, em_scale, 0, 0)
            target = f"u{codepoint:04X}"
            encoding[codepoint] = target
            outlines[target] = outline(name, transform)
            widths[target] = advance, left

        builder = FontBuilder(2048, isTTF=True)
        builder.setupGlyphOrder(list(outlines))
        builder.setupCharacterMap(encoding)
        builder.setupGlyf(outlines)
        builder.setupHorizontalMetrics(widths)
        builder.setupHorizontalHeader(ascent=1841, descent=-432)
        names = source["name"]
        builder.setupNameTable(
            {
                "familyName": FALLBACK_FAMILY,
                "styleName": "Regular",
                "uniqueFontIdentifier": FALLBACK_FAMILY,
                "fullName": FALLBACK_FAMILY,
                "psName": "PillowWMFWingdingsFallback",
                "version": "Version 1.0",
                "copyright": names.getDebugName(0) or "",
                "licenseDescription": names.getDebugName(13) or "",
                "licenseInfoURL": names.getDebugName(14) or "",
            }
        )
        builder.setupOS2(
            sTypoAscender=1841,
            sTypoDescender=-432,
            usWinAscent=1841,
            usWinDescent=432,
            xAvgCharWidth=1822,
            yStrikeoutPosition=800,
            yStrikeoutSize=100,
            ulCodePageRange1=1,
        )
        builder.setupPost(underlinePosition=-200, underlineThickness=100)
        builder.font["head"].created = builder.font["head"].modified = 2082844800
        builder.font.recalcTimestamp = False
        output = BytesIO()
        builder.save(output)
        return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    data = build_font(SOURCE.read_bytes(), METRICS.read_text())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.exists() or args.output.read_bytes() != data:
        args.output.write_bytes(data)
    else:
        args.output.touch()
    print(f"{args.output}: {len(data)} bytes")


if __name__ == "__main__":
    main()
