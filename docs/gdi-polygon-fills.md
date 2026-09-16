# Polygon fill: first compatibility slice

`RasterContext.polygon` maps the record's logical points to device points,
fills the closed contour using the selected alternate or winding rule, then
strokes the same closed contour. The operation does not use or update the current position.
The fill and stroke use the existing fixed-point path machinery; this slice
does not add a polygon-specific rasterizer.

Windows documents [automatic closure and current-position behavior][polygon]
and describes [alternate and winding fill as ray-crossing rules][regions].
`geometry.contains` counts directed crossings at integer device-pixel positions,
ignores horizontal edges, and owns a crossing on one end of an edge only. That
half-open convention avoids counting a shared vertex twice. Alternate mode
uses count parity; winding mode tests for a nonzero count. `SetPolyFillMode`
selects that rule in the saved DC state. Internal stroke masks always use the
alternate rule, independently of the selected brush fill mode.

The Windows references for `polygon-concave-fill`, `polygon-slanted-forward`,
`polygon-slanted-reversed`, and `polygon-slanted-half-scale` match pixel for
pixel. `polygon-wide-outline` also matches, exercising the shared geometric
stroker around a closed polygon. These fixtures cover concavity, sloped edges,
orientation reversal, half-scale mapping, and a wide outline. The two
`polygon-double-wound` references distinguish alternate from winding mode.
These cases are evidence for the implemented slice, not a claim about all
polygon edge configurations.

Multi-contour `PolyPolygon` remains a separate failing compatibility case. Its
fill must evaluate all contours together, rather than painting each contour
independently.

[polygon]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-polygon
[regions]: https://learn.microsoft.com/en-us/windows/win32/gdi/filling-regions
