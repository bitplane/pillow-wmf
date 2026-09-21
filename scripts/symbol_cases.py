"""Symbol byte repertoire and charset selection through actual WMF records."""

from dataclasses import replace

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
            r.select_object(r.create_font(replace(font, height=height)))
            r.text_out(16, y, b"AaBbGgDpWw\xa5\xb1\xb9\xc5\xd5\xe5\xf2\xe6\xe7\xe8\xf6\xf7\xf8")
        yield f"symbol-charset{charset}-weight{weight}-italic{italic}", r

    # Unknown-family selection is charset-driven, not a spelling alias.
    # Include the damaged corpus name, an unrelated name, and generic hints.
    for index, (family, pitch) in enumerate(
        (
            (b"????????", 18),
            (b"Missing Symbol Family", 18),
            (b"", 0),
            (b"Missing Symbol Family", 34),
            (b"Missing Symbol Family", 49),
            (b"MT Extra", 18),
            (b"Symbol", 18),
        )
    ):
        r = Recorder()
        r.set_background_mode(1)
        for y, height in ((8, -16), (64, -48)):
            r.select_object(
                r.create_font(
                    Font(
                        height=height,
                        weight=400,
                        charset=2,
                        pitch_and_family=pitch,
                        face_name=family.ljust(32, b"\0"),
                    )
                )
            )
            r.text_out(16, y, b"\xc5")
        yield f"symbol-missing-family-{index}", r


def custom_selection_case():
    """Unlike Symbol, a private symbol face cannot satisfy an ANSI request."""
    recorder = Recorder()
    recorder.set_background_mode(1)
    recorder.set_text_alignment(24)
    for row, charset in enumerate((0, 1, 2)):
        recorder.select_object(
            recorder.create_font(
                Font(
                    height=-16, weight=400, quality=3, charset=charset, face_name=b"Pillow WMF Symbols".ljust(32, b"\0")
                )
            )
        )
        recorder.ext_text_out(5, 24 + row * 40, b"AB \x80\xe9\xff", advances=(15,) * 6)
    return recorder
