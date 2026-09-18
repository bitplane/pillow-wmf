"""Compact native checks for path validation and round-join traversal."""

from itertools import product

from pillow_wmf import Recorder


def cases():
    for fill_mode, style in ((1, 0), (2, 5)):
        r = Recorder()
        r.set_polygon_fill_mode(fill_mode)
        r.select_object(r.create_pen(style, 2, 0))
        r.select_object(r.create_brush(0, 0x39B571, 0))
        for index, (count, position) in enumerate(product(range(4), range(3))):
            x, y = 5 + index % 4 * 31, 5 + index // 4 * 40
            valid = ((x, y), (x + 12, y), (x + 12, y + 12), (x, y + 12))
            short = ((x + 17, y), (x + 24, y + 12), (x + 17, y + 12))[:count]
            polygons = (short, valid) if position == 0 else (valid, short) if position == 1 else (short,)
            r.poly_polygon(polygons)
            # A rejected call must not poison subsequent drawing or DC state.
            r.rectangle(x, y + 20, x + 8, y + 26)
        yield f"polypolygon-count-boundaries-{fill_mode}", r

    profiles = (
        ("fractional", 10, (1079, 996), (257, 193)),
        ("reflected", 10, (1079, 996), (-257, 193)),
        ("small-table", 8, (512, 512), (128, 128)),
        ("cubic", 28, (512, 512), (128, 128)),
    )
    for name, width, window, viewport in profiles:
        r = Recorder()
        r.set_window_extent(*window)
        r.set_viewport_extent(*viewport)
        r.select_object(r.create_pen(0, width, 0))
        for index, ((dx, dy), side, reverse) in enumerate(
            product(((1, 0), (-1, 0), (0, 1), (0, -1)), (-1, 0, 1), (False, True))
        ):
            r.set_viewport_origin(11 + index % 6 * 21, 15 + index // 6 * 31)
            points = ((-36 * dx, -36 * dy), (0, 0), (-12 * dx - side * 4 * dy, -12 * dy + side * 4 * dx))
            r.polyline(points[::-1] if reverse else points)
        yield f"stroke-reversal-seams-{name}", r
