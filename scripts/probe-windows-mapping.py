"""Print native mapping observations; no reference images or sidecars are written."""

import ctypes
import platform
from ctypes import wintypes

from windows_wmf_render import bind, check, reference_surface

# Suite-wide device contract, not per-image metadata. Physical-mode reference
# images depend on these device metrics.
REFERENCE_DEVICE_CAPS = {
    "HORZSIZE": (4, 271),
    "VERTSIZE": (6, 203),
    "HORZRES": (8, 1024),
    "VERTRES": (10, 768),
    "LOGPIXELSX": (88, 96),
    "LOGPIXELSY": (90, 96),
}


def validate_device_caps(caps):
    expected = {name: value for name, (_, value) in REFERENCE_DEVICE_CAPS.items()}
    if caps != expected:
        raise RuntimeError(f"Reference device changed: expected {expected}, got {caps}; review before generating PNGs")


def sequences():
    """Each sequence runs on a fresh reference DC; names describe the question."""
    for mode in range(1, 9):
        yield f"mode-{mode}", [("SetMapMode", mode)]
    yield (
        "origins-and-half-ties",
        [
            ("SetWindowExtEx", 2, 2, None),
            ("SetViewportExtEx", 1, 1, None),
            ("SetViewportOrgEx", 63, 64, None),
            ("SetWindowOrgEx", -3, 5, None),
            ("OffsetWindowOrgEx", 2, -4, None),
            ("OffsetViewportOrgEx", -1, 3, None),
        ],
    )
    yield (
        "mode-transitions",
        [
            ("SetWindowExtEx", 64, 64, None),
            ("SetMapMode", 8),
            ("SetMapMode", 1),
            ("SetMapMode", 8),
            ("SetMapMode", 7),
            ("SetMapMode", 7),
        ],
    )
    for mode in (1, 6, 7, 8):
        yield (
            f"extent-validation-{mode}",
            [
                ("SetMapMode", mode),
                ("SetWindowExtEx", 0, 10, None),
                ("SetViewportExtEx", 10, 0, None),
                ("ScaleWindowExtEx", 1, 0, 1, 1, None),
                ("ScaleViewportExtEx", 0, 1, 1, 1, None),
            ],
        )
    for reverse in (False, True):
        extents = [("SetWindowExtEx", 100, 50, None), ("SetViewportExtEx", 100, 100, None)]
        yield f"isotropic-order-{reverse}", [("SetMapMode", 7), *(reversed(extents) if reverse else extents)]
    yield (
        "signed-extents-and-truncation",
        [
            ("SetWindowExtEx", -17, 19, None),
            ("SetViewportExtEx", 40, -40, None),
            ("ScaleWindowExtEx", 2, 3, 3, 2, None),
            ("ScaleViewportExtEx", 3, 2, 2, 3, None),
            ("ScaleWindowExtEx", 1, 100, 1, 100, None),
        ],
    )
    yield (
        "save-restore",
        [
            ("MoveToEx", 7, 11, None),
            ("SaveDC",),
            ("SetViewportOrgEx", 32, 16, None),
            ("MoveToEx", 21, 35, None),
            ("SaveDC",),
            ("SetMapMode", 6),
            ("RestoreDC", -1),
            ("RestoreDC", -1),
        ],
    )
    yield "layout", [("SetLayout", 1), ("SetMapMode", 1), ("SetLayout", 0), ("SetMapMode", 1)]


def bind_probe(gdi):
    ptr, integer, boolean = ctypes.c_void_p, ctypes.c_int, wintypes.BOOL
    for name in ("GetMapMode", "SaveDC"):
        bind(gdi, name, integer, ptr)
    bind(gdi, "GetLayout", wintypes.DWORD, ptr)
    bind(gdi, "SetLayout", wintypes.DWORD, ptr, wintypes.DWORD)
    bind(gdi, "SetMapMode", integer, ptr, integer)
    bind(gdi, "RestoreDC", boolean, ptr, integer)
    bind(gdi, "GetDeviceCaps", integer, ptr, integer)
    bind(gdi, "LPtoDP", boolean, ptr, ctypes.POINTER(wintypes.POINT), integer)
    for name in ("GetWindowOrgEx", "GetViewportOrgEx", "GetCurrentPositionEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.POINT))
    for name in ("GetWindowExtEx", "GetViewportExtEx"):
        bind(gdi, name, boolean, ptr, ctypes.POINTER(wintypes.SIZE))
    for name in ("SetWindowOrgEx", "SetViewportOrgEx", "OffsetWindowOrgEx", "OffsetViewportOrgEx", "MoveToEx"):
        bind(gdi, name, boolean, ptr, integer, integer, ctypes.POINTER(wintypes.POINT))
    for name in ("SetWindowExtEx", "SetViewportExtEx"):
        bind(gdi, name, boolean, ptr, integer, integer, ctypes.POINTER(wintypes.SIZE))
    for name in ("ScaleWindowExtEx", "ScaleViewportExtEx"):
        bind(gdi, name, boolean, ptr, integer, integer, integer, integer, ctypes.POINTER(wintypes.SIZE))


SAMPLES = ((-15, -15), (-3, -3), (-1, -1), (0, 0), (1, 1), (3, 3), (15, 15), (127, 127), (1440, -1440))


def snapshot(gdi, dc):
    values = [f"mode={gdi.GetMapMode(dc)}", f"layout={gdi.GetLayout(dc)}"]
    for name, kind, fields in (
        ("GetWindowOrgEx", wintypes.POINT, ("x", "y")),
        ("GetViewportOrgEx", wintypes.POINT, ("x", "y")),
        ("GetWindowExtEx", wintypes.SIZE, ("cx", "cy")),
        ("GetViewportExtEx", wintypes.SIZE, ("cx", "cy")),
        ("GetCurrentPositionEx", wintypes.POINT, ("x", "y")),
    ):
        value = kind()
        check(getattr(gdi, name)(dc, ctypes.byref(value)), name)
        values.append(f"{name}={tuple(getattr(value, field) for field in fields)}")
    print("  " + " ".join(values))
    points = (wintypes.POINT * len(SAMPLES))(*(wintypes.POINT(x, y) for x, y in SAMPLES))
    check(gdi.LPtoDP(dc, points, len(points)), "LPtoDP")
    print(f"  LPtoDP={[(point.x, point.y) for point in points]}")


def main():
    print(f"Windows mapping probe: {platform.platform()}; surface=128x128 top-down BGRX")
    print(f"LPtoDP inputs={SAMPLES}")
    with reference_surface(128, 128) as (gdi, dc, _):
        bind_probe(gdi)
        caps = {name: gdi.GetDeviceCaps(dc, index) for name, (index, _) in REFERENCE_DEVICE_CAPS.items()}
        print(f"Device capabilities={caps}")
        validate_device_caps(caps)
        print("Reference initial state:")
        snapshot(gdi, dc)
    for name, calls in sequences():
        print(f"\n[{name}]")
        with reference_surface(128, 128) as (gdi, dc, _):
            bind_probe(gdi)
            for operation, *args in calls:
                # Failed setters are observations; query unchanged state afterwards.
                result = getattr(gdi, operation)(dc, *args)
                print(f"{operation}{tuple(args)} -> {result}")
                snapshot(gdi, dc)


if __name__ == "__main__":
    main()
