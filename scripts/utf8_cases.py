"""Controlled UTF-8 glyphs and byte-array spacing probes."""

from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from pillow_wmf import Font, Recorder

FAMILY = "Pillow WMF UTF8"


def font_bytes():
    with TTFont(Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf", recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                name = FAMILY.replace(" ", "") if record.nameID == 6 else FAMILY
                record.string = name.encode(record.getEncoding())
        for table in font["cmap"].tables:
            # Also cover the ANSI interpretation so unexpected conversion does
            # not silently invoke a system fallback font.
            table.cmap.update({ord(bytes([b]).decode("cp1252", "replace")): "A" for b in range(128, 256)})
            table.cmap.update({0xE9: "B", 0x4E00: "B", 0xFFFD: "A"})
        supplementary = CmapSubtable.newSubtable(12)
        supplementary.platformID, supplementary.platEncID, supplementary.language = 3, 10, 0
        supplementary.cmap = font.getBestCmap() | {0x10000: "B"}
        font["cmap"].tables.append(supplementary)
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def cases():
    for mode in ("natural", "dx", "pdy"):
        r = Recorder()
        r.set_background_mode(1)
        r.set_text_alignment(25)
        r.select_object(
            r.create_font(
                Font(face_name=FAMILY.encode().ljust(32, b"\0"), charset=254, height=-16, weight=400, quality=3)
            )
        )
        for row, data in enumerate(("AéB".encode(), "A一B".encode(), "A\U00010000B".encode(), b"A\xe1\x80B")):
            r.move_to(8, 24 + row * 30)
            dx = tuple(9 + i * 2 for i in range(len(data))) if mode != "natural" else ()
            if mode == "pdy":
                dx = tuple(value for i, advance in enumerate(dx) for value in (advance, i + 1))
            r.ext_text_out(0, 0, data, advances=dx, options=0x2000 if mode == "pdy" else 0)
            r.set_text_color(0x0000FF)
            r.text_out(0, 0, b"B")
            r.set_text_color(0)
        yield f"utf8-{mode}", r
