"""Inspect Windows GDI's native Arc path and direct raster output."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_cubics
from pillow_wmf.geometry import DevicePath
from pillow_wmf.stroke import cosmetic_line


def verify_fractional_wide_lines(gdi, dc, bits):
    """Exercise shared widening beyond the integer-only line matrix."""
    tested = failures = 0
    check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
    try:
        for width in (2, 3, 6, 7):
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for fx, fy in ((0, 0), (0, 1), (1, 0), (7, 9), (8, 8), (15, 15)):
                    for dx, dy in ((128, 32), (32, 128), (-128, 32), (128, -128)):
                        start = (512 + fx, 512 + fy)
                        end = (start[0] + dx, start[1] + dy)
                        check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                        check(gdi.BeginPath(dc), "BeginPath")
                        check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                        check(gdi.LineTo(dc, *end), "LineTo")
                        check(gdi.EndPath(dc), "EndPath")
                        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                        ctypes.memset(bits, 255, 128 * 128 * 4)
                        check(gdi.StrokePath(dc), "StrokePath")
                        check(gdi.GdiFlush(), "GdiFlush")
                        raw = ctypes.string_at(bits, 128 * 128 * 4)
                        native = {(i % 128, i // 128) for i, pixel in enumerate(raw[::4]) if pixel == 0}
                        context = RasterContext(128, 128)
                        context.select_object(context.create_pen(0, width, 0))
                        context._stroke_path(DevicePath.polyline((start, end)))
                        actual = {
                            (i % 128, i // 128)
                            for i, pixel in enumerate(context.image.convert("L").tobytes())
                            if pixel == 0
                        }
                        tested += 1
                        if native != actual:
                            failures += 1
                            print(
                                "fractional-wide-FAIL",
                                width,
                                start,
                                end,
                                "extra",
                                actual - native,
                                "missing",
                                native - actual,
                            )
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)
    finally:
        check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")
    print("fractional-wide-matrix", tested, "cases", failures, "failures")
    assert not failures


def path_points(gdi, dc):
    count = gdi.GetPath(dc, None, None, 0)
    points = (wintypes.POINT * count)()
    kinds = (ctypes.c_ubyte * count)()
    check(gdi.GetPath(dc, points, kinds, count) == count, "GetPath")
    return tuple((point.x, point.y, kind) for point, kind in zip(points, kinds, strict=True))


def fixed_path_points(gdi, dc):
    """Magnify the inverse mapping only after constructing the device path."""
    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
    try:
        return path_points(gdi, dc)
    finally:
        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")


def main():
    with reference_surface(128, 128) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "FlattenPath", "AbortPath", "StrokePath", "WidenPath", "GdiFlush"):
            bind(gdi, name, boolean, ptr) if name != "GdiFlush" else bind(gdi, name, boolean)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "Arc", boolean, ptr, *(integer for _ in range(8)))
        bind(gdi, "SetViewportExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
        bind(gdi, "SetGraphicsMode", integer, ptr, integer)
        bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
        bind(gdi, "LineTo", boolean, ptr, integer, integer)
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        for start, end in (
            ((736, 424), (710, 308)),
            ((432, 128), (424, 128)),
            ((427, 472), (395, 499)),
            ((395, 499), (384, 528)),
            ((1611, 158), (1464, 128)),
            ((1320, 157), (1198, 238)),
        ):
            check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
            check(gdi.LineTo(dc, *end), "LineTo")
            check(gdi.EndPath(dc), "EndPath")
            print("fractional-segment-path", start, end, path_points(gdi, dc))
            check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.StrokePath(dc), "StrokePath")
            check(gdi.GdiFlush(), "GdiFlush")
            raw = ctypes.string_at(bits, 128 * 128 * 4)
            print(
                "fractional-segment-pixels",
                start,
                end,
                [(i // 4 % 128, i // 4 // 128) for i in range(0, len(raw), 4) if raw[i] == 0],
            )
        check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")
        failures = 0
        tested = 0
        check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
        for fx in range(16):
            for fy in range(16):
                for dx, dy in ((64, 0), (64, 16), (64, 63), (64, 64), (64, 65), (16, 64), (0, 64), (-64, 64)):
                    for reverse in (False, True):
                        start = (512 + fx, 512 + fy)
                        end = (start[0] + dx, start[1] + dy)
                        if reverse:
                            start, end = end, start
                        check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                        check(gdi.BeginPath(dc), "BeginPath")
                        check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                        check(gdi.LineTo(dc, *end), "LineTo")
                        check(gdi.EndPath(dc), "EndPath")
                        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                        ctypes.memset(bits, 255, 128 * 128 * 4)
                        check(gdi.StrokePath(dc), "StrokePath")
                        check(gdi.GdiFlush(), "GdiFlush")
                        raw = ctypes.string_at(bits, 128 * 128 * 4)
                        native = {(i % 128, i // 128) for i, pixel in enumerate(raw[::4]) if pixel == 0}
                        actual = set(cosmetic_line(start, end, 128, 128))
                        tested += 1
                        if native != actual:
                            failures += 1
                            if failures <= 20:
                                print(
                                    "fractional-line-FAIL",
                                    start,
                                    end,
                                    "extra",
                                    actual - native,
                                    "missing",
                                    native - actual,
                                )
        print("fractional-line-matrix", tested, "cases", failures, "failures")
        assert not failures
        check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")
        cases = (
            (8, 8, 47, 47, 47, 27, 27, 8),
            (68, 8, 107, 47, 87, 8, 68, 27),
            (8, 68, 47, 107, 8, 87, 27, 106),
            (68, 68, 107, 107, 87, 106, 106, 87),
            (8, 8, 59, 43, 54, 13, 12, 38),
            (6, 70, 26, 92, 17, 81, 15, 82),
            (6, 70, 26, 92, 16, 80, 15, 81),
            (6, 70, 26, 92, 15, 81, 16, 82),
            (6, 70, 26, 92, 16, 82, 17, 81),
            (8, 8, 56, 56, 33, 32, 32, 31),
            (8, 8, 56, 56, 32, 31, 31, 32),
            (8, 8, 56, 56, 31, 32, 32, 33),
            (8, 8, 56, 56, 32, 33, 33, 32),
        )
        for case in cases:
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            print("arc-raw", case, path_points(gdi, dc))
            print("arc-fixed-controls", case, fixed_path_points(gdi, dc))
            cubics = arc_cubics(*case[:4], case[4:6], case[6:8])
            expected = (cubics[0][0], *(point for cubic in cubics for point in cubic[1:]))
            actual = tuple((x, y) for x, y, _ in fixed_path_points(gdi, dc))
            assert actual == expected, (case, actual, expected)
            check(gdi.FlattenPath(dc), "FlattenPath")
            print("arc-flat", case, path_points(gdi, dc))
            print("arc-fixed-flat", case, fixed_path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.GdiFlush(), "GdiFlush")
            direct = ctypes.string_at(bits, 128 * 128 * 4)
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.StrokePath(dc), "StrokePath")
            check(gdi.GdiFlush(), "GdiFlush")
            path = ctypes.string_at(bits, 128 * 128 * 4)
            difference = sum(direct[i : i + 3] != path[i : i + 3] for i in range(0, len(direct), 4))
            print("arc-direct-path-difference", case, difference)
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, *case), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.FlattenPath(dc), "FlattenPath")
            check(gdi.StrokePath(dc), "StrokePath")
            check(gdi.GdiFlush(), "GdiFlush")
            flattened = ctypes.string_at(bits, 128 * 128 * 4)
            difference = sum(direct[i : i + 3] != flattened[i : i + 3] for i in range(0, len(direct), 4))
            print("arc-direct-flattened-difference", case, difference)
        bind(gdi, "SetViewportOrgEx", boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
        for label, extent, origin in (
            ("reflect-x", (-128, 128), (64, 8)),
            ("reflect-y", (128, -128), (8, 64)),
            ("reflect-both", (-128, -128), (64, 64)),
        ):
            check(gdi.SetViewportExtEx(dc, *extent, None), "SetViewportExtEx")
            check(gdi.SetViewportOrgEx(dc, *origin, None), "SetViewportOrgEx")
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, 8, 8, 56, 56, 56, 32, 32, 8), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
            check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
            print("arc-reflected-raw", label, path_points(gdi, dc))
            print("arc-reflected-fixed-controls", label, fixed_path_points(gdi, dc))
            check(gdi.FlattenPath(dc), "FlattenPath")
            print("arc-reflected-flat", label, path_points(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
        check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
        check(gdi.SetViewportOrgEx(dc, 0, 0, None), "SetViewportOrgEx")
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "SelectObject", ptr, ptr, ptr)
        bind(gdi, "DeleteObject", boolean, ptr)
        bind(gdi, "GetStockObject", ptr, integer)
        verify_fractional_wide_lines(gdi, dc, bits)
        brush = check(gdi.SelectObject(dc, check(gdi.GetStockObject(4), "BLACK_BRUSH")), "SelectObject")
        pen = check(gdi.CreatePen(0, 3, 0), "CreatePen")
        previous = check(gdi.SelectObject(dc, pen), "SelectObject")
        try:
            bind(gdi, "FillPath", boolean, ptr)
            ctypes.memset(bits, 255, 128 * 128 * 4)
            check(gdi.Arc(dc, 68, 8, 116, 56, 136, 32, 68, 8), "Arc")
            check(gdi.GdiFlush(), "GdiFlush")
            direct = ctypes.string_at(bits, 128 * 128 * 4)
            for flatten in (False, True):
                for widen in (False, True):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Arc(dc, 68, 8, 116, 56, 136, 32, 68, 8), "Arc")
                    check(gdi.EndPath(dc), "EndPath")
                    if flatten:
                        check(gdi.FlattenPath(dc), "FlattenPath")
                    if widen:
                        check(gdi.WidenPath(dc), "WidenPath")
                        print("arc-wide-fixed-widened", flatten, fixed_path_points(gdi, dc))
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.FillPath(dc) if widen else gdi.StrokePath(dc), "FillPath/StrokePath")
                    check(gdi.GdiFlush(), "GdiFlush")
                    raw = ctypes.string_at(bits, 128 * 128 * 4)
                    print(
                        "arc-wide-difference",
                        flatten,
                        widen,
                        [
                            (i // 4 % 128, i // 4 // 128, direct[i], raw[i])
                            for i in range(0, len(raw), 4)
                            if direct[i : i + 3] != raw[i : i + 3]
                        ],
                    )
            bind(gdi, "PolyBezier", boolean, ptr, ctypes.POINTER(wintypes.POINT), wintypes.DWORD)
            for control in (
                ((80, 32), (80, 8), (56, 8), (32, 8)),
                ((80, 32), (80, 32), (56, 8), (32, 8)),
                ((32, 8), (56, 8), (80, 8), (80, 32)),
                ((16, 16), (48, 48), (16, 48), (48, 16)),
            ):
                for flatten in (False, True):
                    check(gdi.BeginPath(dc), "BeginPath")
                    points = (wintypes.POINT * 4)(*(wintypes.POINT(*point) for point in control))
                    check(gdi.PolyBezier(dc, points, 4), "PolyBezier")
                    check(gdi.EndPath(dc), "EndPath")
                    if flatten:
                        check(gdi.FlattenPath(dc), "FlattenPath")
                        print("cubic-fixed-flat", control, fixed_path_points(gdi, dc))
                    check(gdi.WidenPath(dc), "WidenPath")
                    print("cubic-fixed-widened", control, flatten, fixed_path_points(gdi, dc))
                    check(gdi.AbortPath(dc), "AbortPath")
            check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
            for control in (
                ((1280, 512), (1280, 128), (896, 128), (512, 128)),
                ((1280, 520), (1280, 136), (896, 136), (512, 136)),
                ((1280, 512), (1280, 136), (896, 128), (512, 128)),
                ((1840, 504), (1840, 296), (1672, 128), (1464, 128)),
                ((256, 256), (768, 768), (768, 256), (1024, 256)),
                ((512, 512), (516, 512), (512, 516), (516, 516)),
            ):
                check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                check(gdi.BeginPath(dc), "BeginPath")
                points = (wintypes.POINT * 4)(*(wintypes.POINT(*point) for point in control))
                check(gdi.PolyBezier(dc, points, 4), "PolyBezier")
                check(gdi.EndPath(dc), "EndPath")
                print("fractional-cubic-input", path_points(gdi, dc))
                check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                check(gdi.WidenPath(dc), "WidenPath")
                print("fractional-cubic-widened", control, fixed_path_points(gdi, dc))
                check(gdi.AbortPath(dc), "AbortPath")
            cap_groups = {}
            for fx in range(16):
                for fy in range(16):
                    start = (512 + fx, 512 + fy)
                    end = (start[0] + 128, start[1] + 32)
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                    check(gdi.LineTo(dc, *end), "LineTo")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    check(gdi.WidenPath(dc), "WidenPath")
                    cap = tuple((x - start[0], y - start[1]) for x, y, _ in fixed_path_points(gdi, dc)[:5])
                    cap_groups.setdefault(cap, []).append((fx, fy))
                    check(gdi.AbortPath(dc), "AbortPath")
            for cap, phases in cap_groups.items():
                print("fractional-cap-group", cap, phases)
            check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")
            bind(gdi, "Ellipse", boolean, ptr, integer, integer, integer, integer)
            bind(gdi, "StrokeAndFillPath", boolean, ptr)
            for brush_kind in (5, 0):
                check(gdi.SelectObject(dc, check(gdi.GetStockObject(brush_kind), "GetStockObject")), "SelectObject")
                ctypes.memset(bits, 255, 128 * 128 * 4)
                check(gdi.Ellipse(dc, 24, 24, 96, 80), "Ellipse")
                check(gdi.GdiFlush(), "GdiFlush")
                direct = ctypes.string_at(bits, 128 * 128 * 4)
                for flatten in (False, True):
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.Ellipse(dc, 24, 24, 96, 80), "Ellipse")
                    check(gdi.EndPath(dc), "EndPath")
                    if flatten:
                        check(gdi.FlattenPath(dc), "FlattenPath")
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.StrokeAndFillPath(dc), "StrokeAndFillPath")
                    check(gdi.GdiFlush(), "GdiFlush")
                    raw = ctypes.string_at(bits, 128 * 128 * 4)
                    print(
                        "ellipse-wide-difference",
                        brush_kind,
                        flatten,
                        [
                            (i // 4 % 128, i // 4 // 128, direct[i], raw[i])
                            for i in range(0, len(raw), 4)
                            if direct[i : i + 3] != raw[i : i + 3]
                        ],
                    )
        finally:
            gdi.SelectObject(dc, previous)
            gdi.DeleteObject(pen)
            gdi.SelectObject(dc, brush)


if __name__ == "__main__":
    main()
