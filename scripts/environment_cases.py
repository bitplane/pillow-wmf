"""Controlled OEM/Mac text, independent of the host's font inventory."""

from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont

from pillow_wmf import Font, Recorder

FAMILY = "Pillow WMF Environment"
OEM_PAGES = (437, 720, 737, 775, 850, 852, 855, 857, 858, 860, 861, 862, 863, 864, 865, 866, 869)
MAC_PAGES = (10000, 10004, 10005, 10006, 10007, 10010, 10017, 10021, 10029, 10079, 10081, 10082)


def font_bytes():
    with TTFont(Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf", recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                name = FAMILY.replace(" ", "") if record.nameID == 6 else FAMILY
                record.string = name.encode(record.getEncoding())
        for table in font["cmap"].tables:
            table.cmap.update({ord(c): "A" if i % 2 == 0 else "B" for i, c in enumerate("ÇéÄÈ")})
        font["OS/2"].ulCodePageRange1 = 1 | (1 << 29) | (1 << 30)
        font["OS/2"].ulCodePageRange2 = 0xFFFF0000
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def cases():
    r = Recorder()
    r.set_background_mode(1)
    r.set_text_alignment(25)
    for row, charset in enumerate((255, 77)):
        r.select_object(
            r.create_font(
                Font(face_name=FAMILY.encode().ljust(32, b"\0"), charset=charset, height=-20, weight=400, quality=3)
            )
        )
        r.move_to(8, 30 + row * 60)
        r.ext_text_out(0, 0, b"\x80\x82AB", advances=(17, 19, 13, 11))
        r.text_out(0, 0, b"B")
    yield "text-oem-mac", r
