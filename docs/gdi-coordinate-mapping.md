# GDI coordinate mapping

The reader and recorder preserve logical coordinates and call order. `Mapping`
owns coordinate state and conversion; each drawing operation realizes its
geometry before the rasterizer determines coverage. There is no global twips
normalization or final-image resize.

## Modes and state

| Mode | Logical unit | Positive Y before layout |
| --- | --- | --- |
| MM_TEXT | Device pixel | Down |
| MM_LOMETRIC | 0.1 mm | Up |
| MM_HIMETRIC | 0.01 mm | Up |
| MM_LOENGLISH | 0.01 inch | Up |
| MM_HIENGLISH | 0.001 inch | Up |
| MM_TWIPS | 1/1440 inch | Up |
| MM_ISOTROPIC | Application-defined, equal physical scale | Extent-dependent |
| MM_ANISOTROPIC | Application-defined, independent axis scales | Extent-dependent |

Text mode installs unit extents. Physical modes use the
[reference device profile](wmf-foundation-fixtures.md#reference-device-profile);
isotropic mode starts with low-metric extents. Anisotropic mode retains the
existing extents. Extent setters and scalers do nothing in fixed modes.
Zero extents, factors or divisors leave state unchanged. Extent scaling
truncates integer division toward zero; a zero result also leaves state unchanged.

Isotropic adjustment shrinks one viewport dimension using physical pixel
dimensions, preserves its sign, and prevents a rounded zero extent. Setter
order and intermediate state matter. Origins are independent of extents.
The current position stays logical across mapping changes. SaveDC/RestoreDC
preserves mapping and position, not painted pixels or object-table allocation.

See [SetMapMode](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setmapmode)
and [SetWindowExtEx](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setwindowextex).

## Driver-point precision

For each axis, let `f32` round to IEEE-754 binary32:

```text
scale       = f32(viewport_extent / window_extent)
translation = f32(f32(-window_origin * scale) + viewport_origin)
product     = f32(logical_coordinate * scale)
device      = (fixed(product) + fixed(translation) + 8) // 16
```

`fixed` converts to signed 28.4, rounding exact half-unit ties away from zero.
The final integer-pixel conversion instead rounds half ties upward.
Each boundary matters: reassociating the expression or retaining Python double
precision throughout can change a boundary pixel.

`Mapping.point` is a separate LPtoDP-style integer conversion, not the driver
path above. There is no universal rounding helper for points, extent scaling,
pen realization and clip displacement.

RTL first adds `trunc((surface_width - 1) * window_extent / viewport_extent)`
to the logical X window origin, then negates the X viewport extent and origin.
The same precision stages follow. Reflecting an already-rounded translation is
not equivalent. Half-open edges additionally shift X by one device pixel.
See [layout](gdi-layout.md).

## Conversion consumers

| Consumer | Contract |
| --- | --- |
| Lines, polygons and primitive bounds | Shared driver-point conversion, followed by primitive-specific edge ownership |
| Current position | Logical coordinates, mapped when consumed |
| Pens and radial directions | Signed linear scale without translation; separate fixed-point realization |
| Clip rectangles | Realize device edges when changing the clip |
| Selected regions | Copy device-coordinate coverage; later mapping changes do not move it |
| Painted regions | Treat stored coordinates as logical; preserve source topology for framing |
| Clip offsets | Scale displacement without origins; round half ties away from zero |
| Bitmap transfers | Distinguish destination mapping from source bitmap coordinates and signed extents |

The [stroke](gdi-strokes.md), [region](gdi-regions.md) and
[bitmap transfer](gdi-dib-transfers.md) contracts describe those consumers.
[Text layout](gdi-text.md) describes font realization and text-specific mapping.

## Device metrics and playback setup

Surface size, device metrics and initial playback mapping are distinct.
The reference bitmap profile uses 271 by 203 mm, 1024 by 768 device resolution,
and 96 by 96 logical DPI. Reference generation checks the profile and stops on
a mismatch; it does not silently replace expectations. PNG dimensions do not
define physical device metrics.

The comparison harness starts in anisotropic mode with window and viewport
extents equal to the canvas dimensions. Each expected PNG supplies its canvas
size. Placeable bounds and units per inch describe placement metadata, not an
instruction to reinterpret every record as twips. Playback setup belongs to the
caller; records can subsequently change it.

[GetDeviceCaps](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-getdevicecaps)
exposes physical size, resolution and logical DPI separately.
[CreateDIBSection](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createdibsection)
does not set DC metrics from the bitmap header's pixels-per-metre fields.
