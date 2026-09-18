# PS_INSIDEFRAME: bounds before stroking

The [CreatePen contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen)
defines style 6 as a solid pen whose bounded figures are reduced to accommodate
the stroke. Polygon and Polyline do not receive that bounds adjustment.

Native `GetPath` measurements distinguish this from clipping an ordinary stroke
to the original box:

- Cosmetic inside-frame pens use ordinary solid-pen geometry.
- Wide inside-frame pens start with the **untrimmed** mapped box, not the usual
  exclusive right/bottom drawing bounds. Transform the full requested pen width
  to device sixteenths before halving. This is independent of the small pen's
  quantized raster silhouette.
- Arc-family angles and RoundRect corner proportions use the original logical
  box, before device-coordinate rounding. Reflection changes radial orientation,
  but scaling does not change the normalized directions or corner ratios.
- Equality is not overflow: a zero-width or zero-height interior remains a
  degenerate path, which is widened normally.
- When a logical interior dimension becomes negative, Rectangle, Ellipse and RoundRect
  fill their untrimmed figure with the pen colour. Arc, Chord and Pie instead
  fail the native drawing call without painting anything.

The overflow decision precedes mapping. Consequently a logically collapsed
interior can become slightly inverted after device bounds are rounded; do not
clamp or reorder the resulting drawing bounds. Fully collapsed closed figures
retain a pen footprint through the shared stroke machinery.

For example, box `(5,6,26,43)` and width 3 give drawing bounds
`(104,120,392,664)` in device sixteenths. Width 21 collapses the horizontal
extent to x=248; width 22 crosses the overflow boundary. The native path logs
in [run 35149207568](https://github.com/bitplane/pillow-wmf/actions/runs/35149207568)
captured this distinction and exposed the initial incorrect equality test.

The renderer passes adjusted bounds into the existing curve constructors and
uses the same polygon filling and stroke widening as other pen styles. There
is no inside-frame-specific line or curve rasterizer. Unit tests preserve
measured ellipse and arc controls; WMF atlases retain Windows-generated PNGs.
The fractional probes also corrected shared logical-angle/corner calculations,
collapsed closed-path footprints, and pen half-contour traversal. See
[stroke construction](gdi-strokes.md) for the measured frame support rules.
The manual `probe-windows-insideframe.py` checks additional exact pixels and
reports native paths, including native rejection of oversized arc-family calls.

## Odd fixed-point diameters

The four corpus coin rims exposed a distinction hidden by integer-scale probes.
[Run 35317428796](https://github.com/bitplane/pillow-wmf/actions/runs/35317428796)
measures the native paths in device sixteenths, including all six bounded
primitives with odd X, Y and XY pen diameters. Their geometry is reconstructed
by these shared rules:

- Round each full transformed pen diameter to fixed point. Inset the left,
  top and bottom by its upward-rounded half; the right uses the downward-rounded
  half. Do not round a floating-point radius independently.
- Keep the resulting upper corners and reflect them about the integer box
  centre to obtain the lower corners. Odd horizontal spans can therefore retain
  a one-unit skew; replacing them with an axis-aligned rectangle loses geometry.
- Ellipse controls retain both upper corners, then reflect the upper semicircle.
  The left and right control distances need not be identical.
- Arc and RoundRect use the box's half-edge vectors, quantized with
  `(component + 1) // 2` before trigonometry or corner scaling. Keep both vector
  components. Pie uses the corresponding origin. Consecutive arc cubics inherit
  the previous endpoint, as native BezierTo does.

For the odd-XY fixture, the adjusted bounds are `(279,279,1770,1769)`, but the
corner traversal is `(1770,279), (279,279), (278,1769), (1769,1769)`.
Its angular origin is `(1025,1024)` with horizontal vector `(746,0)` and north
vector `(1,-745)`. These are geometry calculations, not pixel corrections.
The shared stroke and fill algorithms are unchanged.

## Verification

Twenty-nine committed Windows PNG atlases cover all six bounded primitives,
solid/null brushes, thin through oversized widths, collapse boundaries,
fractional mapping, anisotropy, reflection, and unbounded Polygon/Polyline.
Eighteen additional odd-diameter PNGs and the four unchanged corpus coin pairs
cover the fractional bounds construction above. Unit tests retain native
control points as well as the exact end-to-end pixel comparisons.
The manual probe in
[run 35151984362](https://github.com/bitplane/pillow-wmf/actions/runs/35151984362)
passes 3,510 exact-pixel combinations of primitive, width, brush, box aspect
ratio and mapping, alternating copy/XOR. Another 24 native comparisons verify
collapsed Polygon footprints with both solid and inside-frame pens.

Expected PNGs remain Windows-generated and comparisons remain exact. No pixel
tolerance, fixture-specific masks or alternate rendering routes were added.

This targets the existing RGB compatible-DC profile. Palette-device dithering
described by CreatePen is not implemented, and coverage is not a claim of
exhaustive compatibility with every transform or device type.
