# WMF layout: RTL mapping and drawing

`SETLAYOUT` accepts LTR (0), RTL (1), bitmap-orientation-preserved (8), and
their combination (9). Other bits remain explicitly unsupported. Layout is
saved with the mapping state; it does not mutate recorded coordinates, selected
objects, or pixels already drawn.

## Mapping and coordinate spaces

Enabling RTL forces `MM_ANISOTROPIC`. A subsequent map-mode setter still
establishes that mode's extents, but the effective mode remains anisotropic
while RTL is enabled. Disabling RTL does not restore the previous map mode.

At unit scale, pixel X maps to `surface_width - 1 - X`. At non-unit scale,
Windows does something less obvious: its `DC::MirrorWindowOrg` converts the
last device pixel into an integer logical displacement using signed division
with truncation, then reapplies the scale. With `v` and `w` the viewport and
window X extents:

```
last_logical = trunc((surface_width - 1) * w / v)
scale_x = -v / w
translation_x = last_logical * v / w - viewport_origin_x + window_origin_x * v / w
```

Thus the origin on a 128-pixel surface at scale 3/2 is 126, not 127. The native
`GetTransform` coefficients and `LPtoDP` observations are preserved in unit
tests. The existing 28.4 driver rounding still applies after composing this
transform. Image width is separate from viewport extent.

Different consumers retain different coordinate contracts:

- Points and path vertices use the pixel transform.
- Half-open clip/PatBlt edges add one device X unit under RTL. Clip offsets
  reflect their X displacement. Existing clip coverage stays fixed when layout
  changes.
- Selecting a region as a clip reflects its device-space edges about the
  surface width, without modifying the region object or applying logical scale.
- Shape bounds are adjusted in **logical** units before transformation.
  Native EBOX construction decrements both RTL X edges. Rectangle's wide-pen
  path enters EBOX after its own decrement, so that path adjusts them twice.
  These are native API preparation rules, not alternative rasterizers.
- Pen realization includes the signed layout transform. This matters for the
  fixed-point support contour of nonuniformly scaled wide pens.

## Clockwise curves

RTL sets clockwise traversal for Ellipse, RoundRect and the Arc family. The
orientation must enter curve construction **before** quantizing controls.
Reversing an already-rounded counterclockwise path is insufficient.

The common quarter-ellipse builder accepts a signed Y radius. Its existing
floor/ceil rules then produce the native clockwise bias naturally. For example,
the measured 28.4 first quarter of one RTL ellipse is:

```
(1856,576) -> (1856,647) -> (1713,704) -> (1536,704)
```

Simply reversing the old curve gives a control at Y=646, not 647. The signed
basis also drives partial-arc angles and preserves native starting points for
styled strokes and Pie closure. Raster fill, flattening and stroking remain
shared with LTR drawing.

## Bitmaps and brushes

On the measured WMF playback path, DIBBITBLT, DIBSTRETCHBLT and STRETCHDIB
mirror their output under RTL, including when flag 8 is also set. Do not infer
their behaviour solely from the general Win32 BitBlt documentation.
`SETDIBTODEV` reflects the destination rectangle but retains scan order.
The transfer adapter retains the distinction between pixel anchors and
half-open edges when RTL cancels a negative destination extent.

Hatch and DIB-pattern brushes retain their device-space pattern alignment.
Source-free legacy transfers use the same reflected source/destination DC and
the existing bitmap pipeline. Their identity-mapping self-copy holdouts pass
with both flags 1 and 9. The subsequent [Bitmap16 self-copy slice](gdi-bitmap16.md#self-copy-geometry)
adds overlap, fractional mapping, clipping and signed-extent holdouts, and
distinguishes same-DC rectangle preparation from the DIB anchor adjustment.

## Evidence and limits

There are 36 exact WMF/PNG cases: flags 0/1/8/9, asymmetric primitives, clipping
and layout changes, map-mode ordering, nonzero origins, SaveDC/RestoreDC, four
DIB transfer families and signed extents, fractional/negative scales, cosmetic
and wide pens, pattern brushes, regions, and source-free copies.

Windows generated only missing PNGs:
[initial batch](https://github.com/bitplane/pillow-wmf/actions/runs/35231693447),
[holdouts](https://github.com/bitplane/pillow-wmf/actions/runs/35233013914).
The separately opt-in `probe=layout` reports state and fixed-point paths:
[state](https://github.com/bitplane/pillow-wmf/actions/runs/35232144768),
[coefficients](https://github.com/bitplane/pillow-wmf/actions/runs/35232377947),
[integer paths](https://github.com/bitplane/pillow-wmf/actions/runs/35233377886),
[28.4 paths](https://github.com/bitplane/pillow-wmf/actions/runs/35233784725).
All pytest/pixel comparisons run locally or on Linux; existing goldens and
assertions were not relaxed.

The native-code inspection used Microsoft's
[26100.9444 binary](https://msdl.microsoft.com/download/symbols/win32kfull.sys/A326E51B431000/win32kfull.sys)
and [public symbols](https://msdl.microsoft.com/download/symbols/win32kfull.pdb/5CD57181BCFDC5AE8F4819BEB1196F091/win32kfull.pdb),
already obtained for HALFTONE research. Relevant RVAs are `MirrorWindowOrg`
0x14a750, Rectangle preparation 0x5dda8, and EBOX construction 0x11bd08.
Native reference runs independently validate the reconstructed behaviour.

[SetLayout documentation](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setlayout)
and [Wine's mapping tests](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/tests/mapping.c)
guided the initial probes. Wine's transform implementation alone did not
explain the measured fractional-origin quantization.

This establishes the tested non-text RTL profile, not exhaustive parity for
every layout/ROP/clip combination or extreme coordinate range. Text alignment,
bidirectional text, font mapping and glyph rendering remain the font slice.
