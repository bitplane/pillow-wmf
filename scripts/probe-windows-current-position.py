"""The current position across world-transform changes, and paths after a failed PolyDraw.

Position cases run on a fresh 64x64 reference surface in GM_ADVANCED. Each
optionally moves to a point, then sets a world transform, then reports
GetCurrentPositionEx (logical) and draws one LineTo, ArcTo, AngleArc or
PolylineTo with a one-pixel black pen:

    case NAME position=X,Y result=R
    row Y X0 ##..#               (# marks a changed pixel)

Path cases build a path on the reference surface, end it and read it back
with GetPath (device points), with the current position after the PolyDraw:

    path NAME polydraw=R position=X,Y count=N x,y:TYPE ...

Then, per invalid type, the clip region SelectClipPath makes from the
line-and-ellipse path (the surface filled black through it), and the failed
PolyDraw drawn outside a path followed by a LineTo:

    region NAME clip=C result=R
    row Y X0 ##..#

Then the same position and path cases recorded natively, in the format of
probe-windows-emf-recording.py:

    [NAME] frame=None result=R
      type=T size=S payload=HEX
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, module_versions, reference_surface

SIZE = 64
ROTATE = (0.866, 0.5, -0.5, 0.866, 20.0, 0.0)
SHIFT = (1.0, 0.0, 0.0, 1.0, 7.0, 3.0)
SCALE = (2.0, 0.0, 0.0, 1.5, 0.0, 0.0)
DRAWS = ("line_to", "arc_to", "angle_arc", "polyline_to")
POSITION_CASES = [
    (f"{start}-{transform_name}-{draw}", start_point, transform, draw)
    for start, start_point in (("initial", None), ("moved", (10, 12)))
    for transform_name, transform in (("rotate", ROTATE), ("shift", SHIFT), ("scale", SCALE))
    for draw in DRAWS
]
INVALID_TYPES = {"lone-bezier": (2, 4, 3), "undefined": (2, 2, 9), "short-bezier": (2, 4, 4)}
PATH_CASES = [
    (f"{name}-{tail}", types, tail)
    for name, types in INVALID_TYPES.items()
    for tail in ("alone", "line", "line-ellipse")
]


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
        "ArcTo": (integer,) * 8,
        "Ellipse": (integer,) * 4,
        "Rectangle": (integer,) * 4,
        "AngleArc": (integer, integer, wintypes.DWORD, ctypes.c_float, ctypes.c_float),
        "PolylineTo": (ctypes.POINTER(wintypes.POINT), wintypes.DWORD),
        "PolyDraw": (ctypes.POINTER(wintypes.POINT), ctypes.POINTER(ctypes.c_ubyte), integer),
        "GetCurrentPositionEx": (ctypes.POINTER(wintypes.POINT),),
        "BeginPath": (),
        "EndPath": (),
        "SelectClipPath": (integer,),
        "PatBlt": (integer, integer, integer, integer, wintypes.DWORD),
    }.items():
        api[name] = bind(gdi, name, integer if name == "SetGraphicsMode" else boolean, ptr, *args)
    api["GetPath"] = bind(gdi, "GetPath", integer, ptr, ctypes.POINTER(wintypes.POINT), ctypes.c_char_p, integer)
    return api


def position_case(api, dc, start, transform, draw):
    api["SetGraphicsMode"](dc, 2)
    if start is not None:
        api["MoveToEx"](dc, *start, None)
    api["SetWorldTransform"](dc, ctypes.byref(XForm(*transform)))
    point = wintypes.POINT()
    api["GetCurrentPositionEx"](dc, ctypes.byref(point))
    if draw == "line_to":
        result = api["LineTo"](dc, 40, 30)
    elif draw == "arc_to":
        result = api["ArcTo"](dc, 20, 20, 40, 34, 40, 27, 20, 20)
    elif draw == "angle_arc":
        result = api["AngleArc"](dc, 30, 30, 8, 30.0, 120.0)
    else:
        points = (wintypes.POINT * 2)(wintypes.POINT(40, 30), wintypes.POINT(30, 40))
        result = api["PolylineTo"](dc, points, 2)
    return (point.x, point.y), result


def path_case(api, dc, types, tail):
    api["BeginPath"](dc)
    api["MoveToEx"](dc, 5, 5, None)
    points = (wintypes.POINT * 3)(wintypes.POINT(30, 5), wintypes.POINT(40, 20), wintypes.POINT(10, 30))
    result = api["PolyDraw"](dc, points, (ctypes.c_ubyte * 3)(*types), 3)
    point = wintypes.POINT()
    api["GetCurrentPositionEx"](dc, ctypes.byref(point))
    if tail != "alone":
        api["LineTo"](dc, 50, 10)
    if tail == "line-ellipse":
        api["Ellipse"](dc, 10, 20, 40, 50)
    api["EndPath"](dc)
    return result, (point.x, point.y)


def main():
    print(f"Windows current position probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name, start, transform, draw in POSITION_CASES:
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            api = functions(gdi)
            position, result = position_case(api, dc, start, transform, draw)
            gdi.GdiFlush()
            pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
            print(f"case {name} position={position[0]},{position[1]} result={result}")
            for y in range(SIZE):
                row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                if any(row):
                    first = row.index(True)
                    last = SIZE - 1 - row[::-1].index(True)
                    print(f"row {y} {first} " + "".join("#" if v else "." for v in row[first : last + 1]))
    for name, types, tail in PATH_CASES:
        with reference_surface(SIZE, SIZE) as (gdi, dc, _bits):
            api = functions(gdi)
            result, position = path_case(api, dc, types, tail)
            count = api["GetPath"](dc, None, None, 0)
            size = max(count, 1)
            points, kinds = (wintypes.POINT * size)(), ctypes.create_string_buffer(size)
            api["GetPath"](dc, points, kinds, count)
            listed = " ".join(f"{points[i].x},{points[i].y}:{kinds.raw[i]}" for i in range(max(count, 0)))
            print(f"path {name} polydraw={result} position={position[0]},{position[1]} count={count} {listed}")
    for name, types in INVALID_TYPES.items():
        for clip in (True, False):
            # With a clip path: the region it makes, filled black. Without:
            # the failed PolyDraw drawn outside a path, then a LineTo.
            with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
                api = functions(gdi)
                if clip:
                    path_case(api, dc, types, "line-ellipse")
                    result = api["SelectClipPath"](dc, 5)
                    api["PatBlt"](dc, 0, 0, SIZE, SIZE, 0x00000042)  # BLACKNESS
                else:
                    api["MoveToEx"](dc, 5, 5, None)
                    points = (wintypes.POINT * 3)(wintypes.POINT(30, 5), wintypes.POINT(40, 20), wintypes.POINT(10, 30))
                    result = api["PolyDraw"](dc, points, (ctypes.c_ubyte * 3)(*types), 3)
                    api["LineTo"](dc, 50, 60)
                gdi.GdiFlush()
                pixels = ctypes.cast(bits, ctypes.POINTER(ctypes.c_uint32))
                print(f"region {name} clip={clip} result={result}")
                for y in range(SIZE):
                    row = [pixels[y * SIZE + x] & 0xFFFFFF != 0xFFFFFF for x in range(SIZE)]
                    if any(row):
                        first = row.index(True)
                        last = SIZE - 1 - row[::-1].index(True)
                        print(f"row {y} {first} " + "".join("#" if v else "." for v in row[first : last + 1]))
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    api = functions(gdi)
    ptr = ctypes.c_void_p
    create_emf = bind(gdi, "CreateEnhMetaFileW", ptr, ptr, ctypes.c_wchar_p, ptr, ctypes.c_wchar_p)
    close_emf = bind(gdi, "CloseEnhMetaFile", ptr, ptr)
    get_bits = bind(gdi, "GetEnhMetaFileBits", wintypes.UINT, ptr, wintypes.UINT, ptr)
    delete_emf = bind(gdi, "DeleteEnhMetaFile", wintypes.BOOL, ptr)
    get_clip_box = bind(gdi, "GetClipBox", ctypes.c_int, ptr, ctypes.POINTER(wintypes.RECT))
    create_rgn = bind(gdi, "CreateRectRgn", ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
    get_clip_rgn = bind(gdi, "GetClipRgn", ctypes.c_int, ptr, ptr)
    get_rgn_box = bind(gdi, "GetRgnBox", ctypes.c_int, ptr, ctypes.POINTER(wintypes.RECT))

    def clip_variant(builder):
        def draw(dc):
            api["BeginPath"](dc)
            api["MoveToEx"](dc, 5, 5, None)
            builder(dc)
            api["Ellipse"](dc, 10, 20, 40, 50)
            api["EndPath"](dc)
            count = api["GetPath"](dc, None, None, 0)
            size = max(count, 1)
            points, kinds = (wintypes.POINT * size)(), ctypes.create_string_buffer(size)
            api["GetPath"](dc, points, kinds, count)
            path = " ".join(f"{points[i].x},{points[i].y}:{kinds.raw[i]}" for i in range(max(count, 0)))
            selected = api["SelectClipPath"](dc, 5)
            box, region_box = wintypes.RECT(), wintypes.RECT()
            kind = get_clip_box(dc, ctypes.byref(box))
            region = create_rgn(0, 0, 0, 0)
            has = get_clip_rgn(dc, region)
            get_rgn_box(region, ctypes.byref(region_box))
            api["Rectangle"](dc, 0, 0, 60, 60)
            return (
                f"selected={selected} clipbox={kind}:{box.left},{box.top},{box.right},{box.bottom} "
                f"cliprgn={has}:{region_box.left},{region_box.top},{region_box.right},{region_box.bottom} path={path}"
            )

        return draw

    def failed(dc):
        points = (wintypes.POINT * 3)(wintypes.POINT(30, 5), wintypes.POINT(40, 20), wintypes.POINT(10, 30))
        api["PolyDraw"](dc, points, (ctypes.c_ubyte * 3)(2, 4, 3), 3)
        api["LineTo"](dc, 50, 10)

    def rebuilt(dc):
        api["LineTo"](dc, 30, 5)
        api["MoveToEx"](dc, 5, 5, None)
        api["LineTo"](dc, 50, 10)

    recordings = [
        ("clip-failed-polydraw", clip_variant(failed)),
        ("clip-rebuilt-path", clip_variant(rebuilt)),
        ("clip-line", clip_variant(lambda dc: api["LineTo"](dc, 50, 10))),
        ("clip-ellipse-only", clip_variant(lambda dc: None)),
    ]
    recordings += [
        (f"position-{name}", lambda dc, c=case: position_case(api, dc, *c)) for name, *case in POSITION_CASES
    ]
    recordings += [(f"polydraw-path-{name}", lambda dc, c=case: path_case(api, dc, *c)) for name, *case in PATH_CASES]
    for name, draw in recordings:
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
