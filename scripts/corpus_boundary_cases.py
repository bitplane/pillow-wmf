"""Synthetic colour and state boundaries observed in external WMF corpora."""

from pillow_wmf import Recorder


def color_cases():
    r = Recorder()
    for flag in range(256):
        x, y = flag % 16 * 8, flag // 16 * 8
        color = flag << 24 | 0x563412
        brush = r.create_brush(0, color, 0)
        pen = r.create_pen(0, 1, color)
        r.select_object(brush)
        r.select_object(pen)
        r.rectangle(x, y, x + 4, y + 4)
        r.move_to(x, y + 5)
        r.line_to(x + 4, y + 5)
        r.set_pixel(x + 6, y + 6, color)
        r.delete_object(brush)
        r.delete_object(pen)
    yield "colorref-flags", r
