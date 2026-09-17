"""Independent Bitmap16 wire fixtures; no DIB colour tables or DWORD rows."""

from itertools import product
from struct import pack

from pillow_wmf import Metafile, Recorder
from pillow_wmf.wmf.objects import BitmapData


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

    for depth, operation in product((1, 4, 8, 16, 24, 32), ("bit_blt", "stretch_blt", "brush")):
        r = Recorder()
        r.set_text_color(0x713519)
        r.set_background_color(0xABCDEF)
        dib = source(depth, pattern=operation == "brush")
        if operation == "brush":
            r.select_object(r.create_pattern_brush(dib))
            r.pat_blt(2, 2, 54, 42, 0xF00021)
            r.set_text_color(0x371953)
            r.set_background_color(0xB7D3E1)
            r.pat_blt(64, 2, 54, 42, 0xF00021)
            r.set_rop2(7)
            r.select_object(r.create_pen(5, 0, 0))
            r.rectangle(2, 64, 118, 110)
        else:
            for i, mode in enumerate((1, 2, 3, 4)):
                r.set_stretch_mode(mode)
                if operation == "bit_blt":
                    r.bit_blt(2 + i * 30, 2, 13, 7, 0, 0, 0xCC0020, dib)
                    r.bit_blt(2 + i * 30, 18, 9, 5, 2, 1, 0x660046, dib)
                    r.save_dc()
                    r.set_window_extent(1, 1)
                    r.set_viewport_extent(2, 3)
                    r.bit_blt(1 + i * 15, 15, 13, 7, 0, 0, 0xCC0020, dib)
                    r.restore_dc(-1)
                else:
                    r.stretch_blt(2 + i * 30, 2, 27, 21, 0, 0, 13, 7, 0xCC0020, dib)
                    r.stretch_blt(2 + i * 30, 30, 9, 5, 0, 0, 13, 7, 0xCC0020, dib)
                    r.stretch_blt(28 + i * 30, 46, -27, 21, 2, 1, 9, 5, 0x660046, dib)
                    r.stretch_blt(2 + i * 30, 76, 27, 21, -2, -1, 13, 7, 0xCC0020, dib)
        yield f"bitmap16-{depth}-{operation}", r


class LegacyRecorder(Recorder):
    def to_bytes(self):
        return Metafile.build(self.records, version=0x0100).to_bytes()
