"""Small visual review panels, not an exhaustive font-style matrix."""

from dataclasses import replace

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Font

SIZE = (480, 320)
SAMPLE = b'AEFS"\xfc'
FONT = Font(height=-40, weight=400, charset=2, quality=2, face_name=b"Wingdings".ljust(32, b"\0"))


def context():
    recorder = Recorder()
    recorder.set_window_extent(*SIZE)
    recorder.set_viewport_extent(*SIZE)
    recorder.set_background_mode(1)
    recorder.set_background_color(0xDDEEFF)
    recorder.set_text_alignment(24)
    return recorder


def select(recorder, **changes):
    recorder.select_object(recorder.create_font(replace(FONT, **changes)))


def cases():
    recorder = context()
    for height, y in zip((12, 24, 48, 72), (30, 85, 165, 275), strict=True):
        select(recorder, height=-height)
        recorder.text_out(20, y, SAMPLE)
    yield "sizes-12-24-48-72", recorder

    recorder = context()
    select(recorder)
    for x, y in ((-18, 40), (80, 130), (360, 230)):
        recorder.text_out(x, y, SAMPLE)
    yield "offsets-left-centre-right", recorder

    recorder = context()
    select(recorder, height=-56)
    recorder.ext_text_out(20, 85, SAMPLE, options=6, rectangle=(45, 50, 205, 95))
    recorder.intersect_clip_rect(60, 180, 230, 235)
    recorder.ext_text_out(20, 230, SAMPLE, options=6, rectangle=(35, 190, 280, 250))
    yield "clipping-ETO-then-intersected-DC", recorder

    for angle, origin in ((300, (50, 210)), (-300, (50, 100)), (900, (160, 280))):
        recorder = context()
        select(recorder, escapement=angle)
        recorder.text_out(*origin, SAMPLE)
        yield f"rotation-{angle}", recorder

    recorder = context()
    for y, weight, italic in ((45, 400, 0), (120, 700, 0), (195, 400, 1), (270, 700, 1)):
        select(recorder, weight=weight, italic=italic)
        recorder.text_out(20, y, SAMPLE)
    yield "styles-regular-bold-italic-bolditalic", recorder

    recorder = context()
    for y, underline, strikeout, angle in ((60, 1, 0, 0), (150, 0, 1, 0), (285, 1, 1, 150)):
        select(recorder, underline=underline, strikeout=strikeout, escapement=angle)
        recorder.text_out(20, y, SAMPLE)
    yield "decorations-underline-strikeout-rotated-both", recorder

    recorder = context()
    for y, height, width in ((60, 48, 0), (150, -48, 24), (250, -48, 60)):
        select(recorder, height=height, width=width)
        recorder.text_out(20, y, SAMPLE)
    yield "cell-height-48-narrow-24-wide-60", recorder

    recorder = context()
    recorder.set_viewport_extent(-SIZE[0], SIZE[1])
    recorder.set_viewport_origin(320, 0)
    select(recorder)
    recorder.text_out(0, 80, SAMPLE)
    recorder.ext_text_out(0, 220, SAMPLE, advances=(50, 30, 0, -20, 55, 45))
    yield "reflected-natural-and-signed-advances", recorder
