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
convert the last device pixel into an integer logical displacement using signed
division with truncation, then reapply the scale. With `v` and `w` the viewport and
window X extents:

```
last_logical = trunc((surface_width - 1) * w / v)
scale_x = -v / w
translation_x = FLOAT(FLOAT(-(window_origin_x + last_logical) * FLOAT(scale_x)) - viewport_origin_x)
```

Thus the origin on a 128-pixel surface at scale 3/2 is 126, not 127. The native
`GetTransform` coefficients and `LPtoDP` observations are preserved in unit
tests. Scale, origin multiplication and translation addition each round to binary32;
28.4 driver rounding follows transform composition. Image width is separate from viewport extent.

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
  FrameRegion and ordinary pens share `Mapping.linear_scale`; the
  [object-state tests](gdi-object-lifetime.md) cover reflected fractional
  frame footprints, including negative viewport extents.

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

Simply reversing a counterclockwise curve gives a control at Y=646, not 647. The signed
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
Source-free legacy transfers use the same reflected source/destination DC and the [shared bitmap pipeline](gdi-bitmap16.md#self-copy-geometry).
Same-DC rectangle preparation is distinct from the DIB anchor adjustment.

## Scope and references

[SetLayout documentation](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setlayout)
and [Wine's mapping tests](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/tests/mapping.c)
describe the API and related mapping behaviour. Exact comparisons against the
reference DC determine the pixel contract.

This establishes the tested non-text RTL profile, not exhaustive parity for
every layout/ROP/clip combination or extreme coordinate range. Text alignment,
bidirectional text, font mapping and glyph rendering remain the font slice.
