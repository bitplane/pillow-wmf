"""Print how native EMF playback fits the picture frame onto a target rectangle.

For each case an in-memory EMF is enumerated into a fresh reference DC. After
the header and each mapping record the DC's graphics mode, world transform,
page mapping and LPtoDP results are printed; then the pixels drawn by
SetPixelV markers are listed. No reference images are written.
"""

import ctypes
import platform
import struct
from ctypes import wintypes

from windows_wmf_render import bind, check, module_versions, reference_surface

from pillow_wmf.emf import Metafile, fixed
from pillow_wmf.mapping import ReferenceDevice

SIZE = 128
PIXEL_RECORDS = {15}  # EMR_SETPIXELV: markers, not mapping state.


class XForm(ctypes.Structure):
    _fields_ = [(name, ctypes.c_float) for name in ("m11", "m12", "m21", "m22", "dx", "dy")]


def diagonal(count, step=1, start=0):
    """Markers at (i, i), coloured by their index so each can be found again."""
    return [fixed.SetPixelV(start + i * step, start + i * step, i + 1) for i in range(count)]


def cases():
    """(name, header options, records, target rectangle)."""
    full = (0, 0, SIZE, SIZE)
    # Frames are inclusive 0.01 mm rectangles. On the reference device one
    # pixel is 27100/1024 = 26.46 units across and 20300/768 = 26.43 down.
    for right in (3386, 3387, 3388, 3413):
        yield f"frame-0-{right}", {"frame": (0, 0, right, right)}, diagonal(130), full
    yield "frame-1000", {"frame": (0, 0, 1000, 1000)}, diagonal(40), full
    yield "frame-1000-500", {"frame": (0, 0, 1000, 500)}, diagonal(40), full
    yield "frame-offset", {"frame": (100, -50, 1100, 950)}, diagonal(48, start=-6), full
    yield "frame-tiny", {"frame": (0, 0, 99, 99)}, diagonal(6), full
    yield "frame-large", {"frame": (0, 0, 10000, 10000)}, diagonal(250, step=2), full
    yield "frame-empty-bounds", {"frame": (0, 0, 1000, 1000), "bounds": (5, 5, 10, 10)}, diagonal(40), full
    small = ReferenceDevice((800, 600), (200, 150))
    yield "device-800x600", {"frame": (0, 0, 1000, 1000), "device": small}, diagonal(40), full
    yield "rect-offset", {"frame": (0, 0, 1000, 1000)}, diagonal(40), (10, 20, 74, 52)
    yield "rect-reversed", {"frame": (0, 0, 1000, 1000)}, diagonal(40), (SIZE, SIZE, 0, 0)
    page = [
        fixed.SetMapMode(8),
        fixed.SetWindowOrgEx(-10, 5),
        fixed.SetWindowExtEx(300, 200),
        fixed.SetViewportOrgEx(2, 3),
        fixed.SetViewportExtEx(37, 37),
    ]
    yield "page-anisotropic", {"frame": (0, 0, 1000, 1000)}, page + diagonal(60, step=5, start=-10), full
    himetric = [fixed.SetPixelV(26 * i, -26 * i, i + 1) for i in range(40)]
    yield "page-himetric", {"frame": (0, 0, 1000, 1000)}, [fixed.SetMapMode(3)] + himetric, full
    scale = [fixed.SetWorldTransform(0.75, 0.0, 0.0, 1.5, 0.25, 0.5)]
    yield "world-scale", {"frame": (0, 0, 1000, 1000)}, scale + diagonal(40), full


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    bind(gdi, "GetMapMode", integer, ptr)
    bind(gdi, "GetGraphicsMode", integer, ptr)
    bind(gdi, "GetWorldTransform", boolean, ptr, ctypes.POINTER(XForm))
    bind(gdi, "LPtoDP", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    for name in ("GetWindowOrgEx", "GetViewportOrgEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.POINT))
    for name in ("GetWindowExtEx", "GetViewportExtEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.SIZE))
    bind(gdi, "SetEnhMetaFileBits", ptr, wintypes.UINT, ptr)
    bind(gdi, "DeleteEnhMetaFile", boolean, ptr)
    bind(gdi, "PlayEnhMetaFile", boolean, ptr, ptr, ctypes.POINTER(wintypes.RECT))
    bind(gdi, "PlayEnhMetaFileRecord", boolean, ptr, ptr, ptr, wintypes.UINT)
    bind(gdi, "GdiFlush", boolean)


def float_bits(value):
    return struct.pack("<f", value).hex()


def snapshot(gdi, dc, samples):
    transform = XForm()
    check(gdi.GetWorldTransform(dc, ctypes.byref(transform)), "GetWorldTransform")
    fields = [(name, getattr(transform, name)) for name, _ in XForm._fields_]
    values = [f"gm={gdi.GetGraphicsMode(dc)} mode={gdi.GetMapMode(dc)}"]
    values.append("xform=" + " ".join(f"{name}={value!r}/{float_bits(value)}" for name, value in fields))
    for name, kind, names in (
        ("GetWindowOrgEx", wintypes.POINT, ("x", "y")),
        ("GetWindowExtEx", wintypes.SIZE, ("cx", "cy")),
        ("GetViewportOrgEx", wintypes.POINT, ("x", "y")),
        ("GetViewportExtEx", wintypes.SIZE, ("cx", "cy")),
    ):
        value = kind()
        check(getattr(gdi, name)(dc, ctypes.byref(value)), name)
        values.append(f"{name[3:-2]}={tuple(getattr(value, field) for field in names)}")
    points = (wintypes.POINT * len(samples))(*(wintypes.POINT(x, y) for x, y in samples))
    check(gdi.LPtoDP(dc, points, len(points)), "LPtoDP")
    values.append(f"LPtoDP={[(p.x, p.y) for p in points]}")
    print("  " + "\n  ".join(values))


def markers(bits):
    """Drawn pixels as (index, x, y), or ((r, g, b), x, y) for other colours.

    Marker colours carry their index in the red channel.
    """
    data = ctypes.string_at(bits, SIZE * SIZE * 4)
    found = []
    for offset in range(0, len(data), 4):
        blue, green, red = data[offset], data[offset + 1], data[offset + 2]
        if (red, green, blue) != (255, 255, 255):
            pixel = offset // 4
            colour = red if not green and not blue else (red, green, blue)
            found.append((colour, pixel % SIZE, pixel // SIZE))
    return sorted(found, key=lambda item: (isinstance(item[0], tuple), item))


def run_case(name, header, records, rect):
    data = Metafile.build(records, **header).to_bytes()
    samples = [(record.x, record.y) for record in records if isinstance(record, fixed.SetPixelV)][::8][:12]
    print(f"\n[{name}] frame={header.get('frame')} bounds={header.get('bounds', (0, 0, -1, -1))} rect={rect}")
    if "device" in header:
        print(f"  header device={header['device'].pixels} millimetres={header['device'].millimetres}")
    print(f"  LPtoDP inputs={samples}")
    outputs = []
    failed = []
    for enumerate_records in (True, False):
        with reference_surface(SIZE, SIZE) as (gdi, dc, bits):
            bind_probe(gdi)
            buffer = ctypes.create_string_buffer(data)
            metafile = check(gdi.SetEnhMetaFileBits(len(data), buffer), "SetEnhMetaFileBits")
            target = wintypes.RECT(*rect)
            try:
                if enumerate_records:
                    callback_type = ctypes.WINFUNCTYPE(
                        ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, wintypes.LPARAM
                    )

                    def visit(hdc, table, record, handles, _):
                        kind = ctypes.cast(record, ctypes.POINTER(wintypes.DWORD))[0]
                        if kind == 1:
                            print("  before header:")
                            snapshot(gdi, hdc, samples)
                        played = gdi.PlayEnhMetaFileRecord(hdc, table, record, handles)
                        if kind in PIXEL_RECORDS and not played:
                            failed.append(ctypes.cast(record, ctypes.POINTER(wintypes.LONG))[2:4])
                        if kind not in PIXEL_RECORDS:
                            print(f"  after record type {kind} (played={played}):")
                            snapshot(gdi, hdc, samples)
                        return 1

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
                    result = enum(dc, metafile, callback, None, ctypes.byref(target))
                    print(f"  EnumEnhMetaFile={result}; SetPixelV failed at logical {failed}")
                else:
                    # FALSE when any record fails, such as SetPixelV off the surface.
                    print(f"  PlayEnhMetaFile={gdi.PlayEnhMetaFile(dc, metafile, ctypes.byref(target))}")
                check(gdi.GdiFlush(), "GdiFlush")
                outputs.append(markers(bits))
            finally:
                gdi.DeleteEnhMetaFile(metafile)
    print(f"  enumerated and played pixels agree: {outputs[0] == outputs[1]}")
    print(f"  markers (index, x, y)={outputs[1]}")


def main():
    print(f"Windows EMF frame probe: {platform.platform()}; surface={SIZE}x{SIZE} top-down BGRX")
    print(f"Module versions: {module_versions()}")
    for case in cases():
        run_case(*case)


if __name__ == "__main__":
    main()
