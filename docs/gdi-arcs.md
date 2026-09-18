# GDI `Arc` rasterization

`META_ARC` has an exclusive-bound ellipse rectangle and two points on radial
lines. The radial points need not lie on the ellipse. Windows uses the current
pen, never the brush, and does not update the current position. Equal start and
end points draw the complete ellipse. See the [WMF Arc record](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/742097b4-5879-4c36-b57e-77e7cc152253)
and [GDI Arc contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-arc).

The native path probes in `scripts/probe-windows-arcs.py` measure the following
construction for the tested cases. GDI normalizes radial directions against the untrimmed
logical rectangle, preserving reflection, then excludes the right and bottom edges from the drawn
ellipse. It divides the counterclockwise sweep at quadrant boundaries and
builds a cubic for each part. Generated controls are rounded to 28.4 fixed
point *before* cubic flattening. Intermediate quadrants use the same control
geometry as `Ellipse`; the first and last pieces use the tangent-intersection construction below,
even when they span almost a whole quadrant. `Arc`, `BeginPath`/`Arc`/`StrokePath`, and the explicitly
flattened path produced identical **cosmetic** pixels in the native probes. This is also
consistent with [Wine's path construction](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/path.c),
although Windows reference PNGs remain the compatibility oracle.
Fractional [inside-frame probes](gdi-insideframe.md) distinguish logical radial
normalization from normalization after integer device mapping; the latter loses
angle precision. Drawing bounds are still constructed in device space.
Odd inside-frame diameters require the box's rounded half-edge vectors rather
than independent X/Y radii; see the [fixed-point box construction](gdi-insideframe.md#odd-fixed-point-diameters).
Each cubic starts at its predecessor's actual endpoint, including transitions
between a trigonometric terminal piece and a canonical ellipse quadrant.

Endpoint coverage comes entirely from the [shared GIQ rasterizer](gdi-strokes.md#cosmetic-lines).
The previous radial-coordinate-based endpoint adjustment was incorrect: moving
a radial point farther along the same ray could change its pixels. The
adjustment is removed and radial-distance invariance has regression tests.

## Wide paths

[Run 35097237187](https://github.com/bitplane/pillow-wmf/actions/runs/35097237187)
shows that native wide `StrokePath` changes four pixels after `FlattenPath`,
even though cosmetic strokes do not. `DevicePath` therefore retains line and
cubic commands. Subdivided cubics keep their endpoint tangents for pen support;
a single-chord cubic uses its chord. All commands then use the same stroke
bodies, endpoint caps, joins, and scan converter. Internal vertices receive
joins, not additional round caps. Repeated vertices do not interrupt joins.

[Run 35098165992](https://github.com/bitplane/pillow-wmf/actions/runs/35098165992)
also measures the cap at every subpixel origin: integer centers inset cap
vertices by one fixed-point unit; fractional centers retain them unchanged.
This accounts for the fifth pixel in the original wide-Arc failure.

Copy-mode combined fill/stroke processing flattens the contour before stroking
when a brush participates. With a null brush, cubic tangents survive. This is measured
with both direct Ellipse and StrokeAndFillPath in
[run 35098803927](https://github.com/bitplane/pillow-wmf/actions/runs/35098803927),
and is handled at the shared painting operation, not by an Ellipse rasterizer.
The [Pie composition probes](gdi-pies.md) extend this result: non-copy ROP2
modes retain the cubic tangents even when a brush participates.

## Angular arithmetic and handle construction

Large path-only probes expose arithmetic that a small bitmap conceals. They
allocate no large images: `GetPath` reads the already-constructed device path
through an inverse mapping that reports its original sixteenths of a pixel.

[Run 35105051057](https://github.com/bitplane/pillow-wmf/actions/runs/35105051057)
exposes sine/cosine interpolation at 128 intervals per revolution and arctangent
interpolation at 32 intervals of the reduced ratio `[0, 1]`. The former
`atan2`/`sin`/`cos` construction was mathematically smoother, but not compatible.
`gdi_math.py` generates these mathematical tables; there are no fixture-specific
values or pixel corrections.

Lookup precision applies **before** quadrant reduction. Normalize the degree
angle to `[0, 360)`, store it as FLOAT, multiply by the FLOAT representation of
`32/90`, and store that full-circle table position as FLOAT. Only then fold the
position into the first quadrant. Interpolated results also use FLOAT storage.
[Run 35111628013](https://github.com/bitplane/pillow-wmf/actions/runs/35111628013)
checks five explicit `AngleArc` input angles near cardinal boundaries, bypassing
radial angle conversion and exposing this lookup precision independently.

Folding the angle in double precision before lookup had left one tiny ellipse
loop with a wrong control point and flattened vertex. Its unrounded control X
was `1001.5203`; native lookup precision produces about `1001.4937`, crossing the
fixed-point rounding boundary. The handle is now `(1001, 1776)` and FlattenPath
emits `(1005, 1776)`, exactly as Windows does. Translated and reflected path
captures in [run 35111160259](https://github.com/bitplane/pillow-wmf/actions/runs/35111160259)
confirm that this difference originates before device-coordinate translation.

The reconstruction reduces the radial slope for arctangent lookup, stores that
result at FLOAT precision, and restores quadrants. Degree conversion retains
the previously measured FLOAT-pi convention. Nearly equal radial directions
can become equal at this precision and request a full revolution. Cardinal
boundary pieces remain in the path, including a zero-length terminal piece
when the sweep ends exactly on a boundary.

For unequal endpoint angles separated by less than **three degrees**, endpoints
use high-precision trigonometry followed by FLOAT storage. This selection is
made before unwrapping the counterclockwise sweep. The switch is measured,
not an epsilon added to make pixels pass:
[run 35106971946](https://github.com/bitplane/pillow-wmf/actions/runs/35106971946)
records different native ten-degree endpoints at sweeps 2.9999 and 3.0, and
the same table mode at 3.0001. Half-angle weights still use the lookup table.

For terminal-piece endpoint normals `n0 = (cos(a), sin(a))` and
`n3 = (cos(b), sin(b))`, intersect the two lines `n0.T = 1` and `n3.T = 1`.
Both handles move from their endpoint toward `T` by the fraction
`4*cos((b-a)/2) / (3*(1+cos((b-a)/2)))`. With exact trigonometry this agrees
with the familiar tangent-length formula. With interpolated trigonometry it
does not: endpoint normals need not have exactly unit length. This explains
both the ordinary one-unit control differences and the native tiny loops near
cardinal boundaries. No Arc-specific endpoint or raster-pixel adjustment is
needed. A zero determinant retains a degenerate cubic.

## Verification and limits

The regression suite includes six native atlases (96 arcs): all octants,
short and wrapping sweeps, circular and elliptical bounds, widths 1/3/6, and
near/far points on identical rays. The old PNG expectations remain unchanged.
This is measured compatibility coverage, not a claim of exhaustive GDI parity.

Expanded edge probes initially found **85 pixel failures in 360 Arc cases**.
The reconstruction passes all 360, plus **64 independent holdout cases** across
the precision boundary, reversed sweeps, all quadrants, circular/elliptical
bounds and widths 1/7, in
[run 35107084015](https://github.com/bitplane/pillow-wmf/actions/runs/35107084015).
The `arc-edge-*` WMFs preserve full-size Windows PNG regressions because small
atlas cells can conceal control differences. No old expectations changed.

This remains a behavioral reconstruction, not Microsoft's source algorithm.
All tested pixels match, but arbitrary control-point bit equality is not
claimed. The edge probe now also asserts exact consumed vertices for all 120
captured paths, including the formerly mismatching tiny loop. Unit tests assert
its exact handles and flattened vertices, plus native lookup values from the
explicit FLOAT-angle experiments. These checks and the existing pixel matrices
pass in [run 35111971038](https://github.com/bitplane/pillow-wmf/actions/runs/35111971038).
Very large path-only measurements still
expose differences in some raw coordinates; the remaining angle and transform
arithmetic is not claimed to be bit-exact at every scale. Those measurements
remain diagnostic evidence for future work.
