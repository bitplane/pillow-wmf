"""Original controlled fonts for Windows code-page probes."""

from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont

from pillow_wmf import Font, Recorder

SINGLE_BYTE = {
    1255: (177, 5, bytes.fromhex("E0 FA A4")),
    1256: (178, 6, bytes.fromhex("C7 E1 A1")),
    1258: (163, 8, bytes.fromhex("D5 EC F5")),
    874: (222, 16, bytes.fromhex("A1 D1 E0")),
}


def font_bytes(codepage, bit, sample):
    family = f"Pillow WMF CP{codepage}"
    with TTFont(Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf", recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6):
                name = family.replace(" ", "") if record.nameID == 6 else family
                record.string = name.encode(record.getEncoding())
        characters = sample.decode(f"cp{codepage}")
        for table in font["cmap"].tables:
            table.cmap.update({ord(c): "A" if i % 2 == 0 else "B" for i, c in enumerate(characters)})
        font["OS/2"].ulCodePageRange1 = (1 << bit) | 1
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def single_byte_case():
    recorder = Recorder()
    recorder.set_background_mode(1)
    recorder.set_text_alignment(25)
    for row, (codepage, (charset, _, sample)) in enumerate(SINGLE_BYTE.items()):
        recorder.select_object(
            recorder.create_font(
                Font(
                    face_name=f"Pillow WMF CP{codepage}".encode().ljust(32, b"\0"),
                    charset=charset,
                    height=-16,
                    weight=400,
                    quality=3,
                )
            )
        )
        for column, byte in enumerate(sample):
            recorder.move_to(8 + column * 40, 25 + row * 30)
            recorder.ext_text_out(0, 0, bytes([byte]), advances=(17,))
            recorder.text_out(0, 0, b"B")
    return recorder
