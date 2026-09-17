"""Native PatBlt matrix beyond the committed compact atlases."""

from random import Random

from windows_wmf_render import render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.wmf.objects import Region, Scan


def cases():
    random = Random(90137)
    # Enumerate source-independent tables without using the implementation's
    # reducer, then include every source-dependent table as a rejection probe.
    tables = [table for table in range(256) if all((table >> i & 1) == (table >> (i ^ 2) & 1) for i in range(8))]
    for index, table in enumerate(tables * 24 + list(range(256))):
        r = Recorder()
        r.set_map_mode(8)
        r.set_window_extent(128, 128)
        r.set_viewport_extent(128, 128)
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, random.randrange(1 << 24), 0))
        r.rectangle(0, 0, 128, 128)
        r.select_object(r.create_brush(index % 3, random.randrange(1 << 24), index % 6))
        if index % 3 == 0:
            r.select_clip_region(
                r.create_region(
                    Region(
                        (0, 0, 128, 128),
                        (Scan(0, 41, (0, 128)), Scan(41, 79, (0, 31, 63, 128)), Scan(79, 128, (0, 128))),
                    )
                )
            )
        r.set_window_extent(random.choice((64, 127, 128, 192)), random.choice((64, 127, 128, 192)))
        r.set_viewport_extent(
            random.choice((-192, -77, -64, 43, 64, 96, 129)), random.choice((-192, -77, -64, 43, 64, 96, 129))
        )
        r.set_window_origin(random.randrange(-9, 10), random.randrange(-9, 10))
        r.set_viewport_origin(64, 64)
        r.set_background_mode(1 + index % 2)
        r.set_background_color(random.randrange(1 << 24))
        r.set_rop2(1 + index % 16)
        r.move_to(7, 11)
        for _ in range(8):
            x, y, width, height = (random.randrange(-61, 62) for _ in range(4))
            r.pat_blt(x, y, width, height, table << 16 | random.randrange(65536))
        # Observers: explicit ROP must not change DC ROP2, brush, background or
        # current position. Pen selection above suppresses rectangle outlines.
        r.rectangle(-37, -29, -21, -13)
        r.select_object(r.create_pen(0, 0, 0x19CBA3))
        r.line_to(23, 19)
        yield index, r


def verify():
    failures = 0
    for index, recorder in cases():
        source = recorder.to_bytes()
        expected = render_wmf(source, 128, 128)
        context = RasterContext(128, 128)
        play(Metafile.from_bytes(source), context, strict=True)
        count = sum(
            a != b for a, b in zip(expected.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if count:
            failures += 1
            print(f"FAIL PatBlt case {index}: {count} pixels", flush=True)
    print(f"PatBlt: {index + 1} native cases, {failures} failures", flush=True)
    assert failures == 0


if __name__ == "__main__":
    verify()
