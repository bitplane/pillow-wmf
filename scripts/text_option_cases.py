"""Isolate WMF text option, mapper and font-request semantics."""

from dataclasses import replace

from test_font import FAMILY, FONT_PATH

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (192, 128)
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
