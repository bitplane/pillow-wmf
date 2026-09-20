"""Documented printer escapes on an RGB memory device, with drawing sentinels."""

from io import BytesIO
from struct import pack

from PIL import Image

from pillow_wmf import Recorder


def escapes():
    # MS-WMF 2.3.6 specifies empty payloads for these records.
    for name, code in (
        ("newframe", 1),
        ("abortdoc", 2),
        ("nextband", 3),
        ("enddoc", 11),
        ("page-size", 12),
        ("printing-offset", 13),
        ("scaling", 14),
        ("device-units", 42),
        ("text-metrics", 256),
        ("kerning", 258),
        ("exttextout", 512),
        ("face-name", 513),
        ("download-face", 514),
        ("metafile-driver", 0x801),
        ("dib-support", 0xC01),
        ("begin-path", 0x1000),
        ("end-path", 0x1002),
        ("open-channel", 0x100E),
        ("download-header", 0x100F),
        ("close-channel", 0x1010),
    ):
        yield name, code, b""
    yield "startdoc", 10, b"pillow-wmf-probe\0"
    yield "set-color-table", 4, pack("<HI", 0, 0x0000FF)
    yield "get-color-table", 5, pack("<H", 0)
    yield "query-support", 8, pack("<H", 0x19)
    yield "copies", 17, pack("<H", 2)
    for name, code in (("cap", 21), ("join", 22)):
        for value in range(3):
            yield f"{name}-{value}", code, pack("<i", value)
    yield "miter", 23, pack("<i", 1)
    yield "pattern-rect", 25, pack("<4i2H", 15, 15, 60, 35, 0, 0)
    for name, code in (("eps-printing", 33), ("ignore-postscript", 38)):
        yield name, code, pack("<H", 1)
    for value in range(3):
        yield f"clip-path-{value}", 0x1001, pack("<2H", value, 0)
    data = b"% pillow-wmf probe\n"
    for name, code in (("passthrough", 19), ("postscript-data", 37), ("postscript-passthrough", 0x1013)):
        yield name, code, pack("<H", len(data)) + data
    yield "encapsulated-postscript", 0x1014, pack("<II6i", 32 + len(data), 2, 0, 0, 1024, 0, 0, 1024) + data
    yield "postscript-identify", 0x1015, pack("<I", 1)
    yield "postscript-injection", 0x1016, pack("<IHH", len(data), 1, 0) + data
    yield "postscript-feature", 0x1019, pack("<I", 0)
    yield "private-passthrough", 0x11D8, pack("<IH", 0, len(data)) + data
    for name, code in (("JPEG", 0x1017), ("PNG", 0x1018)):
        if name == "PNG":
            # Fixed encoded bytes: zlib versions choose different streams for
            # the same pixels, but generated WMFs must remain reproducible.
            yield (
                "check-png",
                code,
                bytes.fromhex(
                    "89504e470d0a1a0a0000000d4948445200000002000000020802000000fdd49a73"
                    "0000001049444154789c63fccf00024c609201000d1d010382c971ff"
                    "0000000049454e44ae426082"
                ),
            )
            continue
        stream = BytesIO()
        Image.new("RGB", (2, 2), "red").save(stream, format=name)
        yield f"check-{name.lower()}", code, stream.getvalue()


def drawing(records=()):
    dc = Recorder()
    dc.select_object(dc.create_pen(0, 7, 0xAA3300))
    dc.select_object(dc.create_brush(0, 0x55CCEE, 0))
    dc.rectangle(8, 8, 32, 32)
    dc.move_to(16, 70)
    dc.save_dc()
    for code, data in records:
        dc.escape(code, data)
    dc.line_to(98, 55)
    dc.polyline(((20, 105), (64, 44), (70, 105)))
    dc.rectangle(80, 12, 115, 38)
    dc.restore_dc(-1)
    dc.set_pixel(120, 120, 0x00FF00)
    return dc


def cases():
    yield "baseline", drawing()
    for name, code, data in escapes():
        yield name, drawing(((code, data),))
    yield "combined", drawing((code, data) for _, code, data in escapes())
