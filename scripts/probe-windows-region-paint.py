"""Native region paint/frame matrix, independent of committed PNG fixtures."""

from itertools import product

from windows_wmf_render import render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.wmf.objects import Region, Scan


def cases():
    shapes = (
        (Scan(3, 63, (5, 67)),),
        (Scan(3, 19, (5, 67)), Scan(19, 47, (5, 21, 43, 67)), Scan(47, 63, (5, 67))),
        (Scan(3, 11, (5, 67)), Scan(11, 29, (29, 35)), Scan(29, 63, (5, 67))),
        (Scan(3, 23, (5, 17, 19, 31, 33, 45)), Scan(23, 37, (5, 45)), Scan(37, 63, (15, 21))),
        (Scan(3, 63, (5, 5)),),
        (),
    )
    for index, (operation, style, mode, extent) in enumerate(
        product(
            ("fill_region", "paint_region", "invert_region", "frame_region"),
            (0, 1, 2),
            range(1, 17),
            ((128, 128), (64, 192), (-96, 144)),
        )
    ):
        yield (operation, style, mode, extent, (5, 7), shapes[index % len(shapes)], index)
    for index, (shape, extent, size) in enumerate(
        product(
            shapes,
            ((128, 128), (64, 64), (-64, 64), (64, -64), (96, 144), (-96, -144), (43, 77)),
            ((1, 1), (2, 3), (5, 7), (19, 23), (0, 4), (4, 0), (-5, 7), (5, -7), (-5, -7), (100, 100)),
        )
    ):
        yield ("frame_region", 0, 13, extent, size, shape, index)


def verify():
    failures = 0
    for count, (operation, style, mode, extent, size, scans, index) in enumerate(cases(), 1):
        r = Recorder()
        r.set_map_mode(8)
        r.set_window_extent(128, 128)
        r.set_viewport_extent(128, 128)
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, 0x0037598B, 0))
        r.rectangle(0, 0, 128, 128)
        brush = r.create_brush(style, 0x00A96C32, index % 6)
        other = r.create_brush(2, 0x002194EF, 4)
        r.select_object(other if operation in ("fill_region", "frame_region") else brush)
        # Allocate brushes before a possibly failed region: no accidental
        # object-slot reuse may obscure the paint operation being measured.
        region = r.create_region(Region((0, 0, 1, 1), scans))
        r.set_viewport_extent(*extent)
        r.set_window_origin(index % 5 - 2, index % 7 - 3)
        r.set_viewport_origin(96 if extent[0] < 0 else 7, 96 if extent[1] < 0 else 9)
        r.set_background_color(0x005DB742)
        r.set_background_mode(1 + index % 2)
        r.set_rop2(mode)
        if index % 3 == 0:
            r.exclude_clip_rect(17, 13, 29, 51)
        if operation in ("fill_region", "frame_region"):
            getattr(r, operation)(region, brush, *(size if operation == "frame_region" else ()))
        else:
            getattr(r, operation)(region)
        # A second operation observes that the first did not alter selected
        # brush, ROP2, background state or clip. Keep it outside the region
        # so it cannot cover up incorrect region painting.
        r.rectangle(75, 3, 90, 16)
        source = r.to_bytes()
        native = render_wmf(source, 128, 128)
        context = RasterContext(128, 128)
        play(Metafile.from_bytes(source), context, strict=True)
        differing = sum(
            a != b for a, b in zip(native.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            if failures <= 100:
                print("FAIL", count, operation, style, mode, extent, size, scans, index, differing, flush=True)
    print(f"Region painting: {count} native pixel cases, {failures} failures", flush=True)
    assert failures == 0


if __name__ == "__main__":
    verify()
