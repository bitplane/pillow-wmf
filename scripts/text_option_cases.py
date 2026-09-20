"""Isolate WMF text option, mapper and font-request semantics."""

from dataclasses import replace
from pathlib import Path
from struct import pack

from fontTools.ttLib import TTFont

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (192, 128)
FONT_PATH = Path(__file__).resolve().parents[1] / "test/fonts/layout.ttf"
FAMILY = "Pillow WMF Test"
REQUEST = Font(height=-24, weight=400, quality=3, face_name=FAMILY.encode().ljust(32, b"\0"))


def cases():
    variants = [("baseline", {}, {})]
    variants += [(f"option-{flag:04x}", {}, {"options": flag}) for flag in (0x10, 0x80, 0x400, 0x800, 0x2000)]
    variants += [(f"mapper-{flag}", {}, {"mapper": flag}) for flag in (1, 2, 3)]
    variants += [(f"quality-{quality}", {"quality": quality}, {}) for quality in (0, 4, 5, 6)]
    variants += [(f"precision-{precision}", {"out_precision": precision}, {}) for precision in (1, 3, 4, 7)]
    variants += [(f"clip-{flag}", {"clip_precision": flag}, {}) for flag in (0x10, 0x20, 0x40, 0x80)]
    variants += [("rtl-align", {}, {"alignment": 0x100}), ("rtl-layout", {}, {"layout": 1})]
    for name, changes, state in variants:
        dc = Recorder()
        dc.select_object(dc.create_font(replace(REQUEST, **changes)))
        dc.set_background_mode(1)
        dc.set_text_alignment(25 | state.get("alignment", 0))
        dc.set_mapper_flags(state.get("mapper", 0))
        dc.set_layout(state.get("layout", 0))
        dc.move_to(20, 40)
        options = state.get("options", 0)
        advances = (19, 7, 23, -5, 17, 11) if options & 0x2000 else (19, 23, 17)
        dc.ext_text_out(999, 999, b"ABA", options=options, advances=advances)
        dc.line_to(165, 65)
        dc.set_text_alignment(24)
        dc.text_out(20, 95, b"ABA")
        dc.set_pixel(180, 115, 255)
        yield name, dc


__all__ = ["FAMILY", "FONT_PATH", "SIZE", "cases"]


def rtl_cases():
    for name, alignment, options, changes, scale in (
        ("left", 25, 0, {}, (128, 128)),
        ("right", 27, 0, {}, (128, 128)),
        ("center", 31, 0, {}, (128, 128)),
        ("opaque", 25, 6, {}, (128, 128)),
        ("quarter", 25, 0, {"escapement": 900}, (128, 128)),
        ("angle", 25, 0, {"escapement": 300}, (128, 128)),
        ("fractional", 25, 0, {}, (192, 160)),
        ("pdy", 25, 0x2000, {}, (128, 128)),
    ):
        dc = Recorder()
        dc.select_object(dc.create_font(replace(REQUEST, **changes)))
        dc.set_layout(1)
        dc.set_window_extent(128, 128)
        dc.set_viewport_extent(*scale)
        dc.set_window_origin(-3, 2)
        dc.set_viewport_origin(7, 5)
        dc.set_background_mode(1)
        dc.set_background_color(0x99CCFF)
        dc.set_text_alignment(alignment)
        dc.move_to(45, 65)
        dc.ext_text_out(
            80,
            80,
            b"ABA",
            options=options,
            advances=(19, 7, 23, -5, 17, 11) if options & 0x2000 else (19, 23, 17),
            rectangle=(35, 40, 105, 90) if options & 6 else None,
        )
        dc.line_to(115, 100)
        dc.set_pixel(120, 120, 0x00FF00)
        yield f"rtl-{name}", dc


def placement_cases():
    """Distinguish byte decoding, glyph indexing and two-dimensional spacing."""
    with TTFont(FONT_PATH) as font:
        cmap = font.getBestCmap()
        indices = tuple(font.getGlyphID(cmap[ord(c)]) for c in "ABA")
    indexed = pack("<3H", *indices)
    variants = [
        ("glyph-natural", indexed, 0x10, (), {}, 25, 1),
        ("glyph-explicit", indexed, 0x10, (19, 23, 17, 31, 37, 41), {}, 25, 1),
        ("glyph-odd", indexed + b"Z", 0x10, (), {}, 25, 1),
        ("glyph-invalid", pack("<3H", 0, 0xFFFF, indices[0]), 0x10, (), {}, 25, 1),
    ]
    for name, changes, alignment, background in (
        ("baseline", {}, 25, 1),
        ("right", {}, 27, 1),
        ("center", {}, 30, 1),
        ("opaque", {}, 25, 2),
        ("quarter", {"escapement": 900}, 25, 1),
        ("angle", {"escapement": 300}, 25, 1),
        ("decorated", {"underline": 1, "strikeout": 1}, 25, 1),
        ("quarter-opaque", {"escapement": 900}, 25, 2),
        ("quarter-decorated", {"escapement": 900, "underline": 1, "strikeout": 1}, 25, 1),
        ("angle-opaque", {"escapement": 300}, 25, 2),
    ):
        variants.append((f"pdy-{name}", b"ABA", 0x2000, (19, 7, 23, -5, 17, 11), changes, alignment, background))
    variants.append(("glyph-pdy", indexed, 0x2010, (19, 7, 23, -5, 17, 11) * 2, {}, 25, 1))
    variants.extend(
        (f"pdy-{name}", b"ABA", 0x2000, spacing, {}, 25, 2)
        for name, spacing in (
            ("flat", (19, 0, 23, 0, 17, 0)),
            ("backwards", (-19, -7, -23, 5, -17, -11)),
            ("overlap", (3, 5, -7, -12, 0, 40)),
            ("no-spacing", ()),
        )
    )
    for name, text, options, advances, changes, alignment, background in variants:
        dc = Recorder()
        dc.select_object(dc.create_font(replace(REQUEST, **changes)))
        dc.set_background_mode(background)
        dc.set_background_color(0x99CCFF)
        dc.set_text_alignment(alignment)
        dc.move_to(80, 80)
        dc.ext_text_out(80, 80, text, options=options, advances=advances)
        dc.line_to(165, 100)
        dc.set_pixel(180, 115, 255)
        yield name, dc
