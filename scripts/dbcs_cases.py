"""Controlled mixed-width CP932 text and byte-indexed spacing probes."""

from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont

from pillow_wmf import Font, Recorder

FAMILY = "Pillow WMF CP932"
EXTENDED_FAMILY = "Pillow WMF DBCS"
EXTENDED_CODEPAGES = {936: (134, 18, "一"), 949: (129, 19, "가"), 950: (136, 20, "一"), 1361: (130, 21, "가")}


def extended_font_bytes():
    with TTFont(BytesIO(font_bytes()), recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                name = EXTENDED_FAMILY.replace(" ", "") if record.nameID == 6 else EXTENDED_FAMILY
                record.string = name.encode(record.getEncoding())
        for table in font["cmap"].tables:
            table.cmap.update({ord("一"): "B", ord("가"): "B"})
        font["OS/2"].ulCodePageRange1 |= sum(1 << bit for _, bit, _ in EXTENDED_CODEPAGES.values())
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def extended_cases():
    for mode, advances, options in (
        ("natural", (), 0),
        ("split", (9, 5, 7, 13), 0),
        ("pdy", (9, 1, 5, 2, 7, 3, 13, -6), 0x2000),
    ):
        r = Recorder()
        r.set_background_mode(1)
        r.set_text_alignment(25)
        for row, (codepage, (charset, _, character)) in enumerate(EXTENDED_CODEPAGES.items()):
            r.select_object(
                r.create_font(
                    Font(
                        face_name=EXTENDED_FAMILY.encode().ljust(32, b"\0"),
                        height=-16,
                        weight=400,
                        charset=charset,
                        quality=3,
                    )
                )
            )
            r.move_to(8, 24 + row * 30)
            r.ext_text_out(0, 0, b"A" + character.encode(f"cp{codepage}") + b"B", advances=advances, options=options)
            r.text_out(0, 0, b"B")
        yield f"dbcs-{mode}", r


def font_bytes():
    with TTFont(Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf", recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                record.string = (
                    FAMILY.replace(" ", "").encode(record.getEncoding())
                    if record.nameID == 6
                    else FAMILY.encode(record.getEncoding())
                )
        for table in font["cmap"].tables:
            table.cmap.update({0x0393: "B", 0x3042: "A", 0xFF71: "B", 0x4E00: "A"})
        font["OS/2"].ulCodePageRange1 |= 1 << 17
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def cases():
    for name, advances, options in (
        ("natural", (), 0),
        ("split", (9, 5, 7, 13), 0),
        ("whole", (9, 12, 0, 13), 0),
        ("pdy", (9, 1, 5, 2, 7, 3, 13, -6), 0x2000),
    ):
        r = Recorder()
        r.set_background_mode(1)
        r.select_object(
            r.create_font(
                Font(
                    face_name=FAMILY.encode().ljust(32, b"\0"),
                    height=-20,
                    weight=400,
                    charset=128,
                    quality=3,
                )
            )
        )
        r.set_text_alignment(25)
        r.move_to(10, 32)
        r.ext_text_out(0, 0, b"A\x83\xa1B", advances=advances, options=options)
        r.text_out(0, 0, b"B")
        r.set_text_alignment(24)
        r.text_out(10, 70, b"\x82\xa0\xb1\x88\xea")
        r.set_text_character_extra(3)
        r.ext_text_out(10, 110, b"A\x83\xa1B", advances=advances, options=options)
        yield f"cp932-{name}", r
