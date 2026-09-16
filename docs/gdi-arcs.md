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
point *before* cubic flattening. Complete quadrants use the same control
geometry as `Ellipse`. `Arc`, `BeginPath`/`Arc`/`StrokePath`, and the explicitly
flattened path produced identical **cosmetic** pixels in the native probes. This is also
consistent with [Wine's path construction](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/path.c),
although Windows reference PNGs remain the compatibility oracle.

Endpoint coverage comes entirely from the [shared GIQ rasterizer](gdi-strokes.md#cosmetic-lines).
The previous radial-coordinate-based endpoint adjustment was incorrect: moving
a radial point farther along the same ray could change its pixels. The
adjustment is removed and radial-distance invariance has regression tests.

The initial solid/cosmetic, dashed, reflected, full-ellipse, and current-position
cases match the Windows references. `arc-pen-styles` remains red by five pixels
on its width-3 arc. A wide `Polyline` through the native flattened vertices
matches exactly, but rounds away the subpixel geometry and is not an equivalent
path. [Run 35097237187](https://github.com/bitplane/pillow-wmf/actions/runs/35097237187)
shows that native wide `StrokePath` changes four pixels after `FlattenPath`,
even though cosmetic strokes do not. Cubic information must survive until
widening; matching flattened vertices alone does not establish a correct wide
stroke. One additional pixel differs at the end cap.
The exact test remains enabled as a ratchet.
