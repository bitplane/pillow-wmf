"""Targeted native regressions for pen-support ties and shallow Arc sweeps."""

import ctypes
from ctypes import wintypes
from itertools import product

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import RasterContext
from pillow_wmf.ellipse import arc_cubics
from pillow_wmf.geometry import DevicePath, StrokeSegment
from pillow_wmf.stroke import realize_pen, widen_segment


def fixed_path(gdi, dc):
    """Read existing device geometry in sixteenths without changing its construction."""
    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
    try:
        count = gdi.GetPath(dc, None, None, 0)
        check(count >= 0, "GetPath count")
        points, kinds = (wintypes.POINT * count)(), (ctypes.c_ubyte * count)()
        check(gdi.GetPath(dc, points, kinds, count) == count, "GetPath")
        return tuple((point.x, point.y, kind) for point, kind in zip(points, kinds, strict=True))
    finally:
        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")


def verify_native_clipped_dash_pairs():
    """Validate the crop hypothesis against native Polyline, not our renderer."""
    tested = 0
    for style, background, transpose, reverse in product((1, 2, 3, 4), (1, 2), (False, True), (False, True)):
        points = ((0, -20), (10, -10), (30, 10), (40, 20), (20, 40), (10, 20))
        if transpose:
            points = tuple((y, x) for x, y in points)
        if reverse:
            points = points[::-1]
        results = []
        for size, offset in ((32, 0), (96, 32)):
            with reference_surface(size, size) as (gdi, dc, bits):
                ptr, integer = ctypes.c_void_p, ctypes.c_int
                bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
                bind(gdi, "Polyline", wintypes.BOOL, ptr, ctypes.POINTER(wintypes.POINT), integer)
                bind(gdi, "SetBkMode", integer, ptr, integer)
                bind(gdi, "SetBkColor", wintypes.DWORD, ptr, wintypes.DWORD)
                bind(gdi, "GdiFlush", wintypes.BOOL)
                pen = check(gdi.CreatePen(style, 1, 0), "CreatePen")
                previous = check(gdi.SelectObject(dc, pen), "SelectObject")
                try:
                    check(gdi.SetBkMode(dc, background), "SetBkMode")
                    gdi.SetBkColor(dc, 0x0000FF)
                    native_points = (wintypes.POINT * len(points))(
                        *(wintypes.POINT(x + offset, y + offset) for x, y in points)
                    )
                    check(gdi.Polyline(dc, native_points, len(points)), "Polyline")
                    check(gdi.GdiFlush(), "GdiFlush")
                    raw = ctypes.string_at(bits, size * size * 4)
                    results.append(
                        bytes(
                            raw[((y + offset) * size + x + offset) * 4 + channel]
                            for y in range(32)
                            for x in range(32)
                            for channel in range(3)
                        )
                    )
                finally:
                    gdi.SelectObject(dc, previous)
                    gdi.DeleteObject(pen)
            context = RasterContext(size, size)
            context.select_object(context.create_pen(style, 1, 0))
            context.set_background_mode(background)
            context.set_background_color(0x0000FF)
            context.polyline(tuple((x + offset, y + offset) for x, y in points))
            actual = context.image.crop((offset, offset, offset + 32, offset + 32)).tobytes("raw", "BGR")
            assert actual == results[-1], (
                "native styled clipping mismatch",
                style,
                background,
                transpose,
                reverse,
                size,
            )
        assert results[0] == results[1], ("native crop hypothesis disproved", style, background, transpose, reverse)
        tested += 1
    print("native-clipped-dash-pairs", tested, "exact matches")


def main():
    verify_native_clipped_dash_pairs()
    failures = tested = 0
    with reference_surface(128, 128) as (gdi, dc, bits):
        ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
        for name in ("BeginPath", "EndPath", "StrokePath", "WidenPath", "AbortPath", "FlattenPath"):
            bind(gdi, name, boolean, ptr)
        bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer)
        bind(gdi, "SetGraphicsMode", integer, ptr, integer)
        bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
        bind(gdi, "LineTo", boolean, ptr, integer, integer)
        bind(gdi, "Arc", boolean, ptr, *(integer for _ in range(8)))
        bind(gdi, "AngleArc", boolean, ptr, integer, integer, wintypes.DWORD, ctypes.c_float, ctypes.c_float)
        bind(gdi, "CreatePen", ptr, integer, integer, wintypes.DWORD)
        bind(gdi, "GdiFlush", boolean)

        # Large path-only geometry exposes the arithmetic before 28.4
        # quantization hides it. No large bitmap or pixel enumeration is used.
        for start, end in (((3, -1), (3, 0)), ((-3, 1), (-3, 2)), ((-3, 0), (-3, 1)), ((-2, -16300), (-2, -16299))):
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.Arc(dc, -1000000, -1000000, 1000000, 1000000, *start, *end), "Arc")
            check(gdi.EndPath(dc), "EndPath")
            print("large-arc", start, end, fixed_path(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")
        angle_cases = ((90, 0), (180, 18.4349488), (198.4349488, 15.2551187), (90, 0.01), (90, 0.00001))
        angle_cases += tuple(
            (0, sweep)
            for sweep in (0.01, 1, 2, 2.8125, 5.625, 10, 11.25, 15, 18.4349488, 20, 22.5, 30, 33.75, 45, 60, 67.5, 90)
        )
        angle_cases += tuple((0, sweep) for sweep in (3, 4, 5, 6, 7, 8))
        angle_cases += tuple((angle, sweep) for angle in (10, 18.4349488, 90) for sweep in (0.1, 1, 3, 10))
        angle_cases += tuple((10, sweep) for sweep in (1.9999, 2.0001, 2.8, 2.81249, 2.8125, 2.81251, 2.9))
        angle_cases += tuple((10, sweep) for sweep in (2.9999, 3, 3.0001))
        for angle, sweep in angle_cases:
            check(gdi.BeginPath(dc), "BeginPath")
            check(gdi.MoveToEx(dc, 0, 0, None), "MoveToEx")
            check(gdi.AngleArc(dc, 0, 0, 1000000, angle, sweep), "AngleArc")
            check(gdi.EndPath(dc), "EndPath")
            print("large-angle-arc", angle, sweep, fixed_path(gdi, dc))
            check(gdi.AbortPath(dc), "AbortPath")

        def compare(label, context):
            nonlocal failures, tested
            check(gdi.GdiFlush(), "GdiFlush")
            raw = ctypes.string_at(bits, 128 * 128 * 4)
            actual = context.image.convert("L").tobytes()
            differences = [
                (i % 128, i // 128, expected, observed)
                for i, (expected, observed) in enumerate(zip(raw[::4], actual, strict=True))
                if expected != observed
            ]
            tested += 1
            if differences:
                failures += 1
                if failures <= 30:
                    print("FAIL", label, len(differences), differences[:16])

        for width in (2, 3, 4, 6, 7, 8, 9, 12, 17):
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                vertices = realize_pen(width).vertices
                edges = {(b[0] - a[0], b[1] - a[1]) for a, b in zip(vertices, vertices[1:] + vertices[:1])}
                check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
                for (dx, dy), epsilon, phase in product(sorted(edges), (-1, 0, 1), ((0, 0), (1, 7), (8, 8))):
                    delta = (dx * 8 + ((dy > 0) - (dy < 0)) * epsilon, dy * 8 - ((dx > 0) - (dx < 0)) * epsilon)
                    start = (1024 + phase[0], 1024 + phase[1])
                    end = (start[0] + delta[0], start[1] + delta[1])
                    check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                    check(gdi.BeginPath(dc), "BeginPath")
                    check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                    check(gdi.LineTo(dc, *end), "LineTo")
                    check(gdi.EndPath(dc), "EndPath")
                    check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    if epsilon == 0 and phase == (0, 0):
                        check(gdi.WidenPath(dc), "WidenPath")
                        print("tie-outline", width, delta, "native", fixed_path(gdi, dc))
                        print(
                            "tie-outline",
                            width,
                            delta,
                            "local",
                            widen_segment(StrokeSegment.line(start, end), realize_pen(width)),
                        )
                        check(gdi.AbortPath(dc), "AbortPath")
                        check(gdi.SetWindowExtEx(dc, 2048, 2048, None), "SetWindowExtEx")
                        check(gdi.BeginPath(dc), "BeginPath")
                        check(gdi.MoveToEx(dc, *start, None), "MoveToEx")
                        check(gdi.LineTo(dc, *end), "LineTo")
                        check(gdi.EndPath(dc), "EndPath")
                        check(gdi.SetWindowExtEx(dc, 128, 128, None), "SetWindowExtEx")
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.StrokePath(dc), "StrokePath")
                    context = RasterContext(128, 128)
                    context.select_object(context.create_pen(0, width, 0))
                    context._stroke_path(DevicePath.polyline((start, end)))
                    compare(("pen-tie", width, start, end), context)
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)
        print("pen-ties", tested, "cases", failures, "failures")
        pen_failures, pen_tested = failures, tested
        check(gdi.SetGraphicsMode(dc, 1), "SetGraphicsMode")
        for width in (1, 3, 7):
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for box, distance, offset, quadrant in product(
                    ((8, 8, 120, 120), (8, 16, 120, 112)), (3, 31, 16300), (-2, -1, 0, 1, 2), range(4)
                ):
                    radial = (distance, offset)
                    for _ in range(quadrant):
                        radial = (-radial[1], radial[0])
                    start = (64 + radial[0], 64 + radial[1])
                    end = (64 + radial[0], 64 + radial[1] + 1)
                    if width == 1:
                        check(gdi.BeginPath(dc), "BeginPath")
                        check(gdi.Arc(dc, *box, *start, *end), "Arc")
                        check(gdi.EndPath(dc), "EndPath")
                        print("arc-controls", box, start, end, "native", fixed_path(gdi, dc))
                        print("arc-controls", box, start, end, "local", arc_cubics(*box, start, end))
                        check(gdi.FlattenPath(dc), "FlattenPath")
                        print("arc-flat", start, end, "native", fixed_path(gdi, dc))
                        check(gdi.AbortPath(dc), "AbortPath")
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.Arc(dc, *box, *start, *end), "Arc")
                    context = RasterContext(128, 128)
                    context.select_object(context.create_pen(0, width, 0))
                    context.arc(*box, *start, *end)
                    compare(("arc", width, box, start, end), context)
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)
        print("arc-precision", tested - pen_tested, "cases", failures - pen_failures, "failures")
        holdout_tested, holdout_failures = tested, failures
        # New inputs, not used to reconstruct the algorithm: either side of
        # the short-angle boundary, both sweep directions and all quadrants.
        for width in (1, 7):
            pen = check(gdi.CreatePen(0, width, 0), "CreatePen")
            previous = check(gdi.SelectObject(dc, pen), "SelectObject")
            try:
                for box, offset, quadrant, reverse in product(
                    ((8, 8, 120, 120), (8, 16, 120, 112)), (625, 630), range(4), (False, True)
                ):
                    radials = [(12000, 0), (12000, offset)]
                    for _ in range(quadrant):
                        radials = [(-y, x) for x, y in radials]
                    start, end = ((64 + x, 64 + y) for x, y in radials[:: -1 if reverse else 1])
                    ctypes.memset(bits, 255, 128 * 128 * 4)
                    check(gdi.Arc(dc, *box, *start, *end), "Arc")
                    context = RasterContext(128, 128)
                    context.select_object(context.create_pen(0, width, 0))
                    context.arc(*box, *start, *end)
                    compare(("arc-holdout", width, box, start, end), context)
            finally:
                gdi.SelectObject(dc, previous)
                gdi.DeleteObject(pen)
        print("arc-holdout", tested - holdout_tested, "cases", failures - holdout_failures, "failures")
    assert not failures, f"{failures}/{tested} native edge cases failed"


if __name__ == "__main__":
    main()
