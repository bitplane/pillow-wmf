"""Bounded MT Extra samples: corpus bytes, font selection, and equation pieces."""

from pillow_wmf import Font, Recorder

SIZE = (480, 400)
USED_BYTES = bytes.fromhex(
    "20 24 25 26 29 31 32 33 34 36 37 38 3A 3B 3D 3F 49 4B 4C 4D 4F 50 55 65 67 68 6C 6D 6F 70 72 74 75 76 A1 A5 B5 B6"
)


def cases():
    for charset, pitch in ((0, 80), (1, 16), (2, 16), (160, 16), (160, 80)):
        r = Recorder()
        r.set_background_mode(1)
        r.select_object(
            r.create_font(
                Font(
                    face_name=b"MT Extra".ljust(32, b"\0"),
                    height=-36,
                    weight=400,
                    charset=charset,
                    pitch_and_family=pitch,
                )
            )
        )
        for index, byte in enumerate(USED_BYTES):
            r.text_out(24 + index % 8 * 56, 20 + index // 8 * 68, bytes([byte]))
        yield f"mtextra-charset{charset}-family{pitch}", r
