# PatBlt and ternary raster operations

ROP3 encodes an eight-entry Boolean truth table in bits 16..23, indexed by
`(P << 2) | (S << 1) | D` for each colour bit. The evaluator splits on P and
reuses two binary truth tables; all 256 functions are unit-tested against an
independent bit-by-bit oracle, including mixed RGB channel values.

PatBlt has no source bitmap. A table is source-independent exactly when flipping
S leaves every entry unchanged. The sixteen such tables reduce algebraically to
ROP2 for the existing pixel compositor. The other 240 tables leave the image
unchanged, matching native WMF playback; there is no fabricated source colour.
The operation's explicit ROP never changes or uses the DC's selected ROP2.

## Rectangle and brush semantics

- Map both logical rectangle endpoints, then order the device-space edges.
  Coverage is half-open. Negative extents do not add a one-pixel displacement.
  Zero/collapsed extents paint nothing; pen selection is irrelevant.
- Intersect painting with the image and the existing rectangular/region clip.
- Hatch brushes always supply foreground and background pixels, even with
  TRANSPARENT selected. This is a brush sampling policy for block transfers,
  not a temporary change to the DC's background mode.
- Pattern-independent operations (black, white, destination inversion and
  destination preservation) require no brush. Null brushes otherwise draw
  nothing. Hatch phase remains anchored to device space.
- The legacy low code word and the tested CAPTUREBLT/NOMIRRORBITMAP high bits
  do not change the RGB PatBlt result.

## Fixed-point coordinate boundary

The driver's affine
translation is quantized to 28.4 separately from its scaled coordinate; their
sum is then rounded to integer pixels. Reassociating the transform as
`(coordinate - window_origin) * scale + viewport_origin` and rounding only the
result loses that intermediate boundary.
Conversion to signed 28.4 uses nearest with exact ties away from zero; the
subsequent pixel conversion uses `(fixed + 8) // 16`. These are distinct rounding
stages, not a universal rounding helper.

For example, with X scale 43/128, window origin 9 and viewport origin 64,
the translation 60.9765625 becomes 61 in 28.4. Logical X=-73 contributes
-24.5234375, quantized to -24.5. The device coordinate is therefore 36.5,
rounding to pixel 37; evaluating the combined real expression would incorrectly
select pixel 36. `Mapping.device_point` models this shared conversion rather
than adding corrections to individual raster operations. `Mapping.point`
remains the separate LPtoDP-style mathematical integer conversion.

## Evidence and limits

[Microsoft's ternary-operation specification](https://learn.microsoft.com/en-us/windows/win32/gdi/ternary-raster-operations)
defines the truth-table encoding. The
[PatBlt contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-patblt)
excludes source-dependent operations. Wine's
[blit code](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/bitblt.c)
provides supporting evidence for testing source dependence algebraically;
native output determines the rectangle and hatch semantics used here.

WMF/PNG comparisons cover every truth table across solid/null and opaque/
transparent hatch brushes, signed and zero extents, fractional/reflected
mappings, clipping and alternate code words. Separate blit and state-observer
cases exercise the shared coordinate conversion.

[DIB transfers](gdi-dib-transfers.md) and [Bitmap16 transfers](gdi-bitmap16.md)
use the same Boolean evaluator with source pixels.
