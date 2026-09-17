"""Asymmetric layout probes: points, edges, state and bitmap orientation."""

from pillow_wmf import Recorder
from pillow_wmf.bitmap import RGBBitmap, encode_dib24


def marks(r):
    r.select_object(r.create_pen(0, 1, 0x0000FF))
    r.select_object(r.create_brush(0, 0x317519, 0))
    r.set_pixel(0, 0, 0)
    r.set_pixel(5, 3, 0)
    r.move_to(4, 9)
    r.line_to(38, 16)
    r.rectangle(7, 22, 34, 39)
    r.polygon(((4, 48), (39, 44), (19, 68)))
    r.ellipse(5, 75, 40, 94)
    r.pat_blt(7, 104, 28, 12, 0xF00021)


def cases():
    for flags in (0, 1, 8, 9):
        r = Recorder()
        r.set_layout(flags)
        marks(r)
        yield f"layout-primitives-{flags}", r

        r = Recorder()
        r.set_layout(flags)
        r.intersect_clip_rect(8, 5, 39, 117)
        r.exclude_clip_rect(13, 26, 24, 32)
        r.offset_clip_region(3, 2)
        marks(r)
        r.set_layout(0)
        r.set_rop2(7)
        r.rectangle(0, 0, 128, 128)
        yield f"layout-clip-{flags}", r

        for op in ("dib_bit_blt", "dib_stretch_blt", "stretch_dib", "set_dib_to_device"):
            r = Recorder()
            r.set_layout(flags)
            dib = encode_dib24(
                RGBBitmap(5, 3, bytes(c for y in range(3) for x in range(5) for c in (x * 47, y * 89, 53)))
            )
            for i, width in enumerate((25, -25)):
                y = 8 + i * 40
                if op == "dib_bit_blt":
                    r.dib_bit_blt(35, y, 5 if width > 0 else -5, 3, 0, 0, 0xCC0020, dib)
                elif op == "dib_stretch_blt":
                    r.dib_stretch_blt(35, y, width, 21, 0, 0, 5, 3, 0xCC0020, dib)
                elif op == "stretch_dib":
                    r.stretch_dib(35, y, width, 21, 0, 0, 5, 3, 0xCC0020, 0, dib)
                else:
                    r.set_dib_to_device(35, y, 5, 3, 0, 0, 0, 3, 0, dib)
            yield f"layout-bitmap-{op}-{flags}", r

    for order in ("before", "after", "restore"):
        r = Recorder()
        r.set_map_mode(1)
        r.set_window_origin(3, -2)
        r.set_viewport_origin(7, 4)
        if order == "before":
            r.set_layout(1)
        r.set_window_extent(64, 128)
        r.set_viewport_extent(96, 128)
        if order != "before":
            r.set_layout(1)
        if order == "restore":
            r.save_dc()
            r.set_layout(0)
            r.set_map_mode(1)
            r.restore_dc(-1)
        marks(r)
        yield f"layout-mapping-{order}", r
