"""Targeted layout state observations; no pytest or reference regeneration."""

import ctypes
import runpy
from ctypes import wintypes
from pathlib import Path

from windows_wmf_render import bind, check, reference_surface


def main():
    helpers = runpy.run_path(str(Path(__file__).with_name("probe-windows-mapping.py")))

    class Xform(ctypes.Structure):
        _fields_ = [(name, ctypes.c_float) for name in ("xx", "xy", "yx", "yy", "dx", "dy")]

    for wx, vx, extent in ((0, 0, 96), (3, 0, 96), (0, 7, 96), (3, 7, 96), (3, 7, -96), (3, 7, 64)):
        with reference_surface(128, 128) as (gdi, dc, _):
            helpers["bind_probe"](gdi)
            transform = bind(gdi, "GetTransform", wintypes.BOOL, ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(Xform))
            gdi.SetWindowOrgEx(dc, wx, -2, None)
            gdi.SetViewportOrgEx(dc, vx, 4, None)
            gdi.SetLayout(dc, 1)
            gdi.SetWindowExtEx(dc, 64, 128, None)
            gdi.SetViewportExtEx(dc, extent, 128, None)
            value = Xform()
            check(transform(dc, 0x204, ctypes.byref(value)), "GetTransform")
            print(
                f"TRANSFORM wx={wx} vx={vx} extent={extent}: {[(name, getattr(value, name)) for name, _ in value._fields_]}"
            )
            helpers["snapshot"](gdi, dc)
    names = [f"layout-mapping-{order}" for order in ("before", "after", "restore")]
    names += [f"layout-shapes-scale{vx}-pen0" for vx in (48, 96, -96)]
    for name in names:
        print(f"\n[WMF {name}]", flush=True)
        source = (Path(__file__).resolve().parents[1] / "test/compatibility/wmf" / f"{name}.wmf").read_bytes()
        with reference_surface(128, 128) as (gdi, dc, _):
            helpers["bind_probe"](gdi)
            ptr = ctypes.c_void_p
            set_bits = bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
            delete = bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
            play = bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, ctypes.c_uint)
            for operation in ("BeginPath", "EndPath", "AbortPath"):
                bind(gdi, operation, wintypes.BOOL, ptr)
            get_path = bind(gdi, "GetPath", ctypes.c_int, ptr, ptr, ptr, ctypes.c_int)
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ptr, ptr, ptr, ctypes.c_int, ctypes.c_ssize_t)
            enum = bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
            errors = []

            @callback_type
            def callback(hdc, handles, record, count, _):
                try:
                    function = ctypes.c_ushort.from_address(record + 4).value
                    capture = "shapes" in name and function in (0x0418, 0x061C, 0x0817, 0x081A)
                    if capture:
                        check(gdi.BeginPath(hdc), "BeginPath")
                    result = play(hdc, handles, record, count)
                    if capture:
                        check(gdi.EndPath(hdc), "EndPath")
                        saved = gdi.SaveDC(hdc)
                        gdi.SetLayout(hdc, 0)
                        gdi.SetMapMode(hdc, 1)
                        gdi.SetWindowOrgEx(hdc, 0, 0, None)
                        gdi.SetViewportOrgEx(hdc, 0, 0, None)
                        count = get_path(hdc, None, None, 0)
                        points = (wintypes.POINT * count)()
                        kinds = (ctypes.c_ubyte * count)()
                        get_path(hdc, points, kinds, count)
                        print(f"PATH {name} {function:04x}: {[(p.x, p.y, k) for p, k in zip(points, kinds)]}")
                        gdi.RestoreDC(hdc, saved)
                        gdi.AbortPath(hdc)
                    if function in (0x0103, 0x020B, 0x020C, 0x020D, 0x020E, 0x0149, 0x001E, 0x0127):
                        print(f"record={function:04x} result={result}")
                        helpers["snapshot"](gdi, hdc)
                    return 1
                except Exception as error:
                    errors.append(error)
                    return 0

            buffer = ctypes.create_string_buffer(source)
            metafile = check(set_bits(len(source), buffer), "SetMetaFileBitsEx")
            try:
                check(enum(dc, metafile, callback, 0), "EnumMetaFile")
                if errors:
                    raise errors[0]
            finally:
                delete(metafile)


if __name__ == "__main__":
    main()
