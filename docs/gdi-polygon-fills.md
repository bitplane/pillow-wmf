# Polygon fill: first compatibility slice

`RasterContext.polygon` now maps the record's logical points to device points,
fills the closed contour using the default alternate rule, then strokes the
same closed contour. The operation does not use or update the current position.
The fill and stroke use the existing fixed-point path machinery; this slice
does not add a polygon-specific rasterizer.

Windows documents [automatic closure and current-position behavior][polygon]
and describes [alternate fill as odd ray crossings][regions]. The current
`geometry.contains` test counts crossings at integer device-pixel positions,
ignores horizontal edges, and owns a crossing on one end of an edge only. That
half-open convention avoids counting a shared vertex twice.

The Windows references for `polygon-concave-fill`, `polygon-slanted-forward`,
`polygon-slanted-reversed`, and `polygon-slanted-half-scale` match pixel for
pixel. `polygon-wide-outline` also matches, exercising the shared geometric
stroker around a closed polygon. These fixtures cover concavity, sloped edges,
orientation reversal, half-scale mapping, and a wide outline. They are evidence
for this slice, not a claim about all polygon edge configurations.

The winding rule, explicit `SetPolyFillMode`, and multi-contour `PolyPolygon`
remain separate failing compatibility cases. Their fill semantics need a
shared contour-level rule rather than filling each polygon independently.

[polygon]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-polygon
[regions]: https://learn.microsoft.com/en-us/windows/win32/gdi/filling-regions
