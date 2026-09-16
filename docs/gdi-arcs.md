# GDI `Arc` rasterization

`META_ARC` has an exclusive-bound ellipse rectangle and two points on radial
lines. The radial points need not lie on the ellipse. Windows uses the current
pen, never the brush, and does not update the current position. Equal start and
end points draw the complete ellipse. See the [WMF Arc record](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/742097b4-5879-4c36-b57e-77e7cc152253)
and [GDI Arc contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-arc).

The native path probes in `scripts/probe-windows-arcs.py` measure the following
construction for the tested cases. GDI normalizes radial directions against the untrimmed
device rectangle, then excludes the right and bottom edges from the drawn
ellipse. It divides the counterclockwise sweep at quadrant boundaries and
builds a cubic for each part. Generated controls are rounded to 28.4 fixed
point *before* cubic flattening. Intermediate quadrants use the same control
geometry as `Ellipse`; the first and last pieces use the trigonometric cut,
even when they span almost a whole quadrant. `Arc`, `BeginPath`/`Arc`/`StrokePath`, and the explicitly
flattened path produced identical **cosmetic** pixels in the native probes. This is also
consistent with [Wine's path construction](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/path.c),
although Windows reference PNGs remain the compatibility oracle.

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

Combined fill/stroke processing flattens the contour before stroking when a
brush participates. With a null brush, cubic tangents survive. This is measured
with both direct Ellipse and StrokeAndFillPath in
[run 35098803927](https://github.com/bitplane/pillow-wmf/actions/runs/35098803927),
and is handled at the shared painting operation, not by an Ellipse rasterizer.

## Precision model and limits

[Run 35099322489](https://github.com/bitplane/pillow-wmf/actions/runs/35099322489)
records original 28.4 controls in all quadrants and under reflections. It
distinguishes terminal pieces from intermediate quadrants, including tiny
pieces that quantize to a repeated point at cardinal boundaries. Converting
the radial angle to degrees using single-precision pi reproduces this
ownership. That floating-point model is a behavioral inference, **not** a
claim to know Microsoft's internal constant or implementation. We do not use
an angle tolerance to reclassify pieces or patch their resulting pixels.

Very short terminal pieces can have different native control handles despite
identical flattened geometry. The diagnostic logs those control differences
and asserts exact equality of the consumed vertices (ignoring repeated
zero-length edges); the PNG tests independently require exact pixels. Native
control equality is asserted for the specific quadrant regressions measured
in the unit tests, not claimed for every Arc parameterization.

The regression suite includes six native atlases (96 arcs): all octants,
short and wrapping sweeps, circular and elliptical bounds, widths 1/3/6, and
near/far points on identical rays. The old PNG expectations remain unchanged.
This is measured compatibility coverage, not a claim of exhaustive GDI parity.
