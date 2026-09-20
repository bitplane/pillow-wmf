"""Distinguish missing, subpixel and visible font decoration thicknesses."""

import runpy
from io import BytesIO
from pathlib import Path

from fontTools.ttLib import TTFont

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (160, 128)
THICKNESSES = (0, 1, 50)


def family_name(thickness):
    return f"WMF Decoration {thickness}"


def font_bytes(thickness):
    builder = runpy.run_path(str(Path(__file__).with_name("test_font.py")))
    with TTFont(BytesIO(builder["font_bytes"]()), recalcTimestamp=False) as font:
        for record in font["name"].names:
            if record.nameID in (1, 3, 4, 6):
                record.string = family_name(thickness)
        font["post"].underlinePosition = -100
        font["post"].underlineThickness = thickness
        font["OS/2"].yStrikeoutPosition = 250
        font["OS/2"].yStrikeoutSize = thickness
        data = BytesIO()
        font.save(data)
    return data.getvalue()


def cases():
    for thickness in THICKNESSES:
        family = family_name(thickness)
        for transform, angle, sx in (
            ("horizontal", 0, 1),
            ("oblique", 300, 1),
            ("quarter", 900, 1),
            ("reflected", 0, -1),
        ):
            for enabled in (False, True):
                recorder = Recorder()
                recorder.set_window_extent(*SIZE)
                recorder.set_viewport_extent(SIZE[0] * sx, SIZE[1])
                recorder.set_viewport_origin(80, 80)
                recorder.select_object(
                    recorder.create_font(
                        Font(
                            height=-24,
                            quality=3,
                            weight=400,
                            escapement=angle,
                            underline=int(enabled),
                            strikeout=int(enabled),
                            face_name=family.encode().ljust(32, b"\0"),
                        )
                    )
                )
                recorder.set_background_mode(1)
                recorder.set_text_alignment(24)
                recorder.text_out(0, 0, b"A B")
                suffix = "decorated" if enabled else "plain"
                yield f"decoration-{thickness}-{transform}-{suffix}", family, recorder
