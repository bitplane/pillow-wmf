"""Small WMF experiments for font realization and text placement."""

from test_font import FAMILY

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font


def cases():
    profiles = (
        ("em-height", -20, 0, 0, 1, 1),
        ("cell-height", 20, 0, 0, 1, 1),
        ("explicit-width", -20, 12, 0, 1, 1),
        ("fractional", -20, 0, 0, 3, 2),
        ("rotated", -20, 0, 900, 1, 1),
    )
    for name, height, width, angle, window, viewport in profiles:
        recorder = Recorder()
        recorder.set_window_extent(128 * window, 128 * window)
        recorder.set_viewport_extent(128 * viewport, 128 * viewport)
        font = recorder.create_font(
            Font(
                height=height,
                width=width,
                escapement=angle,
                orientation=angle,
                weight=400,
                quality=3,
                face_name=FAMILY.encode().ljust(32, b"\0"),
            )
        )
        recorder.select_object(font)
        recorder.set_background_mode(1)
        recorder.set_text_alignment(24)  # left, baseline
        recorder.text_out(25, 30, b"A B")
        recorder.ext_text_out(25, 60, b"ABA", advances=(17, 9, 23))
        recorder.save_dc()
        recorder.set_text_alignment(25)  # left, baseline, update current position
        recorder.move_to(25, 90)
        recorder.ext_text_out(1, 1, b"AB", advances=(17, 9))
        recorder.line_to(100, 100)  # Makes text's state change visible.
        recorder.restore_dc(-1)
        recorder.set_background_color(0x00CCEE)
        recorder.ext_text_out(0, 0, b"", options=2, rectangle=(100, 4, 120, 12))
        yield name, recorder
