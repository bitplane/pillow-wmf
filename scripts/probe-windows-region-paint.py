"""Native region paint/frame matrix, independent of committed PNG fixtures."""

import runpy
from itertools import product
from pathlib import Path

from windows_wmf_render import render_wmf

from pillow_wmf import Metafile, RasterContext, play
from pillow_wmf.wmf.objects import Scan

record_case = runpy.run_path(str(Path(__file__).with_name("generate-wmf-fixtures.py")))["region_paint_probe_case"]


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
        r = record_case(operation, style, mode, extent, size, scans, index)
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
