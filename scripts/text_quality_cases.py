"""Compare font-matching quality hints independently of explicit monochrome."""

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (320, 100)
SAMPLE = b"A B A B"


def cases():
    for family in ("Pillow WMF Test", "Noto Sans"):
        for profile, height, width, angle in (
            ("small", -11, 0, 0),
            ("cell", 24, 0, 0),
            ("scaled-angle", -24, 15, -27),
        ):
            for quality in range(4):
                recorder = Recorder()
                recorder.set_window_extent(*SIZE)
                recorder.set_viewport_extent(*SIZE)
                recorder.set_background_mode(1)
                recorder.set_text_alignment(24)
                font = Font(
                    height=height,
                    width=width,
                    escapement=angle,
                    weight=400,
                    quality=quality,
                    face_name=family.encode().ljust(32, b"\0"),
                )
                recorder.select_object(recorder.create_font(font))
                recorder.text_out(12, 40, SAMPLE)
                recorder.ext_text_out(12, 80, SAMPLE, advances=(20,) * len(SAMPLE))
                yield f"quality-{family.replace(' ', '')}-{profile}-{quality}", family, recorder
