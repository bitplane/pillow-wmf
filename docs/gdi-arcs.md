# Arc geometry and arithmetic

An [Arc](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-arc)
is an exclusive-bound ellipse cut by two radial directions. The radial points
need not lie on the ellipse. It uses the selected pen, ignores the brush and
does not change the current position.

`ellipse.arc_cubics` normalizes radial directions against the original logical
box, then constructs the path in the adjusted device box. Normalizing rounded
device points instead changes angles under fractional mapping. The drawing box
excludes right/bottom edges and carries the shared null-pen or
[inside-frame](gdi-insideframe.md) adjustments.

## Angular arithmetic

Arctangent uses a 33-entry FLOAT table in degrees for ratios from zero to one.
Multiply the minor radial component by 32 before dividing by the major
component, interpolate, then restore the octant with one addition. Round each
operation to binary32. Retain the radial's quadrant separately from the rounded
angle: axis ownership follows coordinate signs, not `floor(angle / 90)`.

Sine and cosine use 32 intervals per quadrant. Round the absolute angle and
its product with `32/90` before selecting the quadrant and table cell. Table
entries, differences, products and sums are also binary32. Preserve the
separate evaluation orders of rising and falling cells.

If endpoint angles differ by strictly between zero and three degrees, evaluate
their sine and cosine with the degree-12 Taylor expansion instead. Every
operation still rounds to binary32; the pi constant is `0x40490fda`, one
representable value below nearest-pi. Choose this mode before unwrapping the
sweep. Equal rounded angles request a full revolution, not a short arc.

## Cubic construction

Split the counterclockwise sweep at quadrant boundaries, retaining zero-length
boundary pieces. Internal boundaries use exact axis normals even when radial
endpoints use Taylor evaluation. Full interior quadrants use the shared
[integer circle controls](gdi-curves.md#shared-circle-controls).

For terminal pieces, intersect the endpoint tangent lines `n0.T = 1` and
`n3.T = 1`, where each normal is `(cos(angle), sin(angle))`. The controls are
weighted sums `(1-w)*n + w*T`, with
`w = (4/3)*abs(cos(half_angle)) / (1+abs(cos(half_angle)))`.
Evaluate the half-angle cosine as `sin(FLOAT(half_angle + 90))`.
Every stage uses binary32; neither `n + w*(T-n)` nor the usual
`tan(sweep/4)` handle formula is equivalent at this precision.

When the determinant magnitude is at most `2**-16`, use the endpoints themselves
as the two controls. Otherwise approximate table normals can produce small
loops near cardinal boundaries; these are path geometry, not raster corrections.

Transform each relative control vector using binary32, round to device 28.4
integers with half ties away from zero, then add the integer centre. Rounding
absolute coordinates would make ties depend on translation. Each cubic inherits
its predecessor's actual endpoint.

## Painting and coverage

[Chord](gdi-chords.md) and [Pie](gdi-pies.md) share the arc constructor and only
change closure. Flattening, widening, GIQ endpoint ownership, clipping and
[ROP2 composition](gdi-rop2.md) are shared with other paths.

See [arc tests](../test/unit/wmf/test_arcs.py) and
[precision tests](../test/unit/wmf/test_arc_precision.py) for exact controls,
tiny loops, cardinal boundaries, reflections and large coordinates. WMF/PNG
comparisons exercise sweeps, elliptical bounds, pen styles and fractional
mapping. Coverage targets the reference memory DC, not every device or input.
