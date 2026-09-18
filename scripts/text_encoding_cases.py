"""Single-byte encoding and symbol-cmap probes with original controlled fonts."""

import runpy
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (640, 180)
FONT_ROOT = Path(__file__).resolve().parents[1] / "test/fonts"
ENCODING_FAMILY = "Pillow WMF Encoding"
SYMBOL_FAMILY = "Pillow WMF Symbols"


def font_bytes(*, symbol=False):
    original = runpy.run_path(str(Path(__file__).with_name("test_font.py")))["font_bytes"]()
    font = TTFont(BytesIO(original), recalcTimestamp=False)
    family = SYMBOL_FAMILY if symbol else ENCODING_FAMILY
    for record in font["name"].names:
        if symbol and record.platformID == 3:
            record.platEncID = 0
        if record.nameID in (1, 3, 4, 6):
            record.string = family.replace(" ", "") if record.nameID == 6 else family
    table = CmapSubtable.newSubtable(4)
    table.platformID, table.platEncID, table.language = 3, 0 if symbol else 1, 0
    if symbol:
        table.cmap = {0xF020: "space", 0xF041: "A", 0xF042: "B", 0xF080: "A", 0xF0E9: "B", 0xF0FF: "A"}
    else:
        table.cmap = {
            32: "space",
            65: "A",
            66: "B",
            0xE9: "A",
            0x439: "B",
            0x20AC: "B",
            0x402: "A",
            0xC6: "B",
            0x416: "A",
        }
    font["cmap"].tables = [table]
    os2 = font["OS/2"]
    os2.ulCodePageRange1 = 1 << 31 if symbol else (1 | (1 << 2))
    if symbol:
        os2.panose.bFamilyType = 5
        os2.ulUnicodeRange1 = os2.ulUnicodeRange2 = os2.ulUnicodeRange3 = os2.ulUnicodeRange4 = 0
    os2.usFirstCharIndex, os2.usLastCharIndex = min(table.cmap), max(table.cmap)
    stream = BytesIO()
    font.save(stream)
    return stream.getvalue()


def cases():
    profiles = (
        (
            "western",
            "Noto Sans",
            0,
            "Caf\u00e9 No\u00ebl \u00c6sir \u00df \u20ac \u201cquotes\u201d".encode("cp1252"),
            "cp1252",
        ),
        (
            "cyrillic",
            "Noto Sans",
            204,
            "\u041f\u0440\u0438\u0432\u0435\u0442 \u043c\u0438\u0440! \u0401\u0436 \u2116 12".encode("cp1251"),
            "cp1251",
        ),
        ("default", "Noto Sans", 1, b"Caf\xe9 \x80", "cp1252"),
        ("bytes-western", ENCODING_FAMILY, 0, b"\xe9\x80\xc6 A B", "cp1252"),
        ("bytes-cyrillic", ENCODING_FAMILY, 204, b"\xe9\x80\xc6 A B", "cp1251"),
        ("missing", ENCODING_FAMILY, 0, b"ACB\x81\0\t", "cp1252"),
        ("symbols", SYMBOL_FAMILY, 2, b"AB \x80\xe9\xff", "symbol"),
        ("symbols-default", SYMBOL_FAMILY, 1, b"AB \x80\xe9\xff", "symbol"),
    )
    for name, family, charset, sample, encoding in profiles:
        recorder = Recorder()
        recorder.set_window_extent(*SIZE)
        recorder.set_viewport_extent(*SIZE)
        recorder.select_object(
            recorder.create_font(
                Font(height=-24, weight=400, quality=3, charset=charset, face_name=family.encode().ljust(32, b"\0"))
            )
        )
        recorder.set_background_mode(1)
        recorder.set_text_alignment(24)
        recorder.text_out(12, 40, sample)
        recorder.ext_text_out(12, 80, sample, advances=tuple(22 + i % 3 for i in range(len(sample))))
        recorder.set_text_alignment(25)
        recorder.move_to(12, 120)
        recorder.text_out(0, 0, sample)
        recorder.line_to(600, 120)
        yield f"encoding-{name}", family, sample, encoding, recorder


if __name__ == "__main__":
    for symbol, filename in ((False, "encoding.ttf"), (True, "symbols.ttf")):
        path = FONT_ROOT / filename
        path.write_bytes(font_bytes(symbol=symbol))
        print(path)
