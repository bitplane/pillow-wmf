"""Compact controlled-font regressions for horizontal text layout."""

import runpy
from pathlib import Path

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font


def cases():
    # Keep the original native probe input unchanged when promoting it.
    namespace = runpy.run_path(str(Path(__file__).with_name("text_probe_cases.py")))
    yield "text-em-height", next(namespace["cases"]())[1]

    recorder = Recorder()
    recorder.select_object(
        recorder.create_font(Font(height=-12, weight=400, quality=3, face_name=b"Pillow WMF Test".ljust(32, b"\0")))
    )
    recorder.set_text_color(0xAA2200)
    recorder.set_background_color(0xAADDEE)
    for row, vertical in enumerate((0, 8, 24)):
        for column, horizontal in enumerate((0, 2, 6)):
            x, y = 18 + column * 43, 17 + row * 33
            recorder.save_dc()
            recorder.set_text_alignment(horizontal | vertical)
            recorder.intersect_clip_rect(x - 10, y - 10, x + 13, y + 11)
            recorder.ext_text_out(
                x,
                y,
                b"A B",
                options=(0, 4, 6)[column],
                rectangle=(x - 8, y - 8, x + 12, y + 8) if column else None,
                advances=(9, 3, 7),
            )
            recorder.restore_dc(-1)
    # ROP2 does not choose text's foreground composition; a clipped call must
    # not leave its ETO rectangle installed as the next operation's DC clip.
    recorder.set_rop2(7)
    recorder.set_text_alignment(24)
    recorder.set_background_mode(1)
    recorder.text_out(7, 122, b"ABA")
    recorder.set_background_color(0x22CC55)
    recorder.ext_text_out(0, 0, b"", options=2, rectangle=(110, 110, 123, 122))
    yield "text-layout-and-clip", recorder

    namespace = runpy.run_path(str(Path(__file__).with_name("text_layout_cases.py")))
    promoted = {
        "layout-cell21-PillowWMFTest": "text-cell-height",
        "layout-scaled-spacing-PillowWMFTest": "text-scaled-spacing",
    }
    for name, _, recorder in namespace["cases"]():
        if name in promoted:
            yield promoted[name], recorder

    for name, family, charsets, sample in (
        ("text-codepages", b"Pillow WMF Encoding", (0, 204), b"\xe9\x80\xc6 A B"),
        ("text-symbols", b"Pillow WMF Symbols", (1, 2), b"AB \x80\xe9\xff"),
    ):
        recorder = Recorder()
        recorder.set_background_mode(1)
        recorder.set_text_alignment(24)
        for row, charset in enumerate(charsets):
            recorder.select_object(
                recorder.create_font(
                    Font(height=-16, weight=400, quality=3, charset=charset, face_name=family.ljust(32, b"\0"))
                )
            )
            recorder.text_out(5, 20 + row * 60, sample)
            recorder.ext_text_out(5, 40 + row * 60, sample, advances=tuple(13 + i % 2 for i in range(len(sample))))
            recorder.set_text_justification(sample.count(b" "), 9)
            recorder.text_out(5, 58 + row * 60, sample)
            recorder.set_text_justification(0, 0)
        yield name, recorder

    recorder = Recorder()
    recorder.select_object(
        recorder.create_font(Font(height=-16, weight=400, quality=3, face_name=b"Pillow WMF Encoding".ljust(32, b"\0")))
    )
    recorder.set_background_mode(1)
    recorder.set_text_alignment(24)
    for row, control in enumerate((b"\t", b"\n", b"\r")):
        recorder.text_out(5, 18 + row * 40, b"A" + control + b"B")
        recorder.ext_text_out(5, 35 + row * 40, b"A" + control + b"B", advances=(17, 19, 23))
    yield "text-blank-controls", recorder
