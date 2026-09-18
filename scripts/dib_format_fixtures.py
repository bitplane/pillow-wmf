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
    yield from rle_clip_cases()
    yield from conversion_cases()
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


def rle_clip_cases():
    """Separate encoded-pair phase from literal phase at odd clip boundaries."""
    colors = ((15, 31, 63), (223, 47, 79), (37, 211, 101))
    header = bytearray(encode_dib(12, 4, (0,) * 48, depth=4, colors=colors, rle=True).data[:52])
    encoded = bytes((12, 0x12, 0, 0, 0, 12, 0x12, 0x12, 0x12, 0x12, 0x12, 0x12, 0, 0)) * 2 + bytes((0, 1))
    pack_into("<I", header, 20, len(encoded))
    source = BitmapData("dib", bytes(header) + encoded)
    for operation in ("dib_bit_blt", "dib_stretch_blt", "stretch_dib", "set_dib_to_device"):
        recorder = Recorder()
        recorder.set_stretch_mode(3)
        for row, source_x in enumerate((0, 1, 2, 3)):
            for column, clipped in enumerate((False, True)):
                x, y = 8 + column * 32, 8 + row * 12
                recorder.save_dc()
                if clipped:
                    recorder.intersect_clip_rect(x + 1, y, x + 9, y + 4)
                if operation == "dib_bit_blt":
                    recorder.dib_bit_blt(x, y, 9, 4, source_x, 0, 0xCC0020, source)
                elif operation == "dib_stretch_blt":
                    recorder.dib_stretch_blt(x, y, 9, 4, source_x, 0, 9, 4, 0xCC0020, source)
                elif operation == "stretch_dib":
                    recorder.stretch_dib(x, y, 9, 4, source_x, 0, 9, 4, 0xCC0020, 0, source)
                else:
                    recorder.set_dib_to_device(x, y, 9, 4, source_x, 0, 0, 4, 0, source)
                recorder.restore_dc(-1)
        yield f"dib-rle4-clip-phase-{operation}", recorder


def conversion_cases():
    yield from fixup_holdouts()
    palettes = (
        ((0, 0, 0), (255, 255, 255)),
        ((255, 255, 255), (0, 0, 0)),
        ((19, 59, 97), (90, 96, 210)),
        ((0, 0, 0), (0, 0, 0)),
        ((255, 0, 0), (0, 255, 0)),
        ((11, 37, 83), (11, 37, 83)),
    )
    for pi, colors in enumerate(palettes):
        r = Recorder()
        for pattern, mode, size in product(range(4), (3, 4), (0, 1)):
            row = pattern * 2 + mode - 3
            source = encode_dib(
                13,
                7,
                tuple(
                    0 if pattern == 0 else 1 if pattern == 1 else (x + y) % 2 if pattern == 2 else int(x == y)
                    for y in range(7)
                    for x in range(13)
                ),
                depth=1,
                colors=colors,
            )
            r.set_stretch_mode(mode)
            dw, dh = (13, 7) if size == 0 else (23, 11)
            r.dib_stretch_blt(2 + size * 30, 2 + row * 15, dw, dh, 0, 0, 13, 7, 0xCC0020, source)
            r.stretch_dib(64 + size * 30, 2 + row * 15, dw, dh, 0, 0, 13, 7, 0xCC0020, 0, source)
        yield f"dib-format-mono-halftone-palette-{pi}", r

    # Select a coloured brush first: failed creations must preserve it, not
    # silently realize a white/null brush. Also covers the legacy style path.
    for style in (3, 5):
        r = Recorder()
        r.select_object(r.create_brush(0, 0x731951, 0))
        profiles = (
            (12, 4, None, False),
            (40, 4, None, True),
            (108, 16, (0xF800, 0x7E0, 31), False),
            (124, 32, (0xFF0000, 0xFF00, 255), False),
        )
        for i, (header, depth, masks, rle) in enumerate(profiles):
            source = encode_dib(
                3,
                2,
                (0, 1, 2, 3, 2, 1),
                depth=depth,
                colors=palettes[2] * 8 if depth == 4 else (),
                masks=masks,
                header_size=header,
                rle=rle,
            )
            r.select_object(r.create_dib_pattern_brush(style, 0, source))
            r.pat_blt(2 + i * 30, 2, 25, 25, 0xF00021)
        yield f"dib-format-rejected-brush-style-{style}", r

    for bits in (4, 5, 6, 10):
        depth = 16 if bits <= 5 else 32
        mask = (1 << bits) - 1
        masks = (mask << (2 * bits), mask << bits, mask)
        samples = tuple(i * (1 + (1 << bits) + (1 << (2 * bits))) for i in range(1 << bits))
        r = Recorder()
        for i in range(0, len(samples), 64):
            source = encode_dib(min(64, len(samples)), 1, samples[i : i + 64], depth=depth, masks=masks)
            for mode in (3, 4):
                r.set_stretch_mode(mode)
                r.dib_bit_blt(2 + (mode - 3) * 64, 2 + i // 64 * 4, min(64, len(samples)), 1, 0, 0, 0xCC0020, source)
        yield f"dib-format-channel-ramp-{bits}", r


def fixup_holdouts():
    # Identical RGB edges at different source depths distinguish format dispatch
    # from the shared scan filter. Larger images cross the colour-census gate.
    for size in (7, 49):
        r = Recorder()
        colors = ((19, 59, 97), (90, 96, 210))
        variants = product((1, 4, 8, 24), (0, 1)) if size == 7 else product((1, 4, 8, 24), (0,))
        for i, (depth, diagonal) in enumerate(variants):
            samples = tuple(int(x == y) if diagonal else (x + y) % 2 for y in range(size) for x in range(size))
            if depth == 24:
                samples = tuple(colors[v][0] << 16 | colors[v][1] << 8 | colors[v][2] for v in samples)
            source = encode_dib(size, size, samples, depth=depth, colors=colors if depth <= 8 else ())
            r.set_stretch_mode(4)
            r.dib_stretch_blt(
                i % 2 * 64,
                i // 2 * 30 if size == 7 else i // 2 * 64,
                size + 2,
                size + 2,
                0,
                0,
                size,
                size,
                0xCC0020,
                source,
            )
        yield f"dib-format-fixup-depths-{size}", r

    r = Recorder()
    palettes = (
        ((0, 0, 0), (255, 255, 255)),
        ((255, 255, 255), (0, 0, 0)),
        ((1, 1, 1), (254, 254, 254)),
        ((19, 59, 97), (90, 96, 210)),
    )
    for i, (colors, dc, operation, scale) in enumerate(
        product(
            palettes,
            ((0, 0xFFFFFF), (0xFFFFFF, 0), (0x371953, 0xB7D3E1)),
            ("dib_bit_blt", "dib_stretch_blt", "stretch_dib"),
            (1, 2),
        )
    ):
        r.save_dc()
        r.set_window_extent(1, 1)
        r.set_viewport_extent(scale, scale)
        r.set_viewport_origin(i % 8 * 15, i // 8 * 13)
        r.set_text_color(dc[0])
        r.set_background_color(dc[1])
        r.set_stretch_mode(4)
        source = encode_dib(3, 3, (0, 1, 0, 1, 0, 1, 0, 1, 0), depth=1, colors=colors)
        if operation == "dib_bit_blt":
            r.dib_bit_blt(0, 0, 3, 3, 0, 0, 0xCC0020, source)
        else:
            args = {"source": source} | ({"color_usage": 0} if operation == "stretch_dib" else {})
            getattr(r, operation)(0, 0, 3, 3, 0, 0, 3, 3, 0xCC0020, **args)
        r.restore_dc(-1)
    yield "dib-format-mono-copy-dispatch", r

    # Exhaust every binary 3x3 neighbourhood, including image boundaries.
    for reverse in (False, True):
        colors = ((0, 0, 0), (255, 255, 255))[:: -1 if reverse else 1]
        r = Recorder()
        r.set_stretch_mode(4)
        for value in range(512):
            source = encode_dib(3, 3, tuple((value >> i) & 1 for i in range(9)), depth=1, colors=colors)
            r.dib_bit_blt(value % 32 * 4, value // 32 * 4, 3, 3, 0, 0, 0xCC0020, source)
        yield f"dib-format-fixup-neighbourhoods-{int(reverse)}", r

    for top_down in (False, True):
        for operation in ("dib_stretch_blt", "stretch_dib"):
            r = Recorder()
            r.set_stretch_mode(4)
            source = encode_dib(
                11,
                9,
                tuple(((x * 317 + y * 157) ^ (x * y * 97)) >> 4 & 1 for y in range(9) for x in range(11)),
                depth=1,
                colors=((31, 17, 173), (71, 131, 29)),
                top_down=top_down,
            )
            args = {"source": source} | ({"color_usage": 0} if operation == "stretch_dib" else {})
            for i, (dw, dh, sx, sy, sw, sh) in enumerate(
                (
                    (11, 9, 0, 0, 11, 9),
                    (23, 19, 0, 0, 11, 9),
                    (7, 5, 0, 0, 11, 9),
                    (5, 3, 0, 0, 11, 9),
                    (29, 3, 0, 0, 11, 9),
                    (3, 27, 0, 0, 11, 9),
                    (23, 19, 2, 1, 7, 7),
                    (-23, 19, 2, 1, 7, 7),
                    (23, -19, 2, 1, 7, 7),
                    (23, 19, -2, -1, 11, 9),
                    (23, 19, 8, 6, 11, 9),
                    (1, 19, 0, 0, 1, 9),
                )
            ):
                x, y = i % 4 * 32 + 1, i // 4 * 40 + 1
                getattr(r, operation)(
                    x + (abs(dw) - 1 if dw < 0 else 0),
                    y + (abs(dh) - 1 if dh < 0 else 0),
                    dw,
                    dh,
                    sx,
                    sy,
                    sw,
                    sh,
                    0xCC0020,
                    **args,
                )
            yield f"dib-format-fixup-transfers-{operation}-{int(top_down)}", r
