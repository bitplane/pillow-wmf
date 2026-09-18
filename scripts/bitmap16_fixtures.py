"""Independent Bitmap16 wire fixtures; no DIB colour tables or DWORD rows."""

from itertools import product
from struct import pack

from pillow_wmf import Metafile, Recorder
from pillow_wmf.bitmap import RGBBitmap, encode_dib24
from pillow_wmf.wmf.objects import BitmapData, Palette


def source(depth, width=13, height=7, *, pattern=False, native=False, extra_stride=0):
    stride = ((width * depth + 15) // 16) * 2 + extra_stride
    bits = bytearray(stride * height)
    for y in range(height):
        for x in range(width):
            value = ((x * 0x193B + y * 0x2941) ^ (x << 19) ^ (y << 27)) & ((1 << depth) - 1)
            if depth < 8:
                bits[y * stride + x * depth // 8] |= value << (8 - depth - x * depth % 8)
            else:
                offset = y * stride + x * (depth // 8)
                bits[offset : offset + depth // 8] = value.to_bytes(depth // 8, "little")
    header = pack("<hhhhBB", 0, width, height, stride, 1, depth)
    reserved = bytes(26 if native else 22) if pattern else b""
    return BitmapData("pattern16" if pattern else "bitmap16", header + reserved + bits)


def cases():
    yield from self_copy_cases()
    for operation in ("bit_blt", "stretch_blt"):
        r = Recorder()
        r.select_object(r.create_brush(0, 0x713519, 0))
        for y, depth in enumerate((1, 4, 8, 16, 24, 32)):
            for x, rop in enumerate((0xF00021, 0x550009, 0x000042, 0x330008)):
                bitmap = source(depth)
                if operation == "bit_blt":
                    r.bit_blt(2 + 30 * x, 2 + 20 * y, 13, 7, 0, 0, rop, bitmap)
                else:
                    r.stretch_blt(2 + 30 * x, 2 + 20 * y, 26, 14, 0, 0, 13, 7, rop, bitmap)
        yield f"bitmap16-{operation}-embedded-depth-rop-atlas", r

    r = Recorder()
    indexed = BitmapData("pattern16", pack("<hhhhBB", 0, 16, 16, 16, 1, 8) + bytes(26) + bytes(range(256)))
    brush = r.create_pattern_brush(indexed)
    r.select_object(brush)
    r.pat_blt(0, 0, 32, 32, 0xF00021)
    r.select_palette(r.create_palette(Palette(entries=tuple((i, 31, 73, 0) for i in range(256)))))
    r.realize_palette()
    r.pat_blt(32, 0, 32, 32, 0xF00021)
    r.select_object(r.create_pattern_brush(indexed))
    r.pat_blt(64, 0, 32, 32, 0xF00021)
    yield "bitmap16-native-pattern-device-palette", r

    for depth in (4, 16, 24):
        r = Recorder()
        r.select_object(r.create_pattern_brush(source(depth, pattern=True, native=True)))
        r.select_object(r.create_pen(0, 1, 0x0000FF))
        r.rectangle(2, 2, 32, 32)
        r.pat_blt(40, 2, 30, 30, 0x550009)
        r.move_to(2, 40)
        r.line_to(32, 40)
        r.select_object(r.create_brush(0, 0x713519, 0))
        r.rectangle(2, 50, 32, 80)
        yield f"bitmap16-native-pattern-unrealizable-{depth}", r

    # Native PlayMetaFileRecord reads legacy brush bits at payload byte 36,
    # four bytes beyond the documented Pattern Object layout.
    for depth, extra_stride in (*product((1, 4, 8, 16, 24, 32), (0,)), (1, 4), (32, 4)):
        r = Recorder()
        r.set_text_color(0x713519)
        r.set_background_color(0xABCDEF)
        r.select_object(r.create_pattern_brush(source(depth, pattern=True, native=True, extra_stride=extra_stride)))
        r.pat_blt(2, 2, 54, 42, 0xF00021)
        r.set_text_color(0x371953)
        r.set_background_color(0xB7D3E1)
        r.pat_blt(64, 2, 54, 42, 0xF00021)
        r.set_rop2(7)
        r.select_object(r.create_pen(5, 0, 0))
        r.rectangle(2, 64, 118, 110)
        yield f"bitmap16-native-pattern-{depth}-stride{extra_stride}", r

    for operation, embedded in product(("bit_blt", "stretch_blt"), (False, True)):
        r = Recorder()
        r.select_object(r.create_brush(0, 0x713519, 0))
        bitmap = source(1) if embedded else None
        for i, rop in enumerate((0xF00021, 0x550009, 0xCC0020)):
            if operation == "bit_blt":
                r.bit_blt(2 + i * 40, 2, 13, 7, 0, 0, rop, bitmap)
            else:
                r.stretch_blt(2 + i * 40, 2, 26, 21, 0, 0, 13, 7, rop, bitmap)
        yield f"bitmap16-{operation}-rop-control-embedded{int(embedded)}", r

    for operation in ("bit_blt", "stretch_blt", "brush"):
        r = LegacyRecorder()
        r.set_text_color(0x713519)
        r.set_background_color(0xABCDEF)
        bitmap = source(1, pattern=operation == "brush")
        if operation == "brush":
            r.select_object(r.create_pattern_brush(bitmap))
            r.pat_blt(2, 2, 54, 42, 0xF00021)
        elif operation == "bit_blt":
            r.bit_blt(2, 2, 13, 7, 0, 0, 0xCC0020, bitmap)
        else:
            r.stretch_blt(2, 2, 52, 28, 0, 0, 13, 7, 0xCC0020, bitmap)
        yield f"bitmap16-version100-{operation}", r

    # Source-transfer rejection across depths and stretch modes is a unit
    # contract; the embedded depth/ROP atlases above retain its native oracle.
    for depth in (1, 4, 8, 16, 24, 32):
        r = Recorder()
        r.set_text_color(0x713519)
        r.set_background_color(0xABCDEF)
        r.select_object(r.create_pattern_brush(source(depth, pattern=True)))
        r.pat_blt(2, 2, 54, 42, 0xF00021)
        r.set_text_color(0x371953)
        r.set_background_color(0xB7D3E1)
        r.pat_blt(64, 2, 54, 42, 0xF00021)
        r.set_rop2(7)
        r.select_object(r.create_pen(5, 0, 0))
        r.rectangle(2, 64, 118, 110)
        yield f"bitmap16-{depth}-brush", r


def self_copy_cases():
    """Independent source/destination mapping, clipping and overlap holdouts."""
    seed = encode_dib24(
        RGBBitmap(
            128,
            128,
            bytes(
                c
                for y in range(128)
                for x in range(128)
                for c in ((x * 17 + y * 3) % 256, (y * 29 + x * 5) % 256, (x ^ y) * 2)
            ),
        )
    )
    profiles = (
        ("identity", 0, 64),
        ("fractional", 0, 96),
        ("negative", 0, -96),
        ("rtl", 1, 64),
        ("rtl-fractional", 1, 96),
    )
    for (profile, flags, extent), (operation, mode), scenario in product(
        profiles,
        (("bit_blt", 3), ("stretch_blt", 3), ("stretch_blt", 4)),
        ("overlap", "clip", "signed"),
    ):
        r = Recorder()
        r.dib_bit_blt(0, 0, 128, 128, 0, 0, 0xCC0020, seed)
        r.set_layout(flags)
        r.set_window_extent(64, 64)
        r.set_viewport_extent(extent, 80 if "fractional" in profile else 64)
        r.set_window_origin(3, 2)
        r.set_viewport_origin(110 if extent < 0 else 7, 5)
        r.set_stretch_mode(mode)
        r.select_object(r.create_brush(0, 0x713519, 0))
        if scenario == "clip":
            r.intersect_clip_rect(12, 8, 55, 65)
            r.exclude_clip_rect(23, 17, 29, 54)
        for index, rop in enumerate((0xCC0020, 0x660046)):
            y = 10 + index * 38
            sx, sy = (2, y - 5) if scenario == "clip" else (12, y)
            x, dy = 17, y + 3
            width, height = 24, 19
            if scenario == "signed":
                x, dy, width, height = 48, y + 23, -24, -19
            if operation == "bit_blt":
                r.bit_blt(x, dy, width, height, sx, sy, rop)
            else:
                r.stretch_blt(x, dy, width, height, sx, sy, 17, 13, rop)
        yield f"bitmap16-selfcopy-{profile}-{operation}-mode{mode}-{scenario}", r


class LegacyRecorder(Recorder):
    def to_bytes(self):
        return Metafile.build(self.records, version=0x0100).to_bytes()
