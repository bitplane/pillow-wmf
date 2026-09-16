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


def main():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, recorder in cases():
        path = FIXTURES / f"{name}.wmf"
        path.write_bytes(recorder.to_bytes())
        print(path.relative_to(FIXTURES.parent))


if __name__ == "__main__":
    main()
