"""Small WMFs guarding arithmetic boundaries found in the native binaries."""

from pillow_wmf import Recorder


def cases():
    for layout in (0, 1):
        r = Recorder()
        r.set_map_mode(8)
        r.set_window_extent(6316, 128)
        r.set_viewport_extent(511, 128)
        r.set_window_origin(21707, 0)
        r.set_viewport_origin(138, 0)
        r.set_layout(layout)
        r.select_object(r.create_pen(0, 1, 0))
        for x in (20006, 20007, 20008, 20500, 21000):
            r.move_to(x, 8)
            r.line_to(x, 60)
        r.intersect_clip_rect(20007, 72, 21000, 112)
        r.select_object(r.create_pen(5, 0, 0))
        r.select_object(r.create_brush(0, 0x00CC4400, 0))
        r.rectangle(19900, 64, 21500, 120)
        yield f"mapping-translation-precision-{layout}", r

    for width in (511, 512, 513):
        for reflected in (False, True):
            r = Recorder()
            r.set_map_mode(8)
            r.set_window_extent(1, 1024)
            r.set_viewport_extent(-1 if reflected else 1, 1)
            r.set_viewport_origin(64, 64)
            r.select_object(r.create_pen(0, width, 0))
            r.move_to(-20, -24576)
            r.line_to(20, 24576)
            yield f"pen-thin-size-limit-{width}-{int(reflected)}", r
