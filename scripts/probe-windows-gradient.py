"""Print the pixels native GradientFill writes for rectangles and triangles.

Each case fills one mesh on a fresh 64x64 32-bit DIB at the identity mapping
and prints every changed row as ``y x0 hex...``: the first changed column and
the RGB of each pixel through the last changed column, ``-`` for unchanged
pixels between. Triangles cover every edge orientation, exact-hit slopes and
vertical and horizontal edges; rectangles cover swapped corners. No reference
images are written.

    case name mode vertices=... meshes=...
"""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

SIZE = 64
SENTINEL = b"\xff\xff\xff\xff"


class TriVertex(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)] + [(c, ctypes.c_ushort) for c in ("r", "g", "b", "a")]


# Corner colours below full intensity, so no pixel equals the white sentinel.
COLOURS = ((0xF000, 0x1000, 0x2000), (0x0800, 0xE000, 0x4000), (0x3000, 0x2400, 0xF0F0), (0x8080, 0x7F7F, 0x0101))


def triangles():
    yield "fixture-left", ((4, 60), (32, 25), (32, 45))
    yield "fixture-right", ((32, 25), (60, 60), (32, 45))
    # Exact hits: slopes whose rows land on whole columns.
    yield "exact-right-down", ((10, 5), (40, 20), (10, 50))
    yield "exact-left-down", ((50, 5), (20, 20), (50, 50))
    yield "exact-flat-top", ((8, 8), (56, 8), (32, 56))
    yield "exact-flat-bottom", ((32, 6), (8, 54), (56, 54))
    yield "vertical-left", ((10, 4), (10, 60), (50, 30))
    yield "vertical-right", ((50, 4), (50, 60), (10, 30))
    yield "middle-left", ((30, 4), (4, 30), (40, 60))
    yield "middle-right", ((30, 4), (60, 30), (20, 60))
    yield "thin", ((2, 2), (62, 9), (61, 10))
    yield "steep", ((30, 1), (33, 62), (31, 40))
    yield "shared-a", ((5, 5), (59, 21), (13, 58))
    yield "shared-b", ((59, 21), (13, 58), (60, 61))
    state = 12345
    for index in range(40):
        points = []
        for _ in range(3):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            x = state % 70 - 3
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            points.append((x, state % 70 - 3))
        yield f"random-{index}", tuple(points)


def rectangles():
    yield "rect-h", 0, ((5, 7), (50, 30))
    yield "rect-h-swapped", 0, ((50, 30), (5, 7))
    yield "rect-h-anti", 0, ((50, 7), (5, 30))
    yield "rect-v", 1, ((9, 3), (40, 61))
    yield "rect-v-swapped", 1, ((40, 61), (9, 3))
    yield "rect-h-one", 0, ((20, 20), (21, 25))
    yield "rect-h-wide", 0, ((-10, 2), (90, 4))
    yield "rect-v-tall", 1, ((2, -20), (6, 80))


def fill(mode, points, meshes):
    with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
        msimg = ctypes.WinDLL("msimg32", use_last_error=True)
        gradient = bind(
            msimg,
            "GradientFill",
            wintypes.BOOL,
            ctypes.c_void_p,
            ctypes.POINTER(TriVertex),
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
        )
        vertices = (TriVertex * len(points))(*[TriVertex(x, y, *COLOURS[i], 0) for i, (x, y) in enumerate(points)])
        flat = [index for mesh in meshes for index in mesh]
        indexes = (wintypes.DWORD * len(flat))(*flat)
        check(gradient(dc, vertices, len(points), indexes, len(meshes), mode), "GradientFill")
        data = ctypes.string_at(bits, SIZE * SIZE * 4)
    rows = []
    for y in range(SIZE):
        row = [data[(y * SIZE + x) * 4 : (y * SIZE + x) * 4 + 4] for x in range(SIZE)]
        changed = [x for x, pixel in enumerate(row) if pixel != SENTINEL]
        if changed:
            pixels = row[changed[0] : changed[-1] + 1]
            text = " ".join("-" if p == SENTINEL else f"{p[2]:02x}{p[1]:02x}{p[0]:02x}" for p in pixels)
            rows.append(f"  {y} {changed[0]} {text}")
    return rows


def main():
    print(f"Windows gradient probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, points in triangles():
        print(f"case {name} 2 vertices={points} meshes={((0, 1, 2),)}")
        print("\n".join(fill(2, points, ((0, 1, 2),))))
    for name, mode, points in rectangles():
        print(f"case {name} {mode} vertices={points} meshes={((0, 1),)}")
        print("\n".join(fill(mode, points, ((0, 1),))))


if __name__ == "__main__":
    main()
