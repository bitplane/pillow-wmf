"""Small device-acceptance probes for extended DIB compression and profiles."""

from io import BytesIO
from struct import pack, pack_into

from PIL import Image, ImageCms

from pillow_wmf import Recorder
from pillow_wmf.bitmap import encode_dib
from pillow_wmf.wmf.objects import BitmapData

SIZE = (128, 128)


def bitmaps():
    samples = (0xFF0000, 0x00FF00, 0x0000FF, 0xFFFFFF, 0x000000, 0x00FFFF)
    yield "rgb", encode_dib(3, 2, samples, depth=24)
    image = Image.new("RGB", (3, 2))
    image.putdata([(v >> 16, (v >> 8) & 255, v & 255) for v in samples])
    for compression, kind in ((4, "JPEG"), (5, "PNG")):
        stream = BytesIO()
        image.save(stream, format=kind)
        data = stream.getvalue()
        yield (
            kind.lower(),
            BitmapData(
                "dib",
                pack("<IiiHHIIiiII", 40, 3, 2, 1, 0, compression, len(data), 0, 0, 0, 0) + data + bytes(len(data) % 2),
            ),
        )
    for compression, depth in ((11, 32), (12, 8), (13, 4)):
        data = bytearray(
            encode_dib(
                3,
                2,
                (0, 1, 2, 2, 1, 0),
                depth=depth,
                colors=((0, 0, 0), (255, 0, 0), (0, 255, 0)) if depth < 32 else (),
                rle=depth < 32,
            ).data
        )
        pack_into("I", data, 16, compression)
        yield f"cmyk-{depth}", BitmapData("dib", bytes(data))
    for name, color_space in (
        ("srgb", 0x73524742),
        ("calibrated", 0),
        ("embedded", 0x4D424544),
        ("linked", 0x4C494E4B),
    ):
        data = bytearray(encode_dib(3, 2, samples, depth=24, header_size=124).data)
        pack_into("I", data, 56, color_space)
        if name == "calibrated":
            # sRGB primaries, deliberately non-default gamma to expose ICM.
            pack_into(
                "9i",
                data,
                60,
                *(int(v * (1 << 30)) for v in (0.4124, 0.2126, 0.0193, 0.3576, 0.7152, 0.1192, 0.1805, 0.0722, 0.9505)),
            )
            pack_into("3I", data, 96, *(int(1.8 * 65536),) * 3)
        if name in ("embedded", "linked"):
            if name == "embedded":
                profile = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
                profile[24:36] = pack(">6H", 2020, 1, 1, 0, 0, 0)
            else:
                profile = b"pillow-wmf-nonexistent-profile.icm\0"
            pack_into("III", data, 108, 4, len(data), len(profile))
            data.extend(profile)
        yield name, BitmapData("dib", bytes(data) + bytes(len(data) % 2))


def cases():
    for name, bitmap in bitmaps():
        for operation in ("stretch", "bitblt", "dibstretchblt", "device", "brush"):
            dc = Recorder()
            dc.select_object(dc.create_brush(0, 0x0099CC, 0))
            dc.rectangle(0, 0, 128, 128)
            if operation == "stretch":
                dc.stretch_dib(12, 12, 90, 60, 0, 0, 3, 2, 0xCC0020, 0, bitmap)
            elif operation == "bitblt":
                dc.dib_bit_blt(12, 12, 3, 2, 0, 0, 0xCC0020, bitmap)
            elif operation == "dibstretchblt":
                dc.dib_stretch_blt(12, 12, 90, 60, 0, 0, 3, 2, 0xCC0020, bitmap)
            elif operation == "device":
                dc.set_dib_to_device(12, 12, 3, 2, 0, 0, 0, 2, 0, bitmap)
            else:
                handle = dc.create_dib_pattern_brush(5, 0, bitmap)
                dc.select_object(handle)
                dc.rectangle(12, 12, 102, 72)
                dc.delete_object(handle)
                dc.select_object(dc.create_brush(0, 0xCC00CC, 0))
                dc.rectangle(12, 85, 50, 105)
            dc.set_pixel(120, 120, 0x00FF00)
            yield f"{name}-{operation}", dc
