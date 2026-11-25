"""Print the DC state native EMF playback leaves after a SetLayout record.

Each case plays a metafile record by record with EnumEnhMetaFile onto the
128x128 reference DIB. After every record it prints the layout, mapping
mode, graphics mode, window and viewport, world transform, the composed
world-to-device transform, the clip box, where three logical points land,
and the bounds of the pixels changed so far. No reference images are
written.

    case name index type played=... key=value ...
"""

import ctypes
import platform
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Metafile, fixed

SIZE = 128
FIXTURES = Path(__file__).resolve().parents[1] / "test" / "compatibility" / "emf"
UNIT_FRAME = (0, 0, 3388, 3383)


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def cases():
    yield "fixture", (FIXTURES / "emf-layout-unit.emf").read_bytes()
    rectangle = fixed.Rectangle(10, 10, 60, 40)
    yield "rect-only", Metafile.build([rectangle], frame=UNIT_FRAME).to_bytes()
    yield "layout-rect", Metafile.build([fixed.SetLayout(1), rectangle], frame=UNIT_FRAME).to_bytes()
    yield "layout-off", Metafile.build([fixed.SetLayout(1), fixed.SetLayout(0), rectangle], frame=UNIT_FRAME).to_bytes()
    yield "layout-bitmap", Metafile.build([fixed.SetLayout(9), rectangle], frame=UNIT_FRAME).to_bytes()
    half = (0, 0, 1694, 1692)
    yield "layout-half-frame", Metafile.build([fixed.SetLayout(1), rectangle], frame=half).to_bytes()


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "GetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "GetTransform", boolean, ptr, wintypes.DWORD, ctypes.POINTER(XForm))
    bind(gdi, "GetMapMode", integer, ptr)
    bind(gdi, "GetGraphicsMode", integer, ptr)
    bind(gdi, "GetLayout", wintypes.DWORD, ptr)
    for name in ("GetWindowOrgEx", "GetViewportOrgEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.POINT))
    for name in ("GetWindowExtEx", "GetViewportExtEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.SIZE))
    bind(gdi, "GetClipBox", integer, ptr, ctypes.POINTER(wintypes.RECT))
    bind(gdi, "LPtoDP", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    bind(gdi, "SetEnhMetaFileBits", ptr, wintypes.UINT, ptr)
    bind(gdi, "DeleteEnhMetaFile", boolean, ptr)
    bind(gdi, "PlayEnhMetaFileRecord", boolean, ptr, ptr, ptr, wintypes.UINT)


def xform(value):
    return "(" + ",".join(f"{getattr(value, name):.6g}" for name, _ in XForm._fields_) + ")"


def state(gdi, dc, bits):
    world, device = XForm(), XForm()
    gdi.GetWorldTransform(dc, ctypes.byref(world))
    gdi.GetTransform(dc, 0x204, ctypes.byref(device))
    origin, vorigin, extent, vextent = wintypes.POINT(), wintypes.POINT(), wintypes.SIZE(), wintypes.SIZE()
    gdi.GetWindowOrgEx(dc, ctypes.byref(origin))
    gdi.GetViewportOrgEx(dc, ctypes.byref(vorigin))
    gdi.GetWindowExtEx(dc, ctypes.byref(extent))
    gdi.GetViewportExtEx(dc, ctypes.byref(vextent))
    clip = wintypes.RECT()
    region = gdi.GetClipBox(dc, ctypes.byref(clip))
    points = (wintypes.POINT * 3)(wintypes.POINT(0, 0), wintypes.POINT(10, 10), wintypes.POINT(100, 20))
    gdi.LPtoDP(dc, points, 3)
    data = ctypes.string_at(bits, SIZE * SIZE * 4)
    changed = [(i % SIZE, i // SIZE) for i in range(SIZE * SIZE) if data[4 * i : 4 * i + 4] != b"\xff\xff\xff\xff"]
    bounds = (
        (min(x for x, _ in changed), min(y for _, y in changed), max(x for x, _ in changed), max(y for _, y in changed))
        if changed
        else None
    )
    return (
        f"layout={gdi.GetLayout(dc)} mode={gdi.GetMapMode(dc)} gm={gdi.GetGraphicsMode(dc)}"
        f" worg=({origin.x},{origin.y}) wext=({extent.cx},{extent.cy})"
        f" vorg=({vorigin.x},{vorigin.y}) vext=({vextent.cx},{vextent.cy})"
        f" world={xform(world)} w2d={xform(device)}"
        f" clip={region}:({clip.left},{clip.top},{clip.right},{clip.bottom})"
        f" lp2dp={[(p.x, p.y) for p in points]} changed={len(changed)} bounds={bounds}"
    )


def run(gdi, name, data):
    callback_type = ctypes.WINFUNCTYPE(
        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, wintypes.LPARAM
    )
    with reference_surface(SIZE, SIZE) as (_, dc, bits):
        position = [0]

        def visit(hdc, table, record, handles, _):
            kind = ctypes.cast(record, ctypes.POINTER(wintypes.DWORD))[0]
            played = gdi.PlayEnhMetaFileRecord(hdc, table, record, handles)
            print(f"case {name} {position[0]} {kind} played={played} {state(gdi, hdc, bits)}")
            position[0] += 1
            return 1

        buffer = ctypes.create_string_buffer(data)
        metafile = check(gdi.SetEnhMetaFileBits(len(data), buffer), "SetEnhMetaFileBits")
        try:
            callback = callback_type(visit)
            enum = bind(
                gdi,
                "EnumEnhMetaFile",
                wintypes.BOOL,
                ctypes.c_void_p,
                ctypes.c_void_p,
                callback_type,
                ctypes.c_void_p,
                ctypes.POINTER(wintypes.RECT),
            )
            result = enum(dc, metafile, callback, None, ctypes.byref(wintypes.RECT(0, 0, SIZE, SIZE)))
        finally:
            gdi.DeleteEnhMetaFile(metafile)
        print(f"end {name} result={result} {state(gdi, dc, bits)}")


def main():
    print(f"Windows EMF layout probe: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    bind_probe(gdi)
    for name, data in cases():
        run(gdi, name, data)


if __name__ == "__main__":
    main()
