# GDI `Arc` rasterization

`META_ARC` has an exclusive-bound ellipse rectangle and two points on radial
lines. The radial points need not lie on the ellipse. Windows uses the current
pen, never the brush, and does not update the current position. Equal start and
end points draw the complete ellipse. See the [WMF Arc record](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/742097b4-5879-4c36-b57e-77e7cc152253)
and [GDI Arc contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-arc).

The native path probes in `scripts/probe-windows-arcs.py` establish the raster
construction. GDI normalizes the radial directions against the untrimmed
device rectangle, then excludes the right and bottom edges from the drawn
ellipse. It divides the counterclockwise sweep at quadrant boundaries and
builds a cubic for each part. Generated controls are rounded to 28.4 fixed
point *before* cubic flattening. Complete quadrants use the same control
geometry as `Ellipse`. `Arc`, `BeginPath`/`Arc`/`StrokePath`, and the explicitly
flattened path produced identical pixels in the native probes. This is also
consistent with [Wine's path construction](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/path.c),
although Windows reference PNGs remain the compatibility oracle.

At a top or right cardinal radial, the native open path's terminal pixel is
owned by the following cubic; the initial pixel is not. The raster context
applies this edge-ownership rule after the shared stroke routine. It does not
alter interior curve coverage or apply a fixture-specific correction.

The initial solid/cosmetic, dashed, reflected, full-ellipse, and current-position
cases match the Windows references. `arc-pen-styles` remains red by five pixels
on its width-3 arc. A wide `Polyline` through the native flattened vertices
matches exactly, while the native `WidenPath` contour identifies the difference
at fractional curve vertices around a shallow top segment and its end cap.
This is a geometric-pen widening problem, not arc direction or radial selection.
The exact test remains enabled as a ratchet.
