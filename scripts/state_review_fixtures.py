"""Cross-state holdouts for failed objects, saved selection and RTL frames."""

from itertools import product

from pillow_wmf import Recorder
from pillow_wmf.bitmap import encode_dib
from pillow_wmf.bitmap16 import encode_bitmap16
from pillow_wmf.wmf.objects import Palette, Region, Scan


def cases():
    for operation, failure in product(("fill_region", "frame_region"), ("short-pattern", "core-dib")):
        r = Recorder()
        r.select_object(r.create_brush(0, 0x0000FF, 0))
        region = r.create_region(Region((8, 8, 112, 112), (Scan(8, 112, (8, 112)),)))
        if failure == "short-pattern":
            brush = r.create_pattern_brush(encode_bitmap16(1, 1, (1,), pattern=True))
        else:
            brush = r.create_dib_pattern_brush(
                5, 0, encode_dib(1, 1, (0,), depth=1, colors=((0, 0, 0), (255, 255, 255)), header_size=12)
            )
        getattr(r, operation)(region, brush, *((5, 7) if operation == "frame_region" else ()))
        r.paint_region(region)
        # The failed explicit operation must be visible outside this later mark.
        # XOR makes an earlier accidental fill survive the control operation.
        r.set_rop2(7)
        getattr(r, operation)(region, brush, *((5, 7) if operation == "frame_region" else ()))
        yield f"state-review-null-{operation}-{failure}", r

    for flags, extent, dimensions in product((0, 1, 9), (48, -48), ((5, 1), (5, 9))):
        r = Recorder()
        r.select_object(r.create_brush(0, 0x315719, 0))
        region = r.create_region(
            Region((8, 8, 100, 104), (Scan(8, 40, (8, 100)), Scan(40, 72, (8, 36, 68, 100)), Scan(72, 104, (8, 100))))
        )
        brush = r.create_brush(0, 0x0000FF, 0)
        r.set_layout(flags)
        r.set_window_extent(64, 64)
        r.set_viewport_extent(extent, 72)
        r.set_window_origin(3, 2)
        r.set_viewport_origin(100 if extent < 0 else 5, 1)
        r.frame_region(region, brush, *dimensions)
        yield f"state-review-frame-layout{flags}-scale{extent}-{dimensions[0]}x{dimensions[1]}", r

    for kind, saved in product(("brush", "pen", "palette"), (False, True)):
        r = Recorder()
        if kind == "palette":
            original = r.create_palette(Palette(entries=((255, 0, 0, 0),)))
            replacement = r.create_palette(Palette(entries=((0, 255, 0, 0),)))
            select = r.select_palette
            r.select_object(r.create_brush(0, 0x01000000, 0))
        else:
            if kind == "brush":
                original, replacement = (r.create_brush(0, color, 0) for color in (0x0000FF, 0x00FF00))
            else:
                original, replacement = (r.create_pen(0, 3, color) for color in (0x0000FF, 0x00FF00))
            select = r.select_object
        select(original)
        r.save_dc()
        if saved:
            select(replacement)
        r.delete_object(original)
        r.rectangle(8, 8, 40, 40)
        select(replacement)
        r.rectangle(48, 8, 80, 40)
        r.restore_dc(-1)
        r.rectangle(8, 56, 40, 88)
        # Reuse the released WMF slot without changing the retained selection.
        r.create_brush(0, 0xFF0000, 0)
        r.rectangle(48, 56, 80, 88)
        yield f"state-review-delete-{kind}-saved{int(saved)}", r
