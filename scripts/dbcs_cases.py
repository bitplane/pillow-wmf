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


def spacing_cases():
    """Separate ANSI-array conversion from Unicode Hangul spacing."""
    for gap in (-3, 0, 2, 5, 7, 10):
        for pdy in (False, True):
            r = Recorder()
            r.set_background_mode(1)
            r.set_text_alignment(25)
            for row, (charset, cp, text) in enumerate(
                ((129, 949, "ABB"), (129, 949, "A가B"), (130, 1361, "ABB"), (130, 1361, "A가B"))
            ):
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
                r.move_to(16, 24 + row * 30)
                data = text.encode(f"cp{cp}")
                # Supply equivalent character advances through each ANSI API.
                dx = (
                    (9, gap, 7, 13)
                    if cp == 1361 and len(data) == 4
                    else (9, gap, 0, 7)
                    if len(data) == 4
                    else (9, gap, 7)
                )
                if pdy:
                    dx = tuple(value for advance in dx for value in (advance, 0))
                r.ext_text_out(0, 0, data, advances=dx, options=0x2000 if pdy else 0)
                r.set_text_color(0x0000FF)
                r.text_out(0, 0, b"B")
                r.set_text_color(0)
            yield f"dbcs-spacing-{gap}-{'pdy' if pdy else 'dx'}", r
    # Runs with several unadjustable glyphs distinguish per-glyph clamping
    # from deferred adjustment at the end of a shaped script run.
    for first, second in ((2, 10), (10, 2), (10, 10), (-3, 20)):
        r = Recorder()
        r.set_background_mode(1)
        r.set_text_alignment(25)
        for row, text in enumerate(("A가가B", "A一一B", "AΓΓB", "ABBB")):
            r.select_object(
                r.create_font(
                    Font(
                        face_name=EXTENDED_FAMILY.encode().ljust(32, b"\0"),
                        height=-16,
                        weight=400,
                        charset=129,
                        quality=3,
                    )
                )
            )
            r.move_to(16, 24 + row * 30)
            dx = tuple(
                value
                for char, advance in zip(text, (9, first, second, 7), strict=True)
                for value in ((advance, 0) if len(char.encode("cp949")) == 2 else (advance,))
            )
            r.ext_text_out(0, 0, text.encode("cp949"), advances=dx)
            r.set_text_color(255)
            r.text_out(0, 0, b"B")
            r.set_text_color(0)
        yield f"dbcs-spacing-run-{first}-{second}", r


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
