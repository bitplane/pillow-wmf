"""Regenerate the small, deterministic WMF compatibility inputs."""

from itertools import product
from pathlib import Path

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Region, Scan

FIXTURES = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def cases():
    yield from pat_blt_cases()
    yield from flood_cases()
    yield from region_paint_cases()
    blank = Recorder()
    blank.set_map_mode(8)
    blank.set_window_extent(128, 128)
    blank.set_viewport_extent(128, 128)
    yield "blank", blank

    line = Recorder()
    line.set_map_mode(8)
    line.set_window_extent(128, 128)
    line.set_viewport_extent(128, 128)
    line.select_object(line.create_pen(0, 1, 0x000000FF))  # red COLORREF
    line.move_to(8, 8)
    line.line_to(120, 120)
    yield "line", line

    rectangle = Recorder()
    rectangle.set_map_mode(8)
    rectangle.set_window_extent(128, 128)
    rectangle.set_viewport_extent(128, 128)
    rectangle.select_object(rectangle.create_pen(0, 1, 0x00000000))
    rectangle.select_object(rectangle.create_brush(0, 0x0000AA00, 0))
    rectangle.rectangle(16, 24, 112, 96)
    yield "rectangle", rectangle

    overlap = Recorder()
    overlap.set_map_mode(8)
    overlap.set_window_extent(128, 128)
    overlap.set_viewport_extent(128, 128)
    overlap.select_object(overlap.create_pen(0, 1, 0x00000000))
    overlap.select_object(overlap.create_brush(0, 0x00CC0000, 0))
    overlap.rectangle(12, 12, 88, 88)
    overlap.select_object(overlap.create_brush(0, 0x000000CC, 0))
    overlap.ellipse(48, 40, 116, 108)
    yield "overlap", overlap

    yield from foundation_cases()
    yield from stroke_cases()
    yield from polygon_cases()
    yield from rop2_cases()
    yield from brush_cases()
    yield from styled_pen_cases()
    yield from arc_cases()
    yield from chord_cases()
    yield from chord_cases("pie")
    yield from pie_regression_cases()
    yield from round_rect_cases()
    yield from inside_frame_cases()
    yield from edge_cases()
    yield from region_clip_cases()


def region_clip_cases():
    ring = Region((8, 12, 112, 108), (Scan(12, 32, (8, 112)), Scan(32, 88, (8, 32, 88, 112)), Scan(88, 108, (8, 112))))
    recorder = mapped()
    handle = recorder.create_region(ring)
    recorder.select_object(handle)
    recorder.select_object(recorder.create_pen(5, 1, 0))
    recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
    recorder.rectangle(0, 0, 128, 128)
    yield "region-clip-slot-zero-object", recorder
    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 1, 0))
    handle = recorder.create_region(Region((0, 0, 0, 0), ()))
    recorder.intersect_clip_rect(32, 32, 64, 64)
    recorder.select_object(handle)
    recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
    recorder.rectangle(0, 0, 128, 128)
    yield "region-clip-null-object", recorder
    for name, region in (
        ("ring", ring),
        ("empty", Region((0, 0, 0, 0), ())),
        ("empty-scan", Region((8, 8, 8, 16), (Scan(8, 16, (8, 8)),))),
        ("negative", Region((-16, -8, 64, 64), (Scan(65528, 64, (65520, 64)),))),
        ("overlap", Region((8, 8, 96, 96), (Scan(8, 64, (8, 64)), Scan(32, 96, (32, 96))))),
        ("bounds", Region((0, 0, 1, 1), ring.scans)),
    ):
        for scale in (128, 192):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(5, 1, 0))
            recorder.set_viewport_extent(scale, scale)
            handle = recorder.create_region(region)
            recorder.select_clip_region(handle)
            recorder.delete_object(handle)
            recorder.set_viewport_extent(128, 128)
            recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
            recorder.rectangle(0, 0, 128, 128)
            yield f"region-clip-{name}-{scale}", recorder
    for operation in ("replace", "offset", "restore", "clear", "select-object", "intersect", "exclude"):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 1, 0))
        handle = recorder.create_region(ring)
        recorder.intersect_clip_rect(40, 40, 64, 64)
        recorder.select_clip_region(handle)
        if operation == "offset":
            recorder.set_viewport_extent(192, 64)
            recorder.offset_clip_region(7, -9)
            recorder.set_viewport_extent(128, 128)
        elif operation == "restore":
            recorder.save_dc()
            recorder.exclude_clip_rect(0, 0, 128, 128)
            recorder.restore_dc(-1)
        elif operation == "clear":
            recorder.select_clip_region(None)
        elif operation == "select-object":
            recorder.select_object(handle)
        elif operation == "intersect":
            recorder.intersect_clip_rect(20, 20, 100, 100)
        elif operation == "exclude":
            recorder.exclude_clip_rect(20, 20, 100, 100)
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        recorder.rectangle(0, 0, 128, 128)
        yield f"region-clip-{operation}", recorder


def inside_frame_cases():
    for operation in ("rectangle", "ellipse", "round_rect", "arc", "chord", "pie"):
        recorder = mapped()
        recorder.set_viewport_extent(192, 96)
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        for i, width in enumerate((1, 2, 3, 7, 20, 21)):
            x, y = 5 + i % 3 * 26, 6 + i // 3 * 64
            recorder.select_object(recorder.create_pen(6, width, 0x00402010))
            args = (x, y, x + 21, y + 37)
            if operation == "round_rect":
                args += (13, 19)
            elif operation in ("arc", "chord", "pie"):
                args += (x + 30, y + 10, x - 10, y + 28)
            getattr(recorder, operation)(*args)
        yield f"insideframe-{operation}-fractional", recorder
        recorder = mapped()
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        for i, (width, height) in enumerate(product((20, 21, 22), (21, 37))):
            x, y = 6 + i % 3 * 40, 12 + i // 3 * 64
            recorder.select_object(recorder.create_pen(6, width, 0x00402010))
            args = (x, y, x + 21, y + height)
            if operation == "round_rect":
                args += (13, 19)
            elif operation in ("arc", "chord", "pie"):
                args += (x + 30, y + 10, x - 10, y + 28)
            getattr(recorder, operation)(*args)
        yield f"insideframe-{operation}-collapse", recorder
        for brush in (0, 1):
            recorder = mapped()
            recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 0))
            for i, width in enumerate((0, 1, 2, 3, 4, 7, 20, 40)):
                x, y = 6 + i % 4 * 32, 12 + i // 4 * 64
                recorder.select_object(recorder.create_pen(6, width, 0x00402010))
                args = (x, y, x + 21, y + 37)
                if operation == "round_rect":
                    args += (13, 19)
                elif operation in ("arc", "chord", "pie"):
                    args += (x + 30, y + 10, x - 10, y + 28)
                getattr(recorder, operation)(*args)
            yield f"insideframe-{operation}-brush-{brush}", recorder
    for sx, sy in ((2, 1), (1, 2), (-1, 1), (2, 2)):
        recorder = mapped()
        recorder.set_viewport_origin(128 if sx < 0 else 0, 0)
        recorder.set_viewport_extent(128 * sx, 128 * sy)
        recorder.select_object(recorder.create_pen(6, 7, 0x00402010))
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        recorder.ellipse(8, 8, 56, 56)
        recorder.rectangle(8, 64, 56, 112)
        yield f"insideframe-mapping-{sx}-{sy}", recorder
    recorder = mapped()
    recorder.select_object(recorder.create_pen(6, 7, 0x00402010))
    recorder.polyline(((8, 8), (112, 32), (8, 56)))
    recorder.polygon(((8, 72), (112, 80), (48, 112)))
    yield "insideframe-unbounded", recorder


def round_rect_cases():
    for name, style, width, brush, mode in (
        ("solid", 0, 1, 0, 13),
        ("wide", 0, 7, 0, 13),
        ("outline", 0, 7, 1, 13),
        ("fill-only", 5, 1, 0, 13),
        ("styled", 4, 1, 0, 13),
        ("hatch", 0, 1, 2, 13),
        ("xor", 0, 1, 0, 7),
        ("xor-wide", 0, 7, 0, 7),
    ):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(style, width, 0x00402010))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 5))
        recorder.set_rop2(mode)
        for i, size in enumerate(
            (
                (0, 0),
                (0, 12),
                (12, 0),
                (1, 1),
                (2, 2),
                (3, 5),
                (8, 14),
                (15, 9),
                (20, 20),
                (21, 21),
                (22, 22),
                (23, 23),
                (60, 60),
                (-8, 14),
                (8, -14),
                (-8, -14),
            )
        ):
            x, y = 6 + i % 4 * 32, 6 + i // 4 * 32
            recorder.round_rect(x, y, x + 21, y + 22, *size)
        yield f"roundrect-corners-{name}", recorder
    for sx, sy in ((-1, 1), (1, -1), (-1, -1), (2, 1)):
        recorder = mapped()
        recorder.set_viewport_origin(128 if sx < 0 else 0, 128 if sy < 0 else 0)
        recorder.set_viewport_extent(128 * sx, 128 * sy)
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        recorder.move_to(4, 4)
        recorder.round_rect(8, 8, 56, 104, 17, 29)
        recorder.line_to(30, 12)
        yield f"roundrect-mapping-{sx}-{sy}", recorder


def pie_regression_cases():
    # Holdout failures retained as local, independently rendered regressions.
    for name, box, start, end, width, brush, rop in (
        ("xor-fill-stroke", (9, 17, 117, 108), (90, 27), (23, 103), 1, 0, 7),
        ("xor-wide", (24, 8, 103, 121), (90, 27), (23, 103), 7, 0, 7),
        ("wide-full", (9, 17, 117, 108), (97, 63), (97, 63), 7, 1, 13),
        ("wide-collapsed", (61, 8, 62, 120), (123, 63), (64, 2), 7, 1, 13),
    ):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, width, 0x00402010))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 5))
        recorder.set_rop2(rop)
        recorder.pie(*box, *start, *end)
        yield f"pie-{name}", recorder


def chord_cases(operation="chord"):
    # Independent Windows images exercise closure as well as curved coverage.
    directions = ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))
    for name, style, width, brush, background in (
        ("solid", 0, 1, 0, 2),
        ("wide", 0, 7, 0, 2),
        ("fill-only", 5, 1, 0, 2),
        ("outline", 0, 7, 1, 2),
        ("dashed", 1, 1, 0, 2),
        ("hatch-transparent", 0, 1, 2, 1),
    ):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(style, width, 0))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 4))
        recorder.set_background_mode(background)
        for index in range(16):
            cx, cy = 16 + index % 4 * 32, 16 + index // 4 * 32
            sx, sy = directions[index % 8]
            ex, ey = directions[(index + (1 if index < 8 else 5)) % 8]
            getattr(recorder, operation)(
                cx - 11, cy - 10, cx + 12, cy + 11, cx + sx * 20, cy + sy * 20, cx + ex * 20, cy + ey * 20
            )
        yield f"{operation}-sweeps-{name}", recorder
    for name, box, start, end in (
        ("equal", (8, 16, 120, 112), (120, 64), (120, 64)),
        ("same-ray", (8, 16, 120, 112), (120, 64), (176, 64)),
        ("tiny", (8, 16, 120, 112), (62, 16364), (62, 16365)),
        ("narrow", (60, 8, 63, 120), (100, 30), (20, 80)),
        ("flat", (8, 60, 120, 63), (100, 30), (20, 80)),
        ("reversed", (120, 112, 8, 16), (117, 43), (31, 107)),
    ):
        recorder = mapped()
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        getattr(recorder, operation)(*box, *start, *end)
        yield f"{operation}-edge-{name}", recorder
    for sx, sy in ((-1, 1), (1, -1), (-1, -1), (2, 1)):
        recorder = mapped()
        recorder.set_viewport_origin(128 if sx < 0 else 0, 128 if sy < 0 else 0)
        recorder.set_viewport_extent(128 * sx, 128 * sy)
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        recorder.move_to(4, 4)
        getattr(recorder, operation)(8, 8, 56, 104, 56, 40, 17, 93)
        recorder.line_to(30, 12)  # Neither operation changes the current position.
        yield f"{operation}-mapping-{sx}-{sy}", recorder


def edge_cases():
    for style in (1, 4):
        recorder = mapped()
        recorder.set_background_mode(1)
        recorder.select_object(recorder.create_pen(style, 1, 0))
        recorder.polyline(((0, -80), (40, -40), (120, 40), (160, 80), (80, 160), (40, 80)))
        yield f"pen-style-{style}-minor-axis-clipping", recorder
    for width in (3, 7):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, width, 0))
        for index in range(16):
            cx, cy = 16 + index % 4 * 32, 16 + index // 4 * 32
            distance = (3, 31, 16300, 16300)[index % 4]
            offset = index // 4 - 2
            recorder.arc(cx - 10, cy - 10, cx + 10, cy + 10, cx + distance, cy + offset, cx + distance, cy + offset + 1)
        yield f"arc-shallow-width-{width}", recorder
    # These exact radials expose native control-point and angle-precision
    # differences; small atlas cells can hide them after quantization.
    for name, start, end in (
        ("wrapping-axis", (67, 63), (67, 64)),
        ("short-controls", (61, 65), (61, 66)),
        ("cardinal-controls", (61, 64), (61, 65)),
        ("far-coincident-angles", (62, -16236), (62, -16235)),
    ):
        for width in (1, 7):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, width, 0))
            recorder.arc(8, 8, 120, 120, *start, *end)
            yield f"arc-edge-{name}-width-{width}", recorder
    for width, delta in ((7, (-16, 39)), (8, (-19, 45))):
        for direction in (-1, 1):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, width, 0))
            recorder.move_to(64, 64)
            recorder.line_to(64 + direction * delta[0], 64 + direction * delta[1])
            yield f"pen-support-tie-width-{width}-direction-{direction}", recorder


def mapped():
    recorder = Recorder()
    recorder.set_map_mode(8)
    recorder.set_window_extent(128, 128)
    recorder.set_viewport_extent(128, 128)
    return recorder


def arc_cases():
    # Identical radial rays at two distances: axis tips, diagonals, all octants,
    # short/wrapping sweeps, and circular/elliptical bounds. Each pair must
    # produce identical native pixels regardless of distance from the center.
    directions = ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))
    for width in (1, 3, 6):
        for distance in (1, 11):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, width, 0))
            for index in range(16):
                left, top = 6 + index % 4 * 32, 6 + index // 4 * 32
                right, bottom = left + 20, top + (20 if index < 8 else 22)
                cx, cy = (left + right) // 2, (top + bottom) // 2
                start = directions[index % 8]
                end = directions[(index + (1 if index < 8 else 5)) % 8]
                recorder.arc(
                    left,
                    top,
                    right,
                    bottom,
                    cx + distance * start[0],
                    cy + distance * start[1],
                    cx + distance * end[0],
                    cy + distance * end[1],
                )
            yield f"arc-boundaries-width-{width}-distance-{distance}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 1, 0x000000CC))
    recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
    # Four distinct quarter sweeps; the brush must not affect Arc.
    for left, top, start, end in (
        (8, 8, (47, 27), (27, 8)),
        (68, 8, (87, 8), (68, 27)),
        (8, 68, (8, 87), (27, 106)),
        (68, 68, (87, 106), (106, 87)),
    ):
        recorder.arc(left, top, left + 39, top + 39, *start, *end)
    yield "arc-quarters", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 1, 0))
    for left, top, right, bottom, start, end in (
        (8, 8, 59, 43, (54, 13), (12, 38)),
        (69, 8, 120, 43, (74, 38), (115, 13)),
        (8, 67, 55, 119, (55, 93), (31, 67)),
        (69, 67, 120, 119, (95, 119), (69, 93)),
    ):
        recorder.arc(left, top, right, bottom, *start, *end)
    yield "arc-oblique", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 1, 0))
    recorder.arc(8, 8, 58, 58, 58, 33, 58, 33)  # Equal directions: full ellipse.
    recorder.arc(68, 8, 118, 58, 168, 33, 93, -92)  # Radials need not end on the ellipse.
    recorder.move_to(8, 82)
    recorder.arc(8, 68, 58, 118, 58, 93, 33, 68)
    recorder.line_to(58, 118)  # Arc must leave the current position unchanged.
    yield "arc-radials-and-position", recorder

    recorder = mapped()
    for style, width, box in (
        (0, 0, (8, 8, 56, 56)),
        (0, 3, (68, 8, 116, 56)),
        (1, 1, (8, 68, 56, 116)),
        (3, 1, (68, 68, 116, 116)),
    ):
        recorder.select_object(recorder.create_pen(style, width, 0))
        left, top, right, bottom = box
        recorder.arc(left, top, right, bottom, right + 20, (top + bottom) // 2, left, top)
    yield "arc-pen-styles", recorder

    for name, viewport, origin in (
        ("reflect-x", (-128, 128), (64, 8)),
        ("reflect-y", (128, -128), (8, 64)),
        ("reflect-both", (-128, -128), (64, 64)),
    ):
        recorder = mapped()
        recorder.set_viewport_extent(*viewport)
        recorder.set_viewport_origin(*origin)
        recorder.select_object(recorder.create_pen(0, 1, 0))
        recorder.arc(8, 8, 56, 56, 56, 32, 32, 8)
        yield f"arc-{name}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 3, 0))
    # The native flattened path of the wide Arc above, as an ordinary path.
    recorder.polyline(((115, 32), (113, 22), (108, 15), (101, 10), (92, 8), (83, 10), (75, 15)))
    yield "arc-wide-polyline-control", recorder


def markers(recorder):
    """Asymmetric logical points; no pen, brush or curve realization involved."""
    for x, y, color in ((0, 0, 0), (7, 11, 0x0000CC), (21, 5, 0x00AA00), (35, 27, 0xCC0000)):
        recorder.set_pixel(x, y, color)


def filled_box(recorder, bounds=(8, 12, 40, 36), color=0x00AA00):
    recorder.select_object(recorder.create_pen(5, 0, 0))  # PS_NULL: isolate fill geometry
    recorder.select_object(recorder.create_brush(0, color, 0))
    recorder.rectangle(*bounds)


def foundation_cases():
    # These two deliberately inherit the runner's anisotropic 128:128 setup.
    recorder = Recorder()
    markers(recorder)
    yield "coords-inherited", recorder
    recorder = Recorder()
    recorder.set_window_extent(64, 64)
    markers(recorder)
    yield "coords-inherited-extent", recorder

    for name, window, viewport in (
        ("identity", (128, 128), (128, 128)),
        ("double", (64, 64), (128, 128)),
        ("half", (256, 256), (128, 128)),
        ("two-thirds", (192, 192), (128, 128)),
        ("independent", (64, 256), (128, 128)),
        ("reflect-x", (128, 128), (-128, 128)),
        ("reflect-y", (128, 128), (128, -128)),
        ("reflect-both", (-128, -128), (128, 128)),
    ):
        recorder = mapped()
        recorder.set_window_extent(*window)
        recorder.set_viewport_extent(*viewport)
        recorder.set_viewport_origin(96 if "reflect" in name else 8, 96 if "reflect" in name else 8)
        # Reflection cases need room on either side of the chosen origin.
        if name == "reflect-x":
            recorder.set_viewport_origin(96, 8)
        elif name == "reflect-y":
            recorder.set_viewport_origin(8, 96)
        markers(recorder)
        filled_box(recorder)
        yield f"coords-{name}", recorder

    for translated in (False, True):
        recorder = mapped()
        recorder.set_window_extent(2, 2)
        recorder.set_viewport_extent(1, 1)
        recorder.set_viewport_origin(63 if translated else 64, 64)
        for x in range(-15, 16):
            # Distinct rows prevent adjacent half-tie samples overwriting each other.
            recorder.set_pixel(x, 4 * x, 0x0000CC if x < 0 else 0xCC0000)
        yield f"coords-half-ties{'-translated' if translated else ''}", recorder

    recorder = mapped()
    recorder.set_window_origin(-11, 7)
    recorder.set_viewport_origin(16, 32)
    markers(recorder)
    recorder.offset_window_origin(5, -9)
    recorder.offset_viewport_origin(32, 8)
    markers(recorder)
    yield "coords-origins-offsets", recorder

    for mode, name, step in (
        (1, "text", 24),
        (2, "lometric", 60),
        (3, "himetric", 600),
        (4, "loenglish", 24),
        (5, "hienglish", 240),
        (6, "twips", 360),
        (7, "isotropic", 60),
        (8, "anisotropic", 24),
    ):
        recorder = mapped()
        recorder.set_map_mode(mode)
        recorder.set_viewport_origin(16, 96)
        direction = 1 if mode in (1, 8) else -1
        recorder.set_pixel(step, -direction * step, 0x0000CC)
        filled_box(recorder, (0, -step, step, 0))
        yield f"coords-mode-{name}", recorder

    for mode in (1, 6):
        recorder = mapped()
        recorder.set_map_mode(mode)
        recorder.set_viewport_origin(16, 80)
        recorder.set_window_extent(0, 0)  # Ignored, even though invalid in arbitrary modes.
        recorder.set_viewport_extent(7, 13)
        recorder.scale_window_extent(2, 3, 3, 2)
        recorder.scale_viewport_extent(3, 2, 2, 3)
        filled_box(recorder, (0, -30, 30, 0) if mode == 1 else (0, -450, 450, 0))
        yield f"coords-fixed-ignores-extents-{mode}", recorder

    for reverse in (False, True):
        recorder = mapped()
        recorder.set_map_mode(7)
        recorder.set_viewport_origin(8, 8)
        setters = [(recorder.set_window_extent, (100, 50)), (recorder.set_viewport_extent, (100, 100))]
        for setter, values in reversed(setters) if reverse else setters:
            setter(*values)
        filled_box(recorder)
        yield f"coords-isotropic-order-{'viewport-first' if reverse else 'window-first'}", recorder

    recorder = mapped()
    recorder.set_viewport_origin(8, 8)
    recorder.set_window_extent(17, 19)
    recorder.set_viewport_extent(40, 40)
    recorder.scale_window_extent(2, 3, 3, 2)
    recorder.scale_viewport_extent(3, 2, 2, 3)
    markers(recorder)
    yield "coords-scale-extents", recorder

    recorder = mapped()
    recorder.set_viewport_origin(8, 8)
    recorder.set_window_extent(64, 64)
    recorder.set_map_mode(8)  # Reselecting must not reset custom extents.
    markers(recorder)
    recorder.set_map_mode(1)
    recorder.offset_viewport_origin(0, 64)
    markers(recorder)
    yield "coords-mode-switch", recorder

    # Width is logical. Zero is the separately specified device-pixel hairline.
    for width in (0, 1, 3):
        for name, viewport in (("identity", (128, 128)), ("scale-x", (256, 128)), ("scale-y", (128, 256))):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, width, 0))
            recorder.set_viewport_extent(*viewport)  # Change mapping AFTER selection.
            recorder.move_to(8, 8)
            recorder.line_to(48, 8)
            recorder.line_to(48, 48)
            recorder.move_to(8, 16)
            recorder.line_to(40, 40)
            yield f"pen-width-{width}-{name}", recorder

    recorder = mapped()
    filled_box(recorder)
    yield "pen-null-fill", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 0, 0))
    for dx, dy in (
        (24, 0),
        (24, 12),
        (24, 24),
        (12, 24),
        (0, 24),
        (-12, 24),
        (-24, 24),
        (-24, 12),
        (-24, 0),
        (-24, -12),
        (-24, -24),
        (-12, -24),
        (0, -24),
        (12, -24),
        (24, -24),
        (24, -12),
    ):
        recorder.move_to(64, 64)
        recorder.line_to(64 + dx, 64 + dy)
    yield "drawing-lines-octants", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 0, 0))
    for x, y, end_x, end_y in ((8, 16, 32, 16), (48, 40, 48, 16), (64, 16, 88, 40), (16, 64, 16, 64)):
        recorder.set_pixel(end_x, end_y, 0x0000CC)  # Must survive if LineTo excludes endpoint.
        recorder.move_to(x, y)
        recorder.line_to(end_x, end_y)
    yield "drawing-line-endpoints", recorder

    for primitive in ("rectangle", "ellipse"):
        for name, width, height in (
            ("even", 32, 32),
            ("odd", 33, 33),
            ("wide", 70, 19),
            ("tall", 19, 70),
            ("one-wide", 1, 25),
            ("two-wide", 2, 25),
            ("empty", 0, 25),
        ):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, 1, 0))
            recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
            getattr(recorder, primitive)(24, 24, 24 + width, 24 + height)
            yield f"drawing-{primitive}-{name}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 0, 0))
    recorder.move_to(8, 8)
    recorder.set_viewport_origin(32, 16)
    recorder.set_window_extent(64, 64)
    recorder.line_to(32, 32)
    yield "state-current-position-mapping", recorder

    for restore in ("relative", "absolute"):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, 0, 0))
        recorder.move_to(8, 8)
        saved = recorder.save_dc()
        recorder.set_viewport_origin(32, 16)
        recorder.select_object(recorder.create_pen(0, 0, 0x0000CC))
        recorder.move_to(8, 32)
        recorder.save_dc()
        recorder.set_window_extent(64, 64)
        recorder.line_to(32, 32)
        recorder.restore_dc(-2 if restore == "relative" else saved)
        recorder.line_to(96, 8)
        yield f"state-save-restore-{restore}", recorder

    for before in (True, False):
        recorder = mapped()
        if before:
            recorder.intersect_clip_rect(16, 16, 64, 64)
        recorder.set_viewport_origin(32, 32)
        if not before:
            recorder.intersect_clip_rect(16, 16, 64, 64)
        filled_box(recorder, (0, 0, 80, 80))
        yield f"state-clip-{'before' if before else 'after'}-mapping", recorder

    recorder = mapped()
    recorder.intersect_clip_rect(8, 8, 48, 48)
    recorder.set_viewport_origin(32, 32)
    recorder.set_window_extent(64, 64)
    recorder.offset_clip_region(8, 4)
    filled_box(recorder, (-16, -16, 48, 48))
    yield "state-clip-offset-vector", recorder


def stroke_cases():
    """Probe the algorithms beyond the original three-segment pen fixtures."""
    for width in (3, 6):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, width, 0))
        recorder.select_object(recorder.create_brush(1, 0, 0))
        recorder.ellipse(24, 24, 96, 80)
        yield f"stroke-ellipse-null-width-{width}", recorder
    transforms = (
        ("identity", (128, 128), (128, 128)),
        ("scale-x", (128, 128), (256, 128)),
        ("scale-y", (128, 128), (128, 256)),
        ("half", (256, 256), (128, 128)),
        ("reflect-x", (128, 128), (-128, 128)),
        ("fractional", (256, 384), (384, 256)),
    )
    directions = ((24, 0), (24, 6), (24, 12), (24, 24), (12, 24), (6, 24), (0, 24))
    for width in (1, 2, 3, 4, 5, 6, 7, 12):
        for name, window, viewport in transforms:
            recorder = mapped()
            recorder.set_window_extent(*window)
            recorder.set_viewport_extent(*viewport)
            recorder.set_viewport_origin(64, 64)
            recorder.select_object(recorder.create_pen(0, width, 0))
            for sx, sy in ((1, 1), (-1, 1), (-1, -1), (1, -1)):
                for index, (dx, dy) in enumerate(directions):
                    start, end = (sx * (dx // 3), sy * (dy // 3)), (sx * dx, sy * dy)
                    if index % 2:
                        start, end = end, start
                    recorder.move_to(*start)
                    recorder.line_to(*end)
            yield f"stroke-octants-{width}-{name}", recorder

    for numerator in (5, 6, 7):
        recorder = mapped()
        recorder.set_window_extent(128 * 4, 128)
        recorder.set_viewport_extent(128 * numerator, 128)
        recorder.select_object(recorder.create_pen(0, 1, 0))
        for y in (16, 48, 80):
            recorder.move_to(8, y)
            recorder.line_to(56, y + 16)
        yield f"stroke-hairline-threshold-{numerator}-quarters", recorder

    for primitive in ("rectangle", "ellipse"):
        for width in (2, 3, 6, 12):
            recorder = mapped()
            recorder.select_object(recorder.create_pen(0, width, 0))
            recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
            getattr(recorder, primitive)(24, 24, 96, 80)
            yield f"stroke-{primitive}-width-{width}", recorder

    for primitive in ("rectangle", "ellipse"):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, 1, 0))
        recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
        for index, (width, height) in enumerate(((1, 1), (1, 2), (2, 1), (2, 2), (3, 3), (4, 4), (2, 5), (5, 2))):
            x, y = 16 + index % 4 * 24, 24 + index // 4 * 40
            getattr(recorder, primitive)(x, y, x + width, y + height)
        yield f"stroke-{primitive}-degenerate", recorder

    recorder = mapped()
    recorder.intersect_clip_rect(160, 160, 200, 200)
    recorder.offset_clip_region(-144, -144)
    filled_box(recorder, (0, 0, 100, 100))
    yield "state-clip-offset-from-outside", recorder

    recorder = mapped()
    recorder.intersect_clip_rect(24, 24, 64, 64)
    recorder.ellipse(24, 16, 25, 80)
    recorder.select_object(recorder.create_pen(0, 6, 0))
    recorder.ellipse(40, 8, 96, 80)
    yield "state-clip-ellipse-strokes", recorder


def polygon_cases():
    """Native references for connected strokes and polygon fill rules."""
    for width in (0, 3, 8):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(0, width, 0))
        recorder.set_pixel(104, 88, 0x000000CC)
        recorder.polyline(((16, 24), (48, 24), (64, 56), (104, 88)))
        yield f"polyline-open-width-{width}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 6, 0))
    recorder.polyline(((16, 16), (104, 16), (104, 104), (16, 104), (16, 16)))
    yield "polyline-explicit-closure", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 5, 0))
    recorder.polyline(((16, 24), (16, 24), (64, 24), (64, 24), (96, 72), (96, 72)))
    yield "polyline-repeated-vertices", recorder

    recorder = mapped()
    recorder.set_viewport_extent(-128, 128)
    recorder.set_viewport_origin(120, 0)
    recorder.select_object(recorder.create_pen(0, 4, 0))
    recorder.polyline(((16, 24), (40, 80), (72, 40), (104, 96)))
    yield "polyline-reflect-x", recorder

    concave = ((16, 16), (112, 16), (112, 48), (64, 48), (64, 112), (16, 112))
    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
    recorder.polygon(concave)
    yield "polygon-concave-fill", recorder

    triangle = ((13, 17), (105, 29), (37, 111))
    for reverse, direction in ((False, "forward"), (True, "reversed")):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
        recorder.polygon(triangle[::-1] if reverse else triangle)
        yield f"polygon-slanted-{direction}", recorder

    recorder = mapped()
    recorder.set_window_extent(256, 256)
    recorder.set_viewport_extent(128, 128)
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
    recorder.polygon(((25, 33), (211, 41), (75, 223)))
    yield "polygon-slanted-half-scale", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 7, 0))
    recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
    recorder.polygon(((16, 16), (112, 24), (88, 104), (32, 88)))
    yield "polygon-wide-outline", recorder

    for mode, label in ((1, "alternate"), (2, "winding")):
        recorder = mapped()
        recorder.set_polygon_fill_mode(mode)
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
        recorder.polygon(((16, 16), (112, 16), (112, 112), (16, 112), (16, 16), (112, 16), (112, 112), (16, 112)))
        yield f"polygon-double-wound-{label}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(0, 3, 0))
    recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
    recorder.poly_polygon((((8, 16), (48, 16), (48, 56), (8, 56)), ((72, 72), (112, 72), (112, 112), (72, 112))))
    yield "poly-polygon-disjoint", recorder

    overlapping = (
        ((12, 12), (80, 12), (80, 80), (12, 80)),
        ((48, 48), (116, 48), (116, 116), (48, 116)),
    )
    for mode, label in ((1, "alternate"), (2, "winding")):
        recorder = mapped()
        recorder.set_polygon_fill_mode(mode)
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
        recorder.poly_polygon(overlapping)
        yield f"poly-polygon-overlap-{label}", recorder

    outer = ((12, 12), (116, 12), (116, 116), (12, 116))
    inner = ((40, 40), (88, 40), (88, 88), (40, 88))
    for mode, label in ((1, "alternate"), (2, "winding")):
        for reverse, orientation in ((False, "same"), (True, "opposite")):
            recorder = mapped()
            recorder.set_polygon_fill_mode(mode)
            recorder.select_object(recorder.create_pen(5, 0, 0))
            recorder.select_object(recorder.create_brush(0, 0x00AA00, 0))
            recorder.poly_polygon((outer, inner[::-1] if reverse else inner))
            yield f"poly-polygon-nested-{label}-{orientation}", recorder


def rop2_cases():
    """Exercise each binary mode against nontrivial source and destination RGB."""
    destination = 0x00663399
    source = 0x00CA5BE1
    for primitive in ("lines", "fills"):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, destination, 0))
        recorder.rectangle(0, 0, 128, 128)
        if primitive == "lines":
            recorder.select_object(recorder.create_pen(0, 3, source))
        else:
            recorder.select_object(recorder.create_brush(0, source, 0))
        for mode in range(1, 17):
            x, y = ((mode - 1) % 4 * 32, (mode - 1) // 4 * 32)
            recorder.set_rop2(mode)
            if primitive == "lines":
                recorder.move_to(x + 4, y + 16)
                recorder.line_to(x + 28, y + 16)
            else:
                recorder.rectangle(x + 4, y + 4, x + 28, y + 28)
        yield f"rop2-{primitive}-all", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, destination, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_pen(0, 3, source))
    recorder.set_rop2(7)  # XOR
    recorder.set_pixel(16, 16, source)
    recorder.move_to(8, 32)
    recorder.line_to(40, 32)
    recorder.save_dc()
    recorder.set_rop2(11)  # NOP
    recorder.set_pixel(64, 16, source)
    recorder.move_to(56, 32)
    recorder.line_to(88, 32)
    recorder.restore_dc(-1)
    recorder.move_to(56, 64)
    recorder.line_to(88, 64)
    yield "rop2-state-setpixel", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, destination, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_pen(0, 7, source))
    recorder.set_rop2(7)  # XOR: segment and join overlap must not cancel.
    recorder.polyline(((16, 16), (72, 16), (72, 72), (112, 72)))
    recorder.move_to(16, 104)
    recorder.line_to(112, 104)
    recorder.move_to(16, 104)
    recorder.line_to(112, 104)
    yield "rop2-joined-strokes", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, destination, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_pen(0, 7, source))
    recorder.select_object(recorder.create_brush(0, source, 0))
    recorder.set_rop2(7)
    recorder.rectangle(16, 16, 72, 72)
    recorder.polygon(((88, 24), (120, 72), (80, 72)))
    yield "rop2-fill-and-outline", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, destination, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_pen(0, 7, source))
    recorder.select_object(recorder.create_brush(0, 0x0017A958, 0))
    recorder.set_rop2(7)
    recorder.rectangle(16, 16, 72, 72)
    recorder.polygon(((88, 24), (120, 72), (80, 72)))
    yield "rop2-distinct-pen-brush", recorder


def brush_cases():
    recorder = mapped()
    recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_pen(0, 3, 0x0000AA00))
    recorder.select_object(recorder.create_brush(1, 0x000000FF, 0))
    recorder.rectangle(12, 12, 64, 64)
    recorder.polygon(((72, 16), (116, 56), (64, 72)))
    yield "brush-null", recorder

    for mode, label in ((1, "transparent"), (2, "opaque")):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
        recorder.rectangle(0, 0, 128, 128)
        recorder.set_background_mode(mode)
        recorder.set_background_color(0x0033CC77)
        for hatch in range(6):
            x, y = (hatch % 3) * 40 + 5, (hatch // 3) * 55 + 7
            recorder.select_object(recorder.create_brush(2, 0x00CA5BE1, hatch))
            recorder.rectangle(x, y, x + 31, y + 37)
        yield f"brush-hatches-{label}", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_brush(2, 0x00CA5BE1, 4))
    recorder.set_background_mode(1)
    recorder.set_background_color(0x0033CC77)
    recorder.rectangle(8, 8, 40, 40)
    recorder.save_dc()
    recorder.set_background_mode(2)
    recorder.set_background_color(0x0000AAFF)
    recorder.rectangle(48, 8, 80, 40)
    recorder.restore_dc(-1)
    recorder.rectangle(88, 8, 120, 40)
    yield "brush-background-state", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.select_object(recorder.create_brush(2, 0x00CA5BE1, 5))
    recorder.set_background_mode(2)
    recorder.set_background_color(0x0033CC77)
    recorder.set_rop2(7)
    recorder.rectangle(11, 13, 57, 59)
    recorder.set_window_extent(64, 64)
    recorder.rectangle(39, 7, 59, 25)
    yield "brush-hatch-rop2-mapped", recorder


def styled_pen_cases():
    for mode, label in ((1, "transparent"), (2, "opaque")):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
        recorder.rectangle(0, 0, 128, 128)
        recorder.set_background_mode(mode)
        recorder.set_background_color(0x0033CC77)
        for style in range(1, 5):
            recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
            y = 12 + (style - 1) * 27
            recorder.move_to(7, y)
            recorder.line_to(120, y)
        yield f"pen-styles-lines-{label}", recorder

    for mode, label in ((1, "transparent"), (2, "opaque")):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(5, 0, 0))
        recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
        recorder.rectangle(0, 0, 128, 128)
        recorder.set_background_mode(mode)
        recorder.set_background_color(0x0033CC77)
        for style in range(1, 5):
            recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
            y = 8 + (style - 1) * 28
            recorder.polyline(((8, y + 16), (34, y), (60, y + 16), (84, y), (118, y + 16)))
        yield f"pen-styles-polyline-{label}", recorder

    for style in range(1, 5):
        recorder = mapped()
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
        recorder.set_background_mode(1)
        recorder.rectangle(12, 12, 60, 52)
        recorder.ellipse(68, 12, 116, 52)
        recorder.polygon(((16, 72), (56, 72), (72, 112), (8, 112)))
        yield f"pen-style-{style}-shapes", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.set_background_mode(1)
    for style in range(1, 5):
        recorder.select_object(recorder.create_pen(style, 2, 0x00CA5BE1))
        y = 12 + (style - 1) * 27
        recorder.move_to(7, y)
        recorder.line_to(120, y)
    yield "pen-styles-wide", recorder

    for style in range(1, 5):
        recorder = mapped()
        recorder.set_background_mode(1)
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        recorder.select_object(recorder.create_brush(1, 0, 0))
        recorder.ellipse(8, 8, 57, 43)
        recorder.ellipse(66, 16, 121, 69)
        recorder.ellipse(17, 76, 103, 111)
        yield f"pen-style-{style}-ellipses", recorder

        recorder = mapped()
        recorder.set_background_mode(1)
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        recorder.select_object(recorder.create_brush(1, 0, 0))
        recorder.ellipse(12, 12, 40, 43)
        recorder.ellipse(64, 12, 102, 61)
        recorder.ellipse(20, 72, 76, 119)
        yield f"pen-style-{style}-ellipse-phase", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(1, 1, 0x00CA5BE1))
    recorder.set_window_extent(64, 64)
    recorder.move_to(5, 10)
    recorder.line_to(60, 10)
    recorder.select_object(recorder.create_pen(2, 0, 0x00CA5BE1))
    recorder.move_to(5, 20)
    recorder.line_to(60, 20)
    yield "pen-styles-scaled", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(1, 1, 0x00CA5BE1))
    recorder.move_to(-20, 12)
    recorder.line_to(120, 12)
    recorder.intersect_clip_rect(35, 0, 80, 128)
    recorder.move_to(7, 24)
    recorder.line_to(120, 24)
    yield "pen-style-clipped-phase", recorder

    for style in range(1, 5):
        recorder = mapped()
        recorder.set_background_mode(1)
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        recorder.polyline(
            (
                (120, 42),
                (119, 37),
                (118, 32),
                (112, 24),
                (104, 18),
                (98, 17),
                (93, 16),
                (88, 17),
                (83, 18),
                (74, 24),
                (68, 32),
                (67, 37),
                (66, 42),
            )
        )
        yield f"pen-style-{style}-axis-switch", recorder

    recorder = mapped()
    recorder.select_object(recorder.create_pen(5, 0, 0))
    recorder.select_object(recorder.create_brush(0, 0x00663399, 0))
    recorder.rectangle(0, 0, 128, 128)
    recorder.set_background_mode(2)
    recorder.set_background_color(0x0033CC77)
    recorder.set_rop2(7)
    for style in range(1, 5):
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        y = 12 + (style - 1) * 27
        recorder.move_to(7, y)
        recorder.line_to(120, y)
    yield "pen-styles-rop2-gaps", recorder

    recorder = mapped()
    recorder.set_background_mode(1)
    for style in range(1, 5):
        recorder.select_object(recorder.create_pen(style, 1, 0x00CA5BE1))
        y = 12 + (style - 1) * 27
        recorder.polyline(((-80, y), (-32, y), (96, y)))
    yield "pen-styles-offscreen-connected", recorder


def region_paint_cases():
    islands = (Scan(3, 23, (5, 17, 19, 31, 33, 45)), Scan(23, 37, (5, 45)), Scan(37, 63, (15, 21)))
    ring = (Scan(3, 19, (5, 67)), Scan(19, 47, (5, 21, 43, 67)), Scan(47, 63, (5, 67)))
    for name, extent, size, scans, index in (
        ("small-mirror", (-64, 64), (1, 1), (Scan(3, 63, (5, 67)),), 20),
        ("fraction-state", (43, 77), (19, 23), (Scan(3, 63, (5, 67)),), 63),
        ("fraction-hole", (43, 77), (-5, -7), ring, 138),
        ("fraction-hole-edge", (43, 77), (5, 7), ring, 132),
        ("fraction-hole-filled", (43, 77), (100, 100), ring, 139),
        ("fraction-islands-small", (43, 77), (2, 3), islands, 271),
        ("fraction-islands", (43, 77), (5, 7), islands, 272),
        ("fraction-islands-large", (43, 77), (19, 23), islands, 273),
    ):
        yield "region-frame-native-" + name, region_paint_probe_case("frame_region", 0, 13, extent, size, scans, index)
    for extent in (96, -96, 43):
        r = mapped()
        brush = r.create_brush(0, 0x00663399, 0)
        r.set_viewport_extent(extent, 128)
        r.set_viewport_origin(112 if extent < 0 else 7, 0)
        for width in range(1, 21):
            top = (width - 1) * 6 + 1
            region = r.create_region(Region((5, top, 125, top + 5), (Scan(top, top + 5, (5, 125)),)))
            r.frame_region(region, brush, width, 1)
            r.delete_object(region)
        yield f"region-frame-width-atlas-{extent}", r
    for origin, size in product(range(4), ((1, 1), (5, 7), (19, 23))):
        r = mapped()
        brush = r.create_brush(0, 0x00663399, 0)
        region = r.create_region(Region((5, 3, 67, 63), (Scan(3, 63, (5, 67)),)))
        r.set_viewport_extent(96, 144)
        r.set_window_origin(origin, origin)
        r.set_viewport_origin(7, 9)
        r.frame_region(region, brush, *size)
        yield f"region-frame-phase-{origin}-{size[0]}", r
    for extent, size, index in (
        ((96, 144), (1, 1), 40),
        ((96, 144), (19, 23), 43),
        ((43, 77), (5, 7), 62),
        ((43, 77), (19, 23), 63),
        ((96, 144), (-5, 7), 46),
    ):
        r = mapped()
        brush = r.create_brush(0, 0x00663399, 0)
        region = r.create_region(Region((5, 3, 67, 63), (Scan(3, 63, (5, 67)),)))
        r.set_viewport_extent(*extent)
        r.set_window_origin(index % 5 - 2, index % 7 - 3)
        r.set_viewport_origin(7, 9)
        r.frame_region(region, brush, *size)
        yield f"region-frame-fraction-{index}", r
    for mode in (1, 6, 16):
        r = mapped()
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, 0x00554433, 0))
        r.rectangle(0, 0, 128, 128)
        r.select_object(r.create_brush(2, 0x00CC7733, 5))
        r.set_background_mode(1)
        r.set_rop2(mode)
        r.rectangle(8, 8, 55, 55)
        r.ellipse(67, 8, 120, 55)
        r.polygon(((67, 67), (120, 67), (120, 120), (67, 120)))
        region = r.create_region(Region((8, 67, 55, 120), (Scan(67, 120, (8, 55)),)))
        r.paint_region(region)
        yield f"brush-independent-rop-{mode}", r
    for operation, extent in product(
        ("fill_region", "paint_region", "invert_region", "frame_region"),
        ((64, 64), (-64, 64), (64, -64)),
    ):
        r = mapped()
        brush = r.create_brush(0, 0x00663399, 0)
        r.select_object(brush)
        handle = r.create_region(
            Region(
                (1, 1, 111, 111),
                (
                    Scan(1, 31, (1, 111)),
                    Scan(31, 79, (1, 31, 79, 111)),
                    Scan(79, 111, (1, 111)),
                ),
            )
        )
        r.set_viewport_extent(*extent)
        r.set_viewport_origin(80 if extent[0] < 0 else 7, 80 if extent[1] < 0 else 7)
        if operation in ("fill_region", "frame_region"):
            getattr(r, operation)(handle, brush, *((5, 7) if operation == "frame_region" else ()))
        else:
            getattr(r, operation)(handle)
        yield f"region-paint-halves-{operation}-{extent[0]}-{extent[1]}", r
    # A ring with a narrow arm and disconnected islands: internal scan-band
    # boundaries must not become frame edges.
    shape = Region(
        (8, 8, 112, 112),
        (Scan(8, 24, (8, 88)), Scan(24, 64, (8, 24, 64, 88)), Scan(64, 80, (8, 88)), Scan(80, 104, (40, 46, 96, 112))),
    )
    for operation, state in product(
        ("fill_region", "paint_region", "invert_region", "frame_region"),
        ("solid", "hatch", "transparent", "null", "mapped", "reflected", "xor", "clip"),
    ):
        r = mapped()
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, 0x00554433, 0))
        r.rectangle(0, 0, 128, 128)
        brush = r.create_brush(1 if state == "null" else 2 if state in ("hatch", "transparent") else 0, 0x00CC7733, 5)
        r.select_object(brush)
        handle = r.create_region(shape)
        r.set_background_color(0x002299EE)
        r.set_background_mode(1 if state == "transparent" else 2)
        if state in ("mapped", "reflected"):
            r.set_window_origin(3, 5)
            r.set_viewport_extent(-96 if state == "reflected" else 96, 144)
            r.set_viewport_origin(112 if state == "reflected" else 7, -3)
        if state == "xor":
            r.set_rop2(7)
        if state == "clip":
            r.exclude_clip_rect(15, 13, 70, 73)
        if operation in ("fill_region", "frame_region"):
            r.select_object(r.create_brush(0, 0x0011EE22, 0))
            getattr(r, operation)(handle, brush, *((5, 9) if operation == "frame_region" else ()))
        else:
            getattr(r, operation)(handle)
        yield f"region-paint-{operation}-{state}", r

    for width, height in ((0, 0), (0, 4), (4, 0), (-3, 4), (3, -4), (1, 1), (18, 27), (60, 60)):
        r = mapped()
        brush = r.create_brush(0, 0x00663399, 0)
        handle = r.create_region(shape)
        r.frame_region(handle, brush, width, height)
        yield f"region-frame-size-{width}-{height}", r


def region_paint_probe_case(operation, style, mode, extent, size, scans, index):
    """Shared recorder setup for native matrix cases and captured regressions."""
    r = mapped()
    r.select_object(r.create_pen(5, 0, 0))
    r.select_object(r.create_brush(0, 0x0037598B, 0))
    r.rectangle(0, 0, 128, 128)
    brush = r.create_brush(style, 0x00A96C32, index % 6)
    other = r.create_brush(2, 0x002194EF, 4)
    r.select_object(other if operation in ("fill_region", "frame_region") else brush)
    # Allocate brushes before a possibly failed region, avoiding slot reuse.
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
    # Subsequent drawing observes state preservation without hiding the region.
    r.rectangle(75, 3, 90, 16)
    return r


def flood_cases():
    """Flood topology and brush/ROP atlases, using only established setup calls."""
    for mode in (0, 1):
        for state in ("solid", "null", "opaque", "transparent"):
            for operation in range(1, 17):
                r = mapped()
                r.select_object(r.create_pen(5, 0, 0))
                r.select_object(r.create_brush(0, 0x37598B, 0))
                r.rectangle(4, 4, 124, 124)
                # Different-coloured island: surface excludes it, border crosses it.
                r.select_object(r.create_brush(0, 0x123456, 0))
                r.rectangle(45, 35, 65, 75)
                r.select_object(r.create_brush(1 if state == "null" else 2 if state != "solid" else 0, 0xA96C32, 5))
                r.set_background_color(0x5DB742)
                r.set_background_mode(1 if state == "transparent" else 2)
                r.set_rop2(operation)
                r.ext_flood_fill(12, 12, 0xFFFFFF if mode == 0 else 0x37598B, mode)
                yield f"flood-state-{mode}-{state}-{operation}", r
        for topology in (
            "diagonal",
            "gap",
            "clip-wall",
            "clip-hole",
            "clip-islands",
            "outside",
            "wrong",
            "unbounded",
            "mapped",
            "reflected",
            "same",
        ):
            r = mapped()
            r.select_object(r.create_pen(5, 0, 0))
            r.select_object(r.create_brush(0, 0, 0))
            r.rectangle(0, 0, 128, 128)
            r.select_object(r.create_brush(0, 0xFFFFFF, 0))
            r.rectangle(8, 8, 60, 60)
            r.rectangle(60, 60, 112, 112)
            if topology == "gap":
                r.set_pixel(59, 60, 0xFFFFFF)
            if topology == "clip-wall":
                r.exclude_clip_rect(30, 0, 31, 128)
            if topology == "clip-hole":
                r.exclude_clip_rect(30, 20, 40, 40)
            if topology == "clip-islands":
                r.select_clip_region(r.create_region(Region((8, 8, 60, 60), (Scan(8, 60, (8, 25, 35, 60)),))))
            seed = (12, 12)
            if topology == "outside":
                seed = (-1, 12)
            if topology == "wrong":
                seed = (0, 0)
            if topology == "unbounded":
                seed = (0, 0)
            if topology in ("mapped", "reflected"):
                r.set_viewport_extent(-64 if topology == "reflected" else 64, 192)
                r.set_viewport_origin(32 if topology == "reflected" else 0, 0)
                seed = (24, 8)
            r.select_object(r.create_brush(0, 0xFFFFFF if topology == "same" else 0x22CC77, 0))
            color = (0x123456 if mode == 0 else 0) if topology == "unbounded" else (0 if mode == 0 else 0xFFFFFF)
            r.ext_flood_fill(*seed, color, mode)
            yield f"flood-topology-{mode}-{topology}", r
    r = mapped()
    r.select_object(r.create_brush(0, 0xCC7733, 0))
    r.flood_fill(64, 64, 0)
    yield "flood-legacy", r


def pat_blt_cases():
    # One tile per truth table. Source-dependent operations must not silently
    # acquire an invented source colour. Noncanonical low words probe decoding.
    for style, hatch, background in ((0, 0, 2), (1, 0, 2), *product((2,), range(6), (1, 2))):
        r = mapped()
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, 0x37598B, 0))
        r.rectangle(0, 0, 128, 128)
        r.select_object(r.create_brush(style, 0xA96C32, hatch))
        r.set_background_mode(background)
        r.set_background_color(0x5DB742)
        r.set_rop2(7)  # PatBlt must use its explicit ROP, not DC ROP2.
        for table in range(256):
            r.pat_blt((table % 16) * 8, (table // 16) * 8, 8, 8, table << 16)
        yield f"patblt-tables-{style}-{hatch}-{background}", r
    for extent in ((128, 128), (64, 192), (-64, 192), (64, -192), (-128, -128), (43, 77), (127, 129)):
        for clipped in (False, True):
            r = mapped()
            r.select_object(r.create_brush(0, 0xA96C32, 0))
            r.set_window_origin(3, 5)
            r.set_viewport_origin(112 if extent[0] < 0 else 7, 112 if extent[1] < 0 else 9)
            r.set_viewport_extent(*extent)
            if clipped:
                r.exclude_clip_rect(25, 0, 35, 128)
            for index, (width, height) in enumerate(product((-9, -1, 0, 1, 9), repeat=2)):
                r.pat_blt(15 + (index % 5) * 23, 15 + (index // 5) * 23, width, height, 0x00F00021)
            yield f"patblt-extents-{extent[0]}-{extent[1]}-{int(clipped)}", r
    for flags in (0, 0x40000000, 0x80000000, 0xFFFF):
        r = mapped()
        r.select_object(r.create_brush(2, 0xA96C32, 5))
        r.set_background_mode(1)
        for index, rop in enumerate((0x00000042, 0x00550009, 0x00F00021, 0x005A0049, 0x00FF0062)):
            r.pat_blt(4 + index * 24, 4, 20, 100, rop | flags)
        yield f"patblt-code-bits-{flags:x}", r


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, recorder in cases():
        path = FIXTURES / f"{name}.wmf"
        path.write_bytes(recorder.to_bytes())
        print(path.relative_to(FIXTURES.parent))


if __name__ == "__main__":
    main()
