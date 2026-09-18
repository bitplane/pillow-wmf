# Polygon and PolyPolygon fills

`PolyPolygon` rejects the whole operation if any contour has fewer than two
points. Validate before painting: omitting only the short contour incorrectly
draws the others. A two-point contour is accepted, even though it has no fill
area. Rejected calls leave the current position and selected drawing state
unchanged.

`RasterContext` maps each record's logical points to device paths. `Polygon`
provides one contour; `PolyPolygon` provides several. It fills all contours in
one pass using the selected alternate or winding rule, then strokes each
closed contour. Neither operation uses or updates the current position.
The fill and stroke use the existing fixed-point path machinery, without a polygon-specific rasterizer.

Windows documents [automatic closure and current-position behavior][polygon]
for `Polygon` and the same [contour closure for `PolyPolygon`][polypolygon],
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
The `poly-polygon-disjoint`, nested, and overlapping references match under
both fill modes, including reversed inner-contour orientation. These cases
exercise the shared fill rules, not a claim about all polygon edge
configurations.

Filling contours independently would lose holes and overlapping-region
semantics. `geometry.contains` instead accumulates crossings over every
contour before deciding whether a pixel is covered.

[polygon]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-polygon
[polypolygon]: https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-polypolygon
[regions]: https://learn.microsoft.com/en-us/windows/win32/gdi/filling-regions
