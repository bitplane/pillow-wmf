"""Native drawing with device coordinates near and beyond the 28.4 range.

Each case draws on a white 32x32 surface with the black stock brush and pen
and prints the call's result and the pixels it changed, so the native limit
on device coordinates, and what a call does when it is crossed, can be
modelled exactly:

    case NAME mode=COMPATIBLE|ADVANCED result=R changed=N
    row Y X0 MASK                 (one per changed row; # marks a changed pixel)
"""

import ctypes
import platform
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, reference_surface

OUTPUT = Path("coordinate-limits")
SIZE = 32
LIMIT = 2**27
EDGES = (LIMIT - 2, LIMIT - 1, LIMIT, LIMIT + 1, 2**28, 2**31 - 1)


def points(*values):
    return (wintypes.POINT * len(values))(*(wintypes.POINT(x, y) for x, y in values))


def cases():
    for edge in EDGES:
        yield f"rectangle-right-{edge}", "COMPATIBLE", ("Rectangle", 4, 4, edge, 12)
        yield f"rectangle-left-{edge}", "COMPATIBLE", ("Rectangle", -edge, 4, 20, 12)
        yield f"rectangle-bottom-{edge}", "COMPATIBLE", ("Rectangle", 4, 4, 12, edge)
        yield f"ellipse-right-{edge}", "COMPATIBLE", ("Ellipse", 4, 4, edge, 12)
        yield f"polyline-{edge}", "COMPATIBLE", ("Polyline", (4, 20), (edge, 20))
        yield f"polyline-negative-{edge}", "COMPATIBLE", ("Polyline", (-edge, 20), (20, 24))
        yield f"lineto-{edge}", "COMPATIBLE", ("LineTo", (4, 28), (edge, 28))
        yield f"polygon-{edge}", "COMPATIBLE", ("Polygon", (4, 4), (edge, 8), (4, 28))
        yield f"patblt-{edge}", "COMPATIBLE", ("PatBlt", 4, 4, edge, 8)
        yield f"advanced-rectangle-right-{edge}", "ADVANCED", ("Rectangle", 4, 4, edge, 12)
        yield f"advanced-polyline-{edge}", "ADVANCED", ("Polyline", (4, 20), (edge, 20))
        yield f"advanced-polygon-{edge}", "ADVANCED", ("Polygon", (4, 4), (edge, 8), (4, 28))
    # Polylines whose 28.4 points wrap to just left or right of the start.
    wraps = {
        "wrap-2147483646": ((4, 20), (2**31 - 2, 20)),
        "wrap-268435455": ((4, 20), (2**28 - 1, 20)),
        "wrap-268435457": ((4, 20), (2**28 + 1, 20)),
        "wrap-reversed-2147483647": ((2**31 - 1, 20), (4, 20)),
        "wrap-slanted-2147483647": ((4, 20), (2**31 - 1, 24)),
        "wrap-turning-2147483647": ((4, 20), (2**31 - 1, 20), (10, 26)),
        "wrap-vertical-2147483647": ((20, 4), (20, 2**31 - 1)),
        "wrap-vertical-268435456": ((20, 4), (20, 2**28)),
    }
    for name, line in wraps.items():
        yield f"polyline-{name}", "COMPATIBLE", ("Polyline", *line)
    # Page scales reaching the limit from small logical coordinates.
    for viewport in (2**22, 2**23 + 1, 2**24, 1073840127):
        yield f"scaled-rectangle-{viewport}", ("SCALED", viewport), ("Rectangle", 0, 0, 10, 10)
        yield f"scaled-ellipse-{viewport}", ("SCALED", viewport), ("Ellipse", 0, 0, 10, 10)
        yield f"scaled-polyline-{viewport}", ("SCALED", viewport), ("Polyline", (0, 0), (10, 0))


def main():
    print(f"Windows coordinate limit probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    OUTPUT.mkdir(exist_ok=True)
    for name, mode, (function, *arguments) in cases():
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            ptr, integer = ctypes.c_void_p, ctypes.c_int
            bind(gdi, "GetStockObject", ptr, integer)
            bind(gdi, "SetGraphicsMode", integer, ptr, integer)
            bind(gdi, "SetWindowExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
            bind(gdi, "SetViewportExtEx", wintypes.BOOL, ptr, integer, integer, ptr)
            bind(gdi, "Rectangle", wintypes.BOOL, ptr, integer, integer, integer, integer)
            bind(gdi, "Ellipse", wintypes.BOOL, ptr, integer, integer, integer, integer)
            bind(gdi, "PatBlt", wintypes.BOOL, ptr, integer, integer, integer, integer, wintypes.DWORD)
            bind(gdi, "Polyline", wintypes.BOOL, ptr, ctypes.POINTER(wintypes.POINT), integer)
            bind(gdi, "Polygon", wintypes.BOOL, ptr, ctypes.POINTER(wintypes.POINT), integer)
            bind(gdi, "MoveToEx", wintypes.BOOL, ptr, integer, integer, ptr)
            bind(gdi, "LineTo", wintypes.BOOL, ptr, integer, integer)
            bind(gdi, "GdiFlush", wintypes.BOOL)
            gdi.SelectObject(dc, check(gdi.GetStockObject(4), "GetStockObject"))  # BLACK_BRUSH
            if mode == "ADVANCED":
                check(gdi.SetGraphicsMode(dc, 2), "SetGraphicsMode")
            elif isinstance(mode, tuple):
                check(gdi.SetWindowExtEx(dc, 1, 1, None), "SetWindowExtEx")
                check(gdi.SetViewportExtEx(dc, mode[1], mode[1], None), "SetViewportExtEx")
            if function in ("Rectangle", "Ellipse"):
                result = getattr(gdi, function)(dc, *arguments)
            elif function == "PatBlt":
                result = gdi.PatBlt(dc, *arguments, 0x00F00021)
            elif function == "LineTo":
                (x0, y0), (x1, y1) = arguments
                gdi.MoveToEx(dc, x0, y0, None)
                result = gdi.LineTo(dc, x1, y1)
            else:
                result = getattr(gdi, function)(dc, points(*arguments), len(arguments))
            gdi.GdiFlush()
            data = ctypes.string_at(bits, SIZE * SIZE * 4)
        label = mode if isinstance(mode, str) else f"SCALED-{mode[1]}"
        changed = [
            (y, x)
            for y in range(SIZE)
            for x in range(SIZE)
            if data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 3] != b"\xff\xff\xff"
        ]
        print(f"case {name} mode={label} result={result} changed={len(changed)}")
        for y in sorted({y for y, _ in changed}):
            xs = [x for row, x in changed if row == y]
            print(
                f"row {y} {min(xs)} "
                + "".join("#" if (y, x) in set(changed) else "." for x in range(min(xs), max(xs) + 1))
            )


if __name__ == "__main__":
    main()
