"""Regenerate the small, deterministic WMF compatibility inputs."""

from pathlib import Path

from pillow_wmf import Recorder

FIXTURES = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "wmf"


def cases():
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


def mapped():
    recorder = Recorder()
    recorder.set_map_mode(8)
    recorder.set_window_extent(128, 128)
    recorder.set_viewport_extent(128, 128)
    return recorder


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


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, recorder in cases():
        path = FIXTURES / f"{name}.wmf"
        path.write_bytes(recorder.to_bytes())
        print(path.relative_to(FIXTURES.parent))


if __name__ == "__main__":
    main()
