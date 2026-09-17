"""Inspect native WMF region handles and device clip displacement."""

import ctypes
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

from pillow_wmf import Recorder
from pillow_wmf.wmf.objects import Region, Scan


def main():
    with reference_surface(128, 128) as (gdi, dc, _bits):
        ptr, integer = ctypes.c_void_p, ctypes.c_int
        bind(gdi, "CreateRectRgn", ptr, integer, integer, integer, integer)
        bind(gdi, "SelectClipRgn", integer, ptr, ptr)
        bind(gdi, "OffsetClipRgn", integer, ptr, integer, integer)
        bind(gdi, "GetClipBox", integer, ptr, ctypes.POINTER(wintypes.RECT))
        bind(gdi, "GetObjectType", wintypes.DWORD, ptr)
        bind(gdi, "SetMetaFileBitsEx", ptr, wintypes.UINT, ptr)
        bind(gdi, "DeleteMetaFile", wintypes.BOOL, ptr)
        bind(gdi, "PlayMetaFileRecord", wintypes.BOOL, ptr, ptr, ptr, wintypes.UINT)
        callback_type = ctypes.WINFUNCTYPE(integer, ptr, ctypes.POINTER(ptr), ptr, integer, ctypes.c_ssize_t)
        bind(gdi, "EnumMetaFile", wintypes.BOOL, ptr, ptr, callback_type, ctypes.c_ssize_t)
        for scans in ((), (Scan(8, 16, (8, 8)),), (Scan(8, 16, (8, 32)),)):
            recorder = Recorder()
            recorder.create_region(Region((8, 8, 32, 16), scans))
            data = recorder.to_bytes()
            buffer = ctypes.create_string_buffer(data)
            metafile = check(gdi.SetMetaFileBitsEx(len(data), buffer), "SetMetaFileBitsEx")

            @callback_type
            def callback(hdc, handles, record, count, _param):
                result = gdi.PlayMetaFileRecord(hdc, handles, record, count)
                function = ctypes.cast(record, ctypes.POINTER(ctypes.c_ushort))[2]
                if function == 0x6FF:
                    print("region-handle", scans, bool(result), bool(handles[0]), gdi.GetObjectType(handles[0]))
                return 1

            try:
                check(gdi.EnumMetaFile(dc, metafile, callback, 0), "EnumMetaFile")
            finally:
                gdi.DeleteMetaFile(metafile)
        region = check(gdi.CreateRectRgn(32, 32, 64, 64), "CreateRectRgn")
        try:
            for extent in ((192, 64), (-192, -64), (80, 80)):
                for x, y in ((7, -9), (-7, 9), (1, 1), (-1, -1), (3, -3)):
                    check(gdi.SetViewportExtEx(dc, *extent, None), "SetViewportExtEx")
                    check(gdi.SelectClipRgn(dc, region), "SelectClipRgn")
                    check(gdi.OffsetClipRgn(dc, x, y), "OffsetClipRgn")
                    check(gdi.SetViewportExtEx(dc, 128, 128, None), "SetViewportExtEx")
                    box = wintypes.RECT()
                    gdi.GetClipBox(dc, ctypes.byref(box))
                    print("clip-offset", extent, (x, y), (box.left, box.top, box.right, box.bottom))
        finally:
            gdi.SelectClipRgn(dc, None)
            gdi.DeleteObject(region)


if __name__ == "__main__":
    main()
