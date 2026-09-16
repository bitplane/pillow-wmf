"""Inspect GDI path geometry for the raster cases that still differ."""

import ctypes
from ctypes import wintypes
from pathlib import Path

from PIL import Image
from windows_wmf_render import bind, check, reference_surface


def path_points(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    if count < 0:
        raise OSError(ctypes.get_last_error(), "GetPath size failed")
    points = (wintypes.POINT * count)()
    kinds = (ctypes.c_ubyte * count)()
    if gdi.GetPath(dc, points, kinds, count) != count:
        raise OSError(ctypes.get_last_error(), "GetPath data failed")
    return tuple((point.x, point.y, kind) for point, kind in zip(points, kinds, strict=True))


def main():
    with reference_surface(128, 128) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "FlattenPath", "WidenPath", "AbortPath", "StrokeAndFillPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "Ellipse", boolean, ptr, integer, integer, integer, integer)
        bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
        bind(gdi, "LineTo", boolean, ptr, integer, integer)
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "CreateSolidBrush", ptr, wintypes.DWORD)
        bind(gdi, "FillPath", boolean, ptr)
        bind(gdi, "PathToRegion", ptr, ptr)
        bind(gdi, "SelectObject", ptr, ptr, ptr)
        bind(gdi, "DeleteObject", boolean, ptr)
        bind(gdi, "SetViewportExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        bind(gdi, "GdiFlush", boolean)
        bind(gdi, "Polyline", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
        bind(gdi, "CreatePolygonRgn", ptr, ctypes.POINTER(wintypes.POINT), integer, integer)
        bind(
            gdi,
            "CreatePolyPolygonRgn",
            ptr,
            ctypes.POINTER(wintypes.POINT),
            ctypes.POINTER(integer),
            integer,
            integer,
        )
        bind(gdi, "PtInRegion", boolean, ptr, integer, integer)
        for name, box in (
            ("even", (24, 24, 56, 56)),
            ("odd", (24, 24, 57, 57)),
            ("wide", (24, 24, 94, 43)),
            ("tall", (24, 24, 43, 94)),
            ("two-wide", (24, 24, 26, 49)),
            ("overlap", (48, 40, 116, 108)),
        ):
            pen = check(gdi.CreatePen(0, 0 if name == "overlap" else 1, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Ellipse(dc, *box), "Ellipse")
            check(gdi.EndPath(dc), "EndPath")
            print(f"ellipse-{name}-raw: {path_points(gdi, dc)}")
            check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
            print(f"ellipse-{name}-raw-expanded: {path_points(gdi, dc)}")
            check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
            check(gdi.FlattenPath(dc), "FlattenPath")
            points = path_points(gdi, dc)
            print(f"ellipse-{name}: {len(points)} vertices {points}")
            check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
            print(f"ellipse-{name}-flat-expanded: {path_points(gdi, dc)}")
            check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
            check(gdi.AbortPath(dc), "AbortPath")

            def raster(*, path=False, flatten=False, polyline=False, box=box, points=points):
                ctypes.memset(bits, 255, 128 * 128 * 4)
                if polyline:
                    vertices = (wintypes.POINT * len(points))(*(wintypes.POINT(x, y) for x, y, _ in points))
                    check(gdi.Polyline(dc, vertices, len(vertices)), "Polyline")
                elif path:
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Ellipse(dc, *box), "Ellipse")
                    check(gdi.EndPath(dc), "EndPath")
                    if flatten:
                        check(gdi.FlattenPath(dc), "FlattenPath")
                    check(gdi.StrokeAndFillPath(dc), "StrokeAndFillPath")
                else:
                    check(gdi.Ellipse(dc, *box), "Ellipse")
                check(gdi.GdiFlush(), "GdiFlush")
                return ctypes.string_at(bits, 128 * 128 * 4)

            direct = raster()
            if name != "overlap":
                reference_path = (
                    Path(__file__).resolve().parents[1]
                    / "test"
                    / "compatibility"
                    / "wmf"
                    / f"drawing-ellipse-{name}.png"
                )
                with Image.open(reference_path) as reference:
                    direct_rgb = Image.frombytes("RGB", (128, 128), direct, "raw", "BGRX")
                    black_difference = sum(
                        (left == (0, 0, 0)) != (right == (0, 0, 0))
                        for left, right in zip(
                            direct_rgb.get_flattened_data(), reference.get_flattened_data(), strict=True
                        )
                    )
                print(f"ellipse-{name}-reference-black-difference: {black_difference}")
            for variant, image in (
                ("path", raster(path=True)),
                ("flat", raster(path=True, flatten=True)),
                ("polyline", raster(polyline=True)),
            ):
                different = sum(
                    direct[index : index + 3] != image[index : index + 3] for index in range(0, len(direct), 4)
                )
                print(f"ellipse-{name}-{variant}-raster-difference: {different}")

            if name in ("even", "odd", "wide", "tall", "two-wide"):
                check(gdi.BeginPath(dc), "BeginPath")
                check(gdi.Ellipse(dc, *box), "Ellipse")
                check(gdi.EndPath(dc), "EndPath")
                if gdi.WidenPath(dc):
                    widened = path_points(gdi, dc)
                    print(f"ellipse-{name}-widened: {len(widened)} vertices {widened}")
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    expanded = path_points(gdi, dc)
                    print(f"ellipse-{name}-widened-expanded: {len(expanded)} vertices {expanded}")
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    starts = [index for index, (_, _, kind) in enumerate(widened) if kind == 6]
                    counts = [end - start for start, end in zip(starts, starts[1:] + [len(widened)])]
                    vertices = (wintypes.POINT * len(widened))(*(wintypes.POINT(x, y) for x, y, _ in widened))
                    lengths = (integer * len(counts))(*counts)
                    region = check(gdi.CreatePolyPolygonRgn(vertices, lengths, len(counts), 1), "CreatePolyPolygonRgn")
                    try:
                        difference = sum(
                            (direct[(y * 128 + x) * 4 : (y * 128 + x) * 4 + 3] == b"\0\0\0")
                            != bool(gdi.PtInRegion(region, x, y))
                            for y in range(128)
                            for x in range(128)
                        )
                        print(f"ellipse-{name}-widened-region-black-difference: {difference}")
                    finally:
                        gdi.DeleteObject(region)
                else:
                    print(f"ellipse-{name}-widened: failed with {ctypes.get_last_error()}")
                check(gdi.AbortPath(dc), "AbortPath")

                check(gdi.BeginPath(dc), "BeginPath")
                check(gdi.Ellipse(dc, *box), "Ellipse")
                check(gdi.EndPath(dc), "EndPath")
                check(gdi.WidenPath(dc), "WidenPath")
                region = check(gdi.PathToRegion(dc), "PathToRegion")
                try:
                    difference = sum(
                        (direct[(y * 128 + x) * 4 : (y * 128 + x) * 4 + 3] == b"\0\0\0")
                        != bool(gdi.PtInRegion(region, x, y))
                        for y in range(128)
                        for x in range(128)
                    )
                    print(f"ellipse-{name}-path-region-black-difference: {difference}")
                finally:
                    gdi.DeleteObject(region)

                brush = check(gdi.CreateSolidBrush(0), "CreateSolidBrush")
                previous_brush = check(gdi.SelectObject(dc, brush), "SelectObject")
                ctypes.memset(bits, 255, 128 * 128 * 4)
                check(gdi.BeginPath(dc), "BeginPath")
                check(gdi.Ellipse(dc, *box), "Ellipse")
                check(gdi.EndPath(dc), "EndPath")
                check(gdi.WidenPath(dc), "WidenPath")
                check(gdi.FillPath(dc), "FillPath")
                check(gdi.GdiFlush(), "GdiFlush")
                filled = ctypes.string_at(bits, 128 * 128 * 4)
                black_difference = sum(
                    (direct[index : index + 3] == b"\0\0\0") != (filled[index : index + 3] == b"\0\0\0")
                    for index in range(0, len(direct), 4)
                )
                print(f"ellipse-{name}-widened-fill-black-difference: {black_difference}")
                gdi.SelectObject(dc, previous_brush)
                gdi.DeleteObject(brush)
            gdi.SelectObject(dc, previous)
            gdi.DeleteObject(pen)

        for width, scale_x, scale_y in ((1, 2, 1), (3, 1, 1), (3, 2, 1), (3, 1, 2)):
            check(gdi.SetViewportExtEx(dc, 128 * scale_x, 128 * scale_y, None), "SetViewportExtEx")
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for segment_name, start, end in (
                    ("horizontal", (8, 8), (48, 8)),
                    ("vertical", (48, 8), (48, 48)),
                    ("diagonal", (8, 16), (40, 40)),
                ):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                    check(gdi.LineTo(dc, *end), "LineTo")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.WidenPath(dc), "WidenPath")
                    points = path_points(gdi, dc)
                    print(f"pen-{width}-{scale_x}x{scale_y}-{segment_name}: {len(points)} vertices {points}")
                    check(gdi.AbortPath(dc), "AbortPath")
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)

        for name, points in (
            ("rectangle", ((16, 16), (24, 16), (24, 24), (16, 24))),
            ("diamond", ((20, 16), (24, 20), (20, 24), (16, 20))),
            ("shallow", ((16, 16), (30, 18), (30, 24), (16, 24))),
            ("vertex", ((16, 17), (23, 16), (30, 17), (30, 24), (16, 24))),
        ):
            vertices = (wintypes.POINT * len(points))(*(wintypes.POINT(x, y) for x, y in points))
            region = check(gdi.CreatePolygonRgn(vertices, len(vertices), 1), "CreatePolygonRgn")
            try:
                for y in range(14, 26):
                    xs = [x for x in range(14, 32) if gdi.PtInRegion(region, x, y)]
                    if xs:
                        print(f"region-{name}-row-{y}: {xs}")
            finally:
                gdi.DeleteObject(region)


if __name__ == "__main__":
    main()
