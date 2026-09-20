"""Symbol byte repertoire and charset selection through actual WMF records."""

from pillow_wmf import Font, Recorder

SIZE = (640, 600)


def cases():
    for charset, weight, italic in ((0, 400, 0), (1, 400, 0), (2, 400, 0), (2, 700, 0), (2, 400, 1)):
        r = Recorder()
        r.set_window_extent(*SIZE)
        r.set_viewport_extent(*SIZE)
        r.set_background_mode(1)
        r.set_text_alignment(24)
        font = Font(
            height=-24, weight=weight, italic=italic, charset=charset, quality=3, face_name=b"Symbol".ljust(32, b"\0")
        )
        r.select_object(r.create_font(font))
        for row, start in enumerate(range(32, 256, 16)):
            r.ext_text_out(16, 32 + row * 36, bytes(range(start, start + 16)), advances=(36,) * 16)
        for y, height in ((530, -12), (580, -36)):
            from dataclasses import replace

            r.select_object(r.create_font(replace(font, height=height)))
            r.text_out(16, y, b"AaBbGgDpWw\xa5\xb1\xb9\xc5\xd5\xe5\xf2\xe6\xe7\xe8\xf6\xf7\xf8")
        yield f"symbol-charset{charset}-weight{weight}-italic{italic}", r
