"""Native drawing and recording of degenerate curved shapes and failed path calls.

First, pixels: on a fresh 64x64 reference surface with a one-pixel black pen
and the gray stock brush, each case moves to (5, 60), draws one Arc, Chord,
Pie, ArcTo, RoundRect, Ellipse or zero-radius AngleArc whose logical box has
zero width, zero height or both (and a one-unit-wide control), then draws a
line to (60, 60), in GM_COMPATIBLE and in GM_ADVANCED under the identity, a
rotation and a non-uniform scale:

    case mode=M box=B call=C drawn=R
    row Y X0 ##..#               (# marks a changed pixel)

Then the path (device points and types) after a PolyDraw with an invalid
point type inside a path bracket, and after a following LineTo:

    path step=S result=R count=N x,y:TYPE ...

Then native EMF recordings, in the format of probe-windows-emf-recording.py,
of the same shapes (all at once per mode, and each alone under the rotation)
and of clip paths built after the failed PolyDraw:

    [NAME] frame=None result=R
      type=T size=S payload=HEX
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, module_versions, reference_surface

SIZE = 64
BOXES = {"w0": (20, 10, 20, 40), "h0": (10, 20, 40, 20), "both0": (20, 20, 20, 20), "w1": (20, 10, 21, 40)}
MODES = {
    "compatible": None,
    "identity": (1.0, 0.0, 0.0, 1.0, 0.0, 0.0),
    "rotated": (0.866, 0.5, -0.5, 0.866, 20.0, 0.0),
    "scaled": (1.5, 0.0, 0.0, 0.5, 0.0, 10.0),
}
CALLS = ("arc", "chord", "pie", "arc_to", "round_rect", "ellipse", "angle_arc")


class LogBrush(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("color", wintypes.DWORD), ("hatch", ctypes.c_size_t)]


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def functions(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    api = {}
    for name, args in {
        "SetGraphicsMode": (integer,),
        "SetWorldTransform": (ctypes.POINTER(XForm),),
        "MoveToEx": (integer, integer, ptr),
        "LineTo": (integer, integer),
        "Arc": (integer,) * 8,
        "Chord": (integer,) * 8,
        "Pie": (integer,) * 8,
        "ArcTo": (integer,) * 8,
        "RoundRect": (integer,) * 6,
        "Ellipse": (integer,) * 4,
        "Rectangle": (integer,) * 4,
        "AngleArc": (integer, integer, wintypes.DWORD, ctypes.c_float, ctypes.c_float),
        "PolyDraw": (ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer),
        "BeginPath": (),
        "EndPath": (),
        "WidenPath": (),
        "SelectClipPath": (integer,),
        "SelectObject": (ptr,),
    }.items():
        result = ptr if name == "SelectObject" else (integer if name == "SetGraphicsMode" else boolean)
        api[name] = bind(gdi, name, result, ptr, *args)
    api["GetStockObject"] = bind(gdi, "GetStockObject", ptr, integer)
    api["ExtCreatePen"] = bind(gdi, "ExtCreatePen", ptr, wintypes.DWORD, wintypes.DWORD, ptr, wintypes.DWORD, ptr)
    return api


def set_mode(api, dc, mode):
    if MODES[mode] is not None:
        api["SetGraphicsMode"](dc, 2)
        api["SetWorldTransform"](dc, ctypes.byref(XForm(*MODES[mode])))


def shape(api, dc, call, box):
    left, top, right, bottom = box
    if call == "round_rect":
        return api["RoundRect"](dc, *box, 8, 8)
    if call == "ellipse":
        return api["Ellipse"](dc, *box)
    if call == "angle_arc":
        return api["AngleArc"](dc, left, top, 0, 30.0, 120.0)
    function = {"arc": "Arc", "chord": "Chord", "pie": "Pie", "arc_to": "ArcTo"}[call]
    return api[function](dc, *box, 50, 5, 5, 50)


def invalid_poly_draw(api, dc):
    points = (wintypes.POINT * 3)(wintypes.POINT(30, 5), wintypes.POINT(40, 20), wintypes.POINT(10, 30))
    types = (ctypes.c_ubyte * 3)(2, 4, 3)  # PT_LINETO, a lone PT_BEZIERTO, an undefined type
    return api["PolyDraw"](dc, points, types, 3)


def recordings(api):
    def degenerate(mode):
        def draw(dc):
            set_mode(api, dc, mode)
            results = []
            for box in BOXES.values():
                for call in CALLS:
                    results.append(shape(api, dc, call, box))
            return results

        return draw

    for mode in MODES:
        yield f"degenerate-shapes-{mode}", degenerate(mode)

    def single(box, call):
        def draw(dc):
            set_mode(api, dc, "rotated")
            return shape(api, dc, call, box)

        return draw

    for box_name, box in BOXES.items():
        for call in CALLS:
            yield f"degenerate-rotated-{box_name}-{call}", single(box, call)

    def clip(widen):
        def draw(dc):
            results = []
            if widen:
                brush = LogBrush(0, 0, 0)  # BS_SOLID black
                pen = api["ExtCreatePen"](0x10000, 6, ctypes.byref(brush), 0, None)  # PS_GEOMETRIC
                results.append(bool(api["SelectObject"](dc, pen)))
            api["BeginPath"](dc)
            api["MoveToEx"](dc, 5, 5, None)
            results.append(invalid_poly_draw(api, dc))
            api["LineTo"](dc, 50, 10)
            results.append(api["Ellipse"](dc, 10, 20, 40, 50))
            api["EndPath"](dc)
            if widen:
                results.append(api["WidenPath"](dc))
            results.append(api["SelectClipPath"](dc, 5 if not widen else 1))
            api["Rectangle"](dc, 0, 0, 60, 60)
            return results

        return draw

    yield "invalid-polydraw-clip-path", clip(False)
    yield "invalid-polydraw-widened-clip-path", clip(True)


def main():
    print(f"Windows degenerate shape probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for mode in MODES:
        for box_name, box in BOXES.items():
            for call in CALLS:
                with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
                    api = functions(gdi)
                    api["SelectObject"](dc, api["GetStockObject"](2))  # GRAY_BRUSH
                    set_mode(api, dc, mode)
                    api["MoveToEx"](dc, 5, 60, None)
                    drawn = shape(api, dc, call, box)
                    api["LineTo"](dc, 60, 60)
                    gdi.GdiFlush()
                    pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
                    print(f"case mode={mode} box={box_name} call={call} drawn={drawn}")
                    for y in range(SIZE):
                        row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                        if any(row):
                            first = row.index(True)
                            last = SIZE - 1 - row[::-1].index(True)
                            print(f"row {y} {first} " + "".join("#" if v else "." for v in row[first : last + 1]))
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    api = functions(gdi)
    get_path = bind(
        gdi, "GetPath", ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.POINT), ctypes.c_char_p, ctypes.c_int
    )
    with reference_surface(SIZE, SIZE) as (_, dc, _bits):
        # The path after each step, in device pixels.
        api["BeginPath"](dc)
        api["MoveToEx"](dc, 5, 5, None)
        for step, call in (
            ("poly-draw", lambda: invalid_poly_draw(api, dc)),
            ("line-to", lambda: api["LineTo"](dc, 50, 10)),
        ):
            result = call()
            count = get_path(dc, None, None, 0)
            points, kinds = (wintypes.POINT * max(count, 1))(), ctypes.create_string_buffer(max(count, 1))
            get_path(dc, points, kinds, count)
            listed = " ".join(f"{points[i].x},{points[i].y}:{kinds.raw[i]}" for i in range(max(count, 0)))
            print(f"path step={step} result={result} count={count} {listed}")
        api["EndPath"](dc)
    ptr = ctypes.c_void_p
    create_emf = bind(gdi, "CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ptr, ctypes.c_wchar_p)
    close_emf = bind(gdi, "CloseEnhMetaFile", ptr, ptr)
    get_bits = bind(gdi, "GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
    delete_emf = bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)
    for name, draw in recordings(api):
        with reference_surface(128, 128) as (_, reference, _bits):
            dc = create_emf(reference, None, None, None)
            result = draw(dc)
            metafile = close_emf(dc)
        size = get_bits(metafile, 0, None)
        buffer = ctypes.create_string_buffer(size)
        get_bits(metafile, size, buffer)
        delete_emf(metafile)
        print(f"\n[{name}] frame=None result={result!r}")
        position, data = 0, buffer.raw
        while position < len(data):
            kind, length = struct.unpack_from("<II", data, position)
            print(f"  type={kind} size={length} payload={data[position + 8 : position + length].hex()}")
            position += length


if __name__ == "__main__":
    main()
