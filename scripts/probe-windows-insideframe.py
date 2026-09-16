"""Native inside-frame geometry, including overlarge widths and mapping."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface, render_wmf

from pillow_wmf import Metafile, RasterContext, Recorder, play


def verify_pixels():
    failures = 0
    for index, (operation, width, brush, box, viewport) in enumerate(
        product(
            ("rectangle", "ellipse", "round_rect", "arc", "chord", "pie"),
            (0, 1, 2, 3, 6, 7, 20, 21, 22, 36, 37, 38, 40),
            (0, 1, 2),
            ((5, 6, 26, 43), (5, 6, 42, 27), (5, 6, 26, 27)),
            ((128, 128), (192, 96), (192, 192), (-128, 256)),
        )
    ):
        recorder = Recorder()
        recorder.set_map_mode(8)
        recorder.set_window_extent(128, 128)
        recorder.set_viewport_extent(*viewport)
        recorder.set_viewport_origin(128 if viewport[0] < 0 else 0, 0)
        recorder.select_object(recorder.create_pen(6, width, 0x00402010))
        recorder.select_object(recorder.create_brush(brush, 0x00CC8844, 5))
        recorder.set_rop2(7 if index % 2 == 0 else 13)
        args = box
        if operation == "round_rect":
            args += (13, 19)
        elif operation in ("arc", "chord", "pie"):
            args += (35, 16, -5, 34)
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
            print("insideframe-pixels-FAIL", operation, width, brush, box, viewport, differing)
            if operation == "rectangle" and width == 1 and brush == 1 and box == (5, 6, 26, 43):
                for label, image in (("native", native), ("local", context.image)):
                    print(
                        label,
                        "rows",
                        tuple(
                            (y, tuple(x for x in range(48) if image.getpixel((x, y)) != (255, 255, 255)))
                            for y in (4, 5, 6, 7, 16, 30, 31, 32)
                        ),
                    )
    print("insideframe-pixel-matrix", index + 1, failures)
    assert not failures


def verify_collapsed_polygons():
    for style, width, count in product((0, 6), (2, 3, 7, 21), (2, 3, 4)):
        recorder = Recorder()
        recorder.select_object(recorder.create_pen(style, width, 0))
        recorder.polygon(((32, 32),) * count)
        data = recorder.to_bytes()
        native = render_wmf(data, 128, 128)
        context = RasterContext(128, 128)
        assert play(Metafile.from_bytes(data), context, strict=True) == ()
        assert native.tobytes() == context.image.tobytes(), (style, width, count)
    print("collapsed-polygons", 24, "passed")


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "AbortPath", "WidenPath"):
            bind(gdi, name, boolean, ptr)
        for name, count in (("Rectangle", 4), ("Ellipse", 4), ("RoundRect", 6), ("Arc", 8), ("Chord", 8), ("Pie", 8)):
            bind(gdi, name, boolean, ptr, *([integer] * count))
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
        bind(gdi, "LineTo", boolean, ptr, integer, integer)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        for width, scale in product((0, 1, 2, 3, 4, 7, 20, 21, 22, 37, 40), ((1, 1), (2, 1), (1.5, 0.75), (1.5, 1.5))):
            pen = check(gdi.CreatePen(6, width, 0), "CreatePen")
            old = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for operation in ("Rectangle", "Ellipse", "RoundRect", "Arc", "Chord", "Pie"):
                    check(gdi.SetViewportExtEx(dc, int(128 * scale[0]), int(128 * scale[1]), None), "SetViewportExtEx")
                    args = (5, 6, 26, 43)
                    if operation == "RoundRect":
                        args += (13, 19)
                    elif operation in ("Arc", "Chord", "Pie"):
                        args += (35, 16, -5, 34)
                    check(gdi.BeginPath(dc), "BeginPath")
                    succeeded = bool(getattr(gdi, operation)(dc, *args))
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    assert count >= 0
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print(
                        operation,
                        width,
                        scale,
                        succeeded,
                        tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)),
                    )
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
                if width in (1, 7, 21) and scale == (1.5, 0.75):
                    check(gdi.SetViewportExtEx(dc, 192, 96, None), "SetViewportExtEx")
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Rectangle(dc, 5, 6, 26, 43), "Rectangle")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.WidenPath(dc), "WidenPath")
                    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    count = gdi.GetPath(dc, None, None, 0)
                    points = (wintypes.POINT * count)()
                    kinds = (ctypes.c_ubyte * count)()
                    assert gdi.GetPath(dc, points, kinds, count) == count
                    print("widened-rectangle", width, tuple((p.x, p.y, k) for p, k in zip(points, kinds, strict=True)))
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, old)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    main()
    verify_collapsed_polygons()
    verify_pixels()
