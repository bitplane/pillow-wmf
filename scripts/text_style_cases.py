"""Bounded text transform/style probes using supplied, verifiable fonts."""

from dataclasses import replace

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (640, 320)
SAMPLE = b"A B A B"
PROFILES = {
    "quarter-turn": {"escapement": 900},
    "oblique-angle": {"escapement": 300},
    "clockwise": {"escapement": -300},
    "orientation-only": {"orientation": 900},
    "reflect-x": {"mapping": (-1, 1)},
    "reflect-y": {"mapping": (1, -1)},
    "reflect-both": {"mapping": (-1, -1)},
    "reflect-angle": {"mapping": (-1, 1), "escapement": 300},
    "underline": {"underline": 1},
    "strikeout": {"strikeout": 1},
    "decorated-angle": {"underline": 1, "strikeout": 1, "escapement": 300},
    "synthetic-bold": {"weight": 700},
    "synthetic-italic": {"italic": 1},
    "synthetic-both": {"weight": 700, "italic": 1},
}


def cases():
    for name, settings in PROFILES.items():
        families = (
            ("Pillow WMF Test", "Noto Sans")
            if name
            in ("oblique-angle", "reflect-x", "underline", "synthetic-bold", "synthetic-italic", "synthetic-both")
            else ("Pillow WMF Test",)
        )
        for family in families:
            recorder = Recorder()
            sx, sy = settings.get("mapping", (1, 1))
            recorder.set_window_extent(*SIZE)
            recorder.set_viewport_extent(SIZE[0] * sx, SIZE[1] * sy)
            recorder.set_viewport_origin(240, 160)
            font = Font(height=-24, weight=400, quality=3, face_name=family.encode().ljust(32, b"\0"))
            recorder.select_object(
                recorder.create_font(
                    replace(font, **{key: value for key, value in settings.items() if key != "mapping"})
                )
            )
            recorder.set_background_color(0xDDEEFF)
            recorder.set_background_mode(2)
            recorder.set_text_alignment(24)
            recorder.text_out(0, 0, SAMPLE)
            recorder.ext_text_out(0, 50, SAMPLE, advances=(19, 10, 16, 10, 19, 10, 16))
            recorder.set_background_mode(1)
            recorder.set_text_alignment(25)
            recorder.move_to(0, -60)
            recorder.text_out(0, 0, SAMPLE)
            recorder.line_to(-100, -60)
            yield f"style-{name}-{family.replace(' ', '')}", family, recorder
