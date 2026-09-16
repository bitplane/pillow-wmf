"""Capture native Pie paths, including centre placement and closure order."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface, render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play
from pillow_wmf.ellipse import arc_figure


def verify_pixels():
    """Holdouts beyond the committed sweep atlases; no local image oracle."""
    failures = 0
    cases = product(
        ((9, 17, 117, 108), (24, 8, 103, 121), (61, 8, 62, 120), (8, 8, 8, 64)),
        (((123, 63), (64, 2)), ((90, 27), (23, 103)), ((124, 65), (124, 66)), ((97, 63), (97, 63))),
        ((0, 1), (0, 7), (4, 1), (5, 1)),
        (0, 1, 2),
    )
    for index, (box, radials, pen, brush) in enumerate(cases):
        recorder = Recorder()
        recorder.set_map_mode(8)
        recorder.set_window_extent(128, 128)
        recorder.set_viewport_extent(128, 128)
        recorder.select_object(recorder.create_pen(*pen, 0x00402010))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 5))
        recorder.set_background_mode(1 if index % 2 else 2)
        recorder.set_rop2(7 if index % 3 == 0 else 13)
        if index % 5 == 0:
            recorder.intersect_clip_rect(31, 19, 103, 99)
        recorder.pie(*box, *radials[0], *radials[1])
        data = recorder.to_bytes()
        native = render_wmf(data, 128, 128)
        context = RasterContext(128, 128)
        assert play(Metafile.from_bytes(data), context, strict=True) == ()
        differing = sum(
            a != b for a, b in zip(native.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            print("pie-pixels-FAIL", index, box, radials, pen, brush, differing)
    print("pie-pixel-matrix", index + 1, failures)
    assert not failures


def verify_composition():
    failures = 0
    for operation, width, mode in product(("pie", "chord", "ellipse", "polygon"), (1, 7), range(1, 17)):
        recorder = Recorder()
        recorder.select_object(recorder.create_pen(0, width, 0x00402010))
        recorder.select_object(recorder.create_brush(0, 0x00CC8844, 0))
        recorder.set_rop2(mode)
        if operation == "polygon":
            recorder.polygon(((24, 8), (103, 31), (23, 103), (65, 64)))
        else:
            args = (24, 8, 103, 121)
            if operation != "ellipse":
                args += (90, 27, 23, 103)
            getattr(recorder, operation)(*args)
        data = recorder.to_bytes()
        native = render_wmf(data, 128, 128)
        context = RasterContext(128, 128)
        assert play(Metafile.from_bytes(data), context, strict=True) == ()
        differing = sum(
            a != b for a, b in zip(native.get_flattened_data(), context.image.get_flattened_data(), strict=True)
        )
        if differing:
            failures += 1
            print("composition-FAIL", operation, width, mode, differing)
    print("composition-matrix", 128, failures)
    assert not failures


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "Pie", boolean, ptr, *([integer] * 8))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for style, width in ((0, 1), (0, 7), (1, 1), (5, 1)):
            pen = check(gdi.CreatePen(style, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for args in (
                    (8, 16, 120, 112, 120, 64, 120, 64),
                    (8, 16, 120, 112, 120, 64, 176, 64),
                    (5, 6, 28, 27, 36, 16, 36, -4),
                    (8, 16, 120, 112, 117, 43, 31, 107),
                    (25, 3, 78, 64, 90, 30, 30, 80),
                    (60, 8, 63, 120, 100, 30, 20, 80),
                ):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Pie(dc, *args), "Pie")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count > 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    path = arc_figure(*args[:4], args[4:6], args[6:8], closure="pie", null_pen=style == 5)
                    expected = (path.commands[0][0], *(p for command in path.commands[:-1] for p in command[1:]))
                    assert tuple((p.x, p.y) for p in points) == expected, (style, width, args)
                    assert tuple(kinds) == (6, *([4] * (count - 2)), 3)
                    print("Pie", style, width, args, tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)))
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
    verify_composition()
    verify_pixels()
