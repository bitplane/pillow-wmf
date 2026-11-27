"""Print the pixels native ArcTo and AngleArc draw in each graphics mode.

Each case draws on a fresh 96x96 reference surface: a one-pixel black pen
moves to a start point, draws one ArcTo, AngleArc, Arc, Chord or Pie
(whose interiors the default white brush leaves white), then a line to a fixed
point, so the arc's figure and the current position it leaves both show.
Cases cover GM_COMPATIBLE and GM_ADVANCED under a 1:1, an enlarging and a
reducing page mapping. No reference images are written.

    case mode=... mapping=... call=...
    row y first ###..#
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 96
MAPPINGS = {"unit": (96, 96), "enlarged": (64, 48), "reduced": (128, 120)}
CALLS = {
    "arc-to-ccw": ("arc_to", 1, (10, 10, 41, 31, 41, 10, 10, 31)),
    "arc-to-cw": ("arc_to", 2, (10, 10, 41, 31, 41, 10, 10, 31)),
    "arc-to-narrow": ("arc_to", 1, (50, 8, 63, 40, 63, 20, 50, 8)),
    "arc-to-odd": ("arc_to", 2, (12, 40, 37, 59, 12, 50, 37, 41)),
    "angle-arc": ("angle_arc", 1, (60, 60, 15, 30.0, 200.0)),
    "angle-arc-back": ("angle_arc", 1, (30, 70, 9, 100.0, -150.0)),
    "arc-cw": ("arc", 2, (10, 10, 41, 31, 41, 10, 10, 31)),
    "chord-cw": ("chord", 2, (12, 40, 37, 59, 12, 50, 37, 41)),
    "pie-cw": ("pie", 2, (50, 8, 63, 40, 63, 20, 50, 8)),
    "chord-ccw": ("chord", 1, (12, 40, 37, 59, 12, 50, 37, 41)),
    "pie-ccw": ("pie", 1, (50, 8, 63, 40, 63, 20, 50, 8)),
}


def main():
    print(f"Windows compatible-mode arc probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for mapping, window in MAPPINGS.items():
        for mode in (1, 2):
            for name, (call, direction, arguments) in CALLS.items():
                with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
                    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
                    bind(gdi, "SetWindowExtEx", boolean, ptr, integer, integer, ptr)
                    bind(gdi, "SetGraphicsMode", integer, ptr, integer)
                    bind(gdi, "SetArcDirection", integer, ptr, integer)
                    bind(gdi, "MoveToEx", boolean, ptr, integer, integer, ptr)
                    bind(gdi, "LineTo", boolean, ptr, integer, integer)
                    for function in ("ArcTo", "Arc", "Chord", "Pie"):
                        bind(gdi, function, boolean, ptr, *(integer,) * 8)
                    bind(
                        gdi, "AngleArc", boolean, ptr, integer, integer, wintypes.DWORD, ctypes.c_float, ctypes.c_float
                    )
                    check(gdi.SetWindowExtEx(dc, *window, None), "SetWindowExtEx")
                    check(gdi.SetGraphicsMode(dc, mode), "SetGraphicsMode")
                    check(gdi.SetArcDirection(dc, direction), "SetArcDirection")
                    check(gdi.MoveToEx(dc, 5, 90, None), "MoveToEx")
                    functions = {"arc_to": gdi.ArcTo, "arc": gdi.Arc, "chord": gdi.Chord, "pie": gdi.Pie}
                    drawn = functions.get(call, gdi.AngleArc)(dc, *arguments)
                    check(gdi.LineTo(dc, 90, 90), "LineTo")
                    pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
                    print(f"case mode={mode} mapping={mapping} call={name} drawn={drawn}")
                    for y in range(SIZE):
                        row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                        if any(row):
                            first = row.index(True)
                            last = SIZE - 1 - row[::-1].index(True)
                            print(f"row {y} {first} " + "".join("#" if v else "." for v in row[first : last + 1]))


if __name__ == "__main__":
    main()
