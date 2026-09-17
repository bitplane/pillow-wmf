"""DIB format probes: shared transfers, colour tables, masks, bands and brushes."""

from itertools import product
from struct import pack_into

from pillow_wmf import Recorder
from pillow_wmf.bitmap import encode_dib
from pillow_wmf.wmf.objects import BitmapData


def formats():
    for header, depth in product((12, 40, 108, 124), (1, 4, 8, 16, 24, 32)):
        if header != 12 or depth in (1, 4, 8, 24):
            yield f"h{header}-rgb{depth}", header, depth, None, False
    for header, (depth, masks) in product(
        (40, 108, 124),
        (
            (16, (0xF800, 0x07E0, 0x001F)),
            (16, (0x0F00, 0x00F0, 0x000F)),
            (32, (0xFF, 0xFF00, 0xFF0000)),
            (32, (0x3FF00000, 0x000FFC00, 0x3FF)),
        ),
    ):
        yield f"h{header}-masks{depth}-{masks[0]:x}", header, depth, masks, False
    for depth in (4, 8):
        yield f"h40-rle{depth}", 40, depth, None, True


def cases():
    for name, header, depth, masks, rle in formats():
        for top_down in (False,) if header == 12 or rle else (False, True):
            width, height = 13, 7  # Byte/nibble/word padding, asymmetry and crop edges.
            colors = (
                tuple(((i * 71 + 19) % 256, (i * 37 + 59) % 256, (i * 113 + 97) % 256) for i in range(1 << depth))
                if depth <= 8
                else ()
            )
            samples = tuple(
                ((x * 0x193B + y * 0x2941) ^ (x << 19) ^ (y << 27)) & ((1 << depth) - 1)
                for y in range(height)
                for x in range(width)
            )
            source = encode_dib(
                width,
                height,
                samples,
                depth=depth,
                colors=colors,
                masks=masks,
                header_size=header,
                top_down=top_down,
                rle=rle,
            )
            r = Recorder()
            r.set_map_mode(8)
            r.set_window_extent(128, 128)
            r.set_viewport_extent(128, 128)
            r.set_text_color(0x573119)
            r.set_background_color(0xABCDEF)
            for i, mode in enumerate((1, 2, 3, 4)):
                r.set_stretch_mode(mode)
                r.dib_stretch_blt(2 + i * 31, 2, 27, 19, 0, 0, width, height, 0xCC0020, source)
                r.stretch_dib(2 + i * 31, 24, 27, 19, 0, 0, width, height, 0x660046, 0, source)
            r.dib_bit_blt(3, 48, width, height, 0, 0, 0xCC0020, source)
            r.set_dib_to_device(23, 48, width, height, 0, 0, 0, height, 0, source)
            r.set_dib_to_device(43, 48, width, height, 0, 0, 1, 3, 0, source)
            r.select_object(r.create_dib_pattern_brush(5, 0, source))
            r.pat_blt(3, 66, 57, 25, 0xF00021)
            r.set_stretch_mode(3)
            r.dib_stretch_blt(98, 96, -35, 23, 1, 1, 11, 5, 0xCC0020, source)
            yield f"dib-format-{name}-{'top' if top_down else 'bottom'}", r

    # RLE absolute words, odd literal counts, delta gaps, short rows and EOB.
    for depth in (4, 8):
        colors = tuple((i * 13, 255 - i * 11, i * 7) for i in range(16))
        encoded = (
            bytes((3, 2, 0, 5, 1, 3, 5, 7, 9, 0, 0, 0, 0, 2, 2, 1, 4, 6, 0, 1))
            if depth == 8
            else bytes((3, 0x23, 0, 5, 0x13, 0x57, 0x90, 0, 0, 0, 0, 2, 2, 1, 4, 0x68, 0, 1))
        )
        data = bytearray(encode_dib(13, 7, (0,) * 91, depth=depth, colors=colors, rle=True).data[:104])
        pack_into("<I", data, 20, len(encoded))
        source = BitmapData("dib", bytes(data) + encoded)
        r = Recorder()
        r.select_object(r.create_brush(0, 0x675321, 0))
        r.pat_blt(0, 0, 128, 128, 0xF00021)
        r.set_stretch_mode(3)
        r.dib_stretch_blt(2, 2, 52, 28, 0, 0, 13, 7, 0xCC0020, source)
        r.stretch_dib(64, 2, 52, 28, 0, 0, 13, 7, 0xCC0020, 0, source)
        r.set_dib_to_device(2, 48, 13, 7, 0, 0, 0, 7, 0, source)
        yield f"dib-format-rle{depth}-commands", r
