"""Discriminating horizontal text realization/layout cases, not a font matrix."""

from dataclasses import replace

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (640, 240)
PROFILES = {
    "cell20": {"height": 20},
    "cell21": {"height": 21},
    "default-height": {"height": 0},
    "default-quality": {"quality": 0},
    "width7": {"width": 7},
    "width12": {"width": 12},
    "scale-up": {"scale": (3, 2, 3, 2)},
    "scale-down": {"scale": (2, 3, 2, 3)},
    "scale-wide": {"scale": (2, 1, 1, 1)},
    "scale-tall": {"scale": (1, 1, 2, 1)},
    "scaled-width": {"width": 7, "scale": (3, 2, 2, 3)},
    "extra": {"extra": 3},
    "negative-extra": {"extra": -4},
    "justify": {"justify": (3, 7)},
    "negative-justify": {"justify": (3, -7)},
    "scaled-spacing": {"extra": 2, "justify": (3, 7), "scale": (2, 3, 3, 2)},
    "signed-advances": {"advances": (13, 0, -7, 12, 0, 9, 6)},
    "cp-right": {"align": 27},
    "cp-center": {"align": 31},
}


def cases():
    for profile, settings in PROFILES.items():
        families = (
            ("Pillow WMF Test", "Noto Sans")
            if profile in ("cell20", "default-quality", "width7", "scale-up", "scaled-spacing")
            else ("Pillow WMF Test",)
        )
        for family in families:
            recorder = Recorder()
            vx, wx, vy, wy = settings.get("scale", (1, 1, 1, 1))
            recorder.set_window_extent(640 * wx, 240 * wy)
            recorder.set_viewport_extent(640 * vx, 240 * vy)
            font = Font(height=-20, weight=400, quality=3, face_name=family.encode().ljust(32, b"\0"))
            font = replace(font, **{key: settings[key] for key in ("height", "width", "quality") if key in settings})
            recorder.select_object(recorder.create_font(font))
            recorder.set_background_color(0xDDEEFF)
            recorder.set_background_mode(2)
            recorder.set_text_alignment(24)
            recorder.set_text_character_extra(settings.get("extra", 0))
            recorder.set_text_justification(*settings.get("justify", (0, 0)))
            recorder.text_out(30, 35, b"A B A B")
            recorder.ext_text_out(30, 70, b"A B A B", advances=settings.get("advances", (13, 7, 9, 7, 13, 7, 9)))
            recorder.set_text_alignment(settings.get("align", 25))
            recorder.move_to(150, 105)
            recorder.text_out(0, 0, b"A B A B")
            recorder.line_to(250, 105)
            yield f"layout-{profile}-{family.replace(' ', '')}", family, recorder
