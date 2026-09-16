"""Measure solid-pen outlines and pixels over a width/transform/slope matrix.

The report is printed to the CI log; it does not create reference sidecars.
Coordinates in reported paths are sixteenths of a device pixel.
"""

import argparse
import ctypes
import json
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import RasterContext


def main(*, dump_paths=False):
    size = 128
    tested = failures = 0
    with reference_surface(size, size) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "WidenPath", "AbortPath", "StrokePath", "FillPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
        bind(gdi, "LineTo", boolean, ptr, integer, integer)
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "CreateSolidBrush", ptr, wintypes.DWORD)
        bind(gdi, "GdiFlush", boolean)
        bind(gdi, "SaveDC", integer, ptr)
        bind(gdi, "RestoreDC", boolean, ptr, integer)
        bind(gdi, "SetViewportOrgEx", boolean, ptr, integer, integer, ptr)

        def pixels():
            check(gdi.GdiFlush(), "GdiFlush")
            raw = ctypes.string_at(bits, size * size * 4)
            return bytes(raw[index] for index in range(0, len(raw), 4))

        brush = check(gdi.CreateSolidBrush(0), "CreateSolidBrush")
        previous_brush = check(gdi.SelectObject(dc, brush), "SelectObject")
        try:
            for width in (0, 1, 2, 3, 4, 5, 6, 7, 12):
                pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
                previous_pen = check(gdi.SelectObject(dc, pen), "SelectObject")
                try:
                    for scale in (
                        (1, 1, 1, 1),
                        (2, 1, 1, 1),
                        (1, 1, 2, 1),
                        (1, 2, 1, 1),
                        (1, 1, 1, 2),
                        (3, 2, 2, 3),
                        (2, 1, 2, 1),
                        (1, 2, 1, 2),
                        (3, 2, 3, 2),
                        (-1, 1, 1, 1),
                        (1, 1, -1, 1),
                        (-2, 1, 1, 1),
                        (1, 1, -2, 1),
                    ):
                        xn, xd, yn, yd = scale
                        for delta in (
                            (24, 0),
                            (24, 3),
                            (24, 6),
                            (24, 12),
                            (24, 18),
                            (24, 24),
                            (12, 24),
                            (3, 24),
                            (0, 24),
                            (24, -6),
                            (24, -24),
                            (6, -24),
                            (0, 0),
                        ):
                            for reverse in (False, True):
                                check(gdi.SaveDC(dc), "SaveDC")
                                try:
                                    check(gdi.SetWindowExtEx(dc, size * xd, size * yd, None), "SetWindowExtEx")
                                    check(gdi.SetViewportExtEx(dc, size * xn, size * yn, None), "SetViewportExtEx")
                                    check(gdi.SetViewportOrgEx(dc, 40, 40, None), "SetViewportOrgEx")
                                    start, end = (delta, (0, 0)) if reverse else ((0, 0), delta)
                                    ctypes.memset(bits, 255, size * size * 4)
                                    check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                                    check(gdi.LineTo(dc, *end), "LineTo")
                                    direct = pixels()
                                    tested += 1
                                    if not dump_paths:
                                        context = RasterContext(size, size)
                                        context.select_object(context.create_pen(0, width, 0))
                                        context.set_window_extent(size * xd, size * yd)
                                        context.set_viewport_extent(size * xn, size * yn)
                                        context.set_viewport_origin(40, 40)
                                        context.move_to(*start)
                                        context.line_to(*end)
                                        actual = context.image.convert("L").tobytes()
                                        differing = sum(a != b for a, b in zip(actual, direct, strict=True))
                                        if differing:
                                            failures += 1
                                            print(
                                                f"FAIL width={width} scale={scale} {start}->{end}: {differing} pixels"
                                            )
                                        continue
                                    check(gdi.BeginPath(dc), "BeginPath")
                                    check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                                    check(gdi.LineTo(dc, *end), "LineTo")
                                    check(gdi.EndPath(dc), "EndPath")
                                    outline = None
                                    difference = None
                                    if gdi.WidenPath(dc):
                                        check(gdi.SetWindowExtEx(dc, size * 16, size * 16, None), "SetWindowExtEx")
                                        check(gdi.SetViewportExtEx(dc, size, size, None), "SetViewportExtEx")
                                        check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
                                        count = gdi.GetPath(dc, None, None, 0)
                                        if count < 0:
                                            raise OSError("GetPath failed")
                                        points = (wintypes.POINT * count)()
                                        kinds = (ctypes.c_ubyte * count)()
                                        if gdi.GetPath(dc, points, kinds, count) != count:
                                            raise OSError("GetPath changed size")
                                        outline = [(point.x, point.y) for point in points]
                                        ctypes.memset(bits, 255, size * size * 4)
                                        check(gdi.FillPath(dc), "FillPath")
                                        difference = sum(a != b for a, b in zip(direct, pixels(), strict=True))
                                    else:
                                        check(gdi.AbortPath(dc), "AbortPath")
                                    rows = []
                                    for y in range(size):
                                        row = direct[y * size : (y + 1) * size]
                                        if 0 in row:
                                            rows.append((y, [x for x, value in enumerate(row) if value == 0]))
                                    print("STROKE " + json.dumps([width, scale, start, end, outline, difference, rows]))
                                finally:
                                    check(gdi.RestoreDC(dc, -1), "RestoreDC")
                finally:
                    gdi.SelectObject(dc, previous_pen)
                    gdi.DeleteObject(pen)
        finally:
            gdi.SelectObject(dc, previous_brush)
            gdi.DeleteObject(brush)
    print(f"Native strokes: {tested} cases, {failures} failures")
    if failures:
        raise SystemExit(1)


def probe_shapes():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "WidenPath", "AbortPath"):
            bind(gdi, name, boolean, ptr)
        for name in ("Ellipse", "Rectangle"):
            bind(gdi, name, boolean, ptr, integer, integer, integer, integer)
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)

        def capture():
            check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
            count = gdi.GetPath(dc, None, None, 0)
            if count < 0:
                raise OSError("GetPath failed")
            points = (wintypes.POINT * count)()
            kinds = (ctypes.c_ubyte * count)()
            if gdi.GetPath(dc, points, kinds, count) != count:
                raise OSError("GetPath changed size")
            result = [(point.x, point.y, kind) for point, kind in zip(points, kinds, strict=True)]
            check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
            return result

        for width in (2, 3, 6, 12):
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for name in ("Ellipse", "Rectangle"):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(getattr(gdi, name)(dc, 24, 24, 96, 80), name)
                    check(gdi.EndPath(dc), "EndPath")
                    raw = capture()
                    check(gdi.WidenPath(dc), "WidenPath")
                    wide = capture()
                    print("SHAPE " + json.dumps([name, width, raw, wide]))
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dump-paths", action="store_true", help="Report raw native geometry instead of comparing pixels"
    )
    args = parser.parse_args()
    main(dump_paths=args.dump_paths)
    if args.dump_paths:
        probe_shapes()
