"""Text sample sheets for visual QA of glyph rendering with real fonts.

Text rasterization is not pixel-matched to Windows (see ``docs/emf.md``): the
glyphs are drawn by FreeType, so they are compared by eye instead. Each sheet
is an EMF of ordinary text in common Windows faces across sizes, qualities,
styles and transforms. ``probe-windows-text-samples.py`` plays the sheets
natively and ``text-samples-side-by-side.py`` renders the same bytes locally
next to the native images.
"""

import math
import struct

from pillow_wmf.emf import Metafile, fixed, text, variable
from pillow_wmf.emf.objects import LogFont
from pillow_wmf.mapping import REFERENCE_DEVICE

WIDTH = 720
FACES = ("Arial", "Times New Roman", "Courier New", "Verdana", "Georgia", "Trebuchet MS")
PANGRAM = "The quick brown fox jumps over the lazy dog 0123456789"
SCALES = (100 * 271 / 1024, 100 * 203 / 768)
GM_COMPATIBLE, GM_ADVANCED = 1, 2
TRANSPARENT, OPAQUE = 1, 2
BS_SOLID = 0


class Sheet:
    """Records with explicit object slots on a canvas of reference pixels."""

    def __init__(self, height):
        self.height = height
        self.records = [fixed.SetBkMode(TRANSPARENT), fixed.SetTextColor(0x000000)]
        self.slot = 0

    def add(self, *records):
        self.records.extend(records)

    def font(self, face, height, *, weight=400, italic=0, underline=0, strikeout=0, quality=0, escapement=0, charset=0):
        """Create, select and (after the caller's text) free a font."""
        self.slot += 1
        name = face.encode("utf-16-le").ljust(64, b"\0")
        logfont = LogFont(
            height=height,
            escapement=escapement,
            orientation=escapement,
            weight=weight,
            italic=italic,
            underline=underline,
            strikeout=strikeout,
            charset=charset,
            quality=quality,
            face_name=name,
        )
        extra = bytes(256) + struct.pack("<II", 0x08007664, 0)
        self.add(variable.ExtCreateFontIndirectW(self.slot, logfont, extra), fixed.SelectObject(self.slot))
        return self.slot

    def text(self, x, y, string, *, mode=GM_COMPATIBLE):
        data = string.encode("utf-16-le")
        start = 8 + 52 + 16
        blob = data + bytes(-len(data) % 4)
        self.add(
            text.ExtTextOutW((0, 0, -1, -1), mode, *SCALES, x, y, len(data) // 2, start, 0, (0, 0, -1, -1), 0, blob)
        )

    def line(self, face, height, x, y, string, *, mode=GM_COMPATIBLE, **style):
        """Draw one run in its own font, then free the font."""
        slot = self.font(face, height, **style)
        self.text(x, y, string, mode=mode)
        self.add(fixed.SelectObject(0x8000000D), fixed.DeleteObject(slot))  # SYSTEM_FONT

    def fill(self, rectangle, colour):
        self.slot += 1
        self.add(fixed.CreateBrushIndirect(self.slot, BS_SOLID, colour, 0), fixed.SelectObject(self.slot))
        self.add(fixed.SelectObject(0x80000008), fixed.Rectangle(*rectangle))  # NULL_PEN
        self.add(fixed.SelectObject(0x80000000), fixed.DeleteObject(self.slot))  # WHITE_BRUSH
        self.add(fixed.SelectObject(0x80000007))  # BLACK_PEN

    def metafile(self):
        (pixels_x, pixels_y), (mm_x, mm_y) = REFERENCE_DEVICE.pixels, REFERENCE_DEVICE.millimetres
        frame = (0, 0, round(WIDTH * mm_x * 100 / pixels_x), round(self.height * mm_y * 100 / pixels_y))
        return Metafile.build(self.records, frame=frame, bounds=(0, 0, WIDTH - 1, self.height - 1))


def sizes():
    """Each face at the common UI and document sizes, default quality."""
    sheet = Sheet(700)
    y = 6
    for face in FACES[:4]:
        for height in (-9, -11, -12, -13, -15, -16, -19, -24, -32):
            sheet.line(face, height, 6, y, f"{face} {-height}px: {PANGRAM}")
            y += -height + 4
        y += 4
    return sheet


def qualities():
    """Antialiasing qualities on light and dark grounds."""
    sheet = Sheet(560)
    names = {0: "default", 3: "non-antialiased", 4: "antialiased", 5: "ClearType"}
    y = 6
    for ground, ink in ((None, 0x000000), (0x402010, 0xFFFFFF), (0xD0F0FF, 0x0000A0)):
        top = y
        if ground is not None:
            sheet.fill((0, top - 3, WIDTH, top + 176), ground)
        sheet.add(fixed.SetTextColor(ink))
        for face in ("Arial", "Times New Roman"):
            for quality in (0, 3, 4, 5):
                for height in (-11, -15):
                    if height == -11:
                        x = 6
                    else:
                        x = 360
                    sheet.line(
                        face, height, x, y, f"{face} {-height}px {names[quality]}: quick brown fox", quality=quality
                    )
                y += 21
        y += 14
    sheet.add(fixed.SetTextColor(0x000000))
    return sheet


def styles():
    """Weights, slants and decorations, real and simulated."""
    sheet = Sheet(640)
    y = 6
    for face in ("Arial", "Times New Roman", "Courier New", "Georgia"):
        for label, style in (
            ("regular", {}),
            ("bold", {"weight": 700}),
            ("italic", {"italic": 1}),
            ("bold italic", {"weight": 700, "italic": 1}),
            ("underline + strikeout", {"underline": 1, "strikeout": 1}),
        ):
            sheet.line(face, -15, 6, y, f"{face} {label}: The quick brown fox 0123", **style)
            sheet.line(face, -11, 400, y + 2, f"{face} {label}: quick brown fox", **style)
            y += 19
        y += 8
    for weight in (100, 300, 400, 500, 600, 700, 800, 900):
        sheet.line("Arial", -16, 6, y, f"Arial weight {weight}: The quick brown fox", weight=weight)
        sheet.line("Verdana", -12, 400, y + 2, f"Verdana weight {weight}", weight=weight)
        y += 20
    return sheet


def rotations():
    """Escapement in compatible mode, then world transforms in advanced mode."""
    sheet = Sheet(540)
    sheet.add(fixed.SetTextAlign(0x18))  # TA_BASELINE
    for index, angle in enumerate((0, 150, 300, 450, 900, 1800, 2700, 3150)):
        x, y = 110 + 180 * (index % 4), 100 + 200 * (index // 4)
        # The second run sits one line below the first, along the rotated y axis.
        below = round(18 * math.sin(math.radians(angle / 10))), round(18 * math.cos(math.radians(angle / 10)))
        sheet.line("Arial", -15, x, y, f"Arial {angle / 10:g}°", escapement=angle)
        sheet.line(
            "Times New Roman",
            -11,
            x + below[0],
            y + below[1],
            f"Times {angle / 10:g}° italic",
            escapement=angle,
            italic=1,
        )
    for m11, m12, m21, m22, x, label in (
        (0.866, -0.5, 0.5, 0.866, 20, "rotate 30°"),
        (1.0, 0.0, -0.4, 1.0, 200, "shear"),
        (1.5, 0.0, 0.0, 0.8, 360, "stretch"),
        (-1.0, 0.0, 0.0, 1.0, 700, "mirror"),
    ):
        sheet.add(fixed.SaveDC(), fixed.SetWorldTransform(m11, m12, m21, m22, float(x), 460.0))
        sheet.line("Times New Roman", -16, 0, 0, f"Times {label}", mode=GM_ADVANCED)
        sheet.line("Arial", -12, 0, 26, f"Arial {label} italic", mode=GM_ADVANCED, italic=1)
        sheet.add(fixed.RestoreDC(-1))
    sheet.add(fixed.SetTextAlign(0))
    return sheet


def characters():
    """Accents, Greek, Cyrillic, punctuation and the symbol faces."""
    sheet = Sheet(360)
    y = 6
    for face in ("Arial", "Times New Roman", "Courier New"):
        sheet.line(face, -16, 6, y, f"{face}: àéîõü ÀÉÎÕÜ çñß ÆØÅ æøå œŒ € £ ¥ © ® ™ § ¶ † ‡ … – — ‘’ “”")
        sheet.line(face, -16, 6, y + 22, f"{face}: Ελληνικά αβγδε ΑΒΓΔΕ · Русский абвгд АБВГД")
        y += 52
    sheet.line("Symbol", -20, 6, y, "abgdepqrstuvwxyz ABGDEPQRST", charset=2)
    sheet.line("Wingdings", -20, 6, y + 30, "abcdefghijklmnopqrstuvwxyz 0123456789", charset=2)
    sheet.line("Webdings", -20, 6, y + 60, "abcdefghijklmnopqrstuvwxyz", charset=2)
    return sheet


SHEETS = {
    "sizes": sizes,
    "qualities": qualities,
    "styles": styles,
    "rotations": rotations,
    "characters": characters,
}


def sheet_bytes(name):
    """The sheet's EMF and its canvas size."""
    sheet = SHEETS[name]()
    return sheet.metafile().to_bytes(), (WIDTH, sheet.height)
