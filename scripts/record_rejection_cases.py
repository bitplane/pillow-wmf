"""Record-local failure boundaries with a visible continuation marker."""

from dataclasses import replace

from pillow_wmf import Metafile, Recorder
from pillow_wmf.wmf import fixed, variable


def cases():
    for name, records in (
        ("delete-unallocated", [fixed.DeleteObject(3)]),
        ("delete-twice", [fixed.DeleteObject(0), fixed.DeleteObject(0)]),
        ("select-deleted", [fixed.DeleteObject(0), fixed.SelectObject(0)]),
        ("wrong-region-kind", [fixed.InvertRegion(0)]),
    ):
        program = Metafile.build([fixed.CreatePenIndirect(0, 3, 0, 0), *records, fixed.SetPixel(255, 120, 120)])
        yield name, replace(program, header=replace(program.header, object_count=4))
    for width in (0, 3):
        for count in (0, 1, 2):
            yield (
                f"polygon-{count}-pen-{width}",
                Metafile.build(
                    [
                        fixed.CreatePenIndirect(0, width, 0, 0),
                        fixed.SelectObject(0),
                        variable.Polygon(((30, 30), (60, 50))[:count]),
                        fixed.SetPixel(255, 120, 120),
                    ]
                ),
            )


def corpus_cases():
    for mode in (0, 65535):
        r = Recorder()
        r.set_background_color(0x00FF00)
        r.set_background_mode(2)
        r.set_background_mode(mode)
        r.select_object(r.create_brush(2, 0x0000FF, 0))
        r.pat_blt(10, 10, 30, 30, 0x00F00021)
        r.set_pixel(120, 120, 255)
        yield f"background-{mode}", r.metafile()
    for width in (-1, -3, -32768):
        r = Recorder()
        r.select_object(r.create_pen(0, width, 255))
        r.move_to(20, 20)
        r.line_to(50, 40)
        r.set_pixel(120, 120, 255)
        yield f"negative-pen-{abs(width)}", r.metafile()
    for level in (-2, 0, 2):
        r = Recorder()
        r.save_dc()
        r.set_window_origin(5, 5)
        # Construct invalid references as records, not checked GDI calls.
        records = [
            *r.records,
            fixed.RestoreDC(level),
            fixed.SetPixel(255, 25, 25),
            fixed.RestoreDC(-1),
            fixed.SetPixel(255, 120, 120),
        ]
        yield f"restore-invalid-{level}", Metafile.build(records)
    for name, records, capacity in (
        ("select-outside", [fixed.SelectObject(9)], 1),
        ("delete-outside", [fixed.DeleteObject(9)], 1),
        ("object-overflow", [fixed.CreatePenIndirect(0, 3, 0, 0xFF0000), fixed.SelectObject(0)], 1),
    ):
        m = Metafile.build(
            [
                fixed.CreatePenIndirect(0, 1, 0, 255),
                *records,
                fixed.MoveTo(20, 20),
                fixed.LineTo(40, 50),
                fixed.SetPixel(255, 120, 120),
            ]
        )
        yield name, replace(m, header=replace(m.header, object_count=capacity))
