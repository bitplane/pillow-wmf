# GDI strokes

Lines, polylines, polygons, rectangles and curves share one device-path pipeline.
`DevicePath` retains line/cubic commands and device sixteenths through stroke
construction. Cosmetic strokes use Grid Intersection Quantization (GIQ); wide
strokes sweep a realized polygonal pen along the path.

Microsoft documents the [cosmetic/geometric distinction](https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-lineattrs),
[logical pen widths](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen)
and [28.4 device paths](https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-pathobj).
The implementation targets the project's true-colour memory-DC profile, not
arbitrary world transforms, pen join/cap styles or display drivers.

## Cosmetic lines

The rounded device X width selects a hairline when it is at most one; logical
width zero always selects it. Changing only the Y scale does not widen an
otherwise cosmetic pen.

For each major-axis grid intersection, choose the nearest minor-coordinate
pixel, resolving half ties toward the smaller coordinate. Intersect the
segment with that pixel's half-pixel diamond. Emit a pixel only when the segment
visits and exits the diamond; an endpoint inside it is excluded.

Diamond membership follows the GIQ rules in Intel's
[Broadwell PRM, volume 7, pages 593–594](https://www.x.org/docs/intel/BDW/intel-gfx-prm-osrc-bdw-vol07-3d_media_gpgpu_0.pdf):
edges are outside except the bottom corner, the right corner (left for slope
+1), and the bottom-left/right edges for slopes +1/-1 respectively. A shared
vertex is not universally owned by the following segment. Zero-length cosmetic
segments paint nothing.

The same algorithm accepts integer LineTo coordinates and fractional curve
vertices. Bound grid enumeration by the bitmap without moving the original
endpoints or changing their rounding phase. [Styled pens](gdi-styled-pens.md)
advance through the complete unclipped span.

`Polyline` maps its point array once and does not use or update the current
position. Repeating its first point adds a final segment; it does not request
a closed figure.

## Pen realization

Circular device pens with rounded widths 1 through 6 have discrete half-pixel
silhouette tables. For CreatePen, test circularity after quantizing both full
transformed diameters to 28.4, rather than comparing the original scales.

Other pens use a cubic semicircle and its central reflection. Quantize full
diameters before halving outward. Preserve the first transformed basis vector's
orientation when constructing [circle controls](gdi-curves.md); reflection can
change a boundary vertex by one fixed unit.

For CreatePen, a diameter of at most 8 fixed units selects a diamond with that
axis replaced by a one-pixel diameter, provided every half-basis component is
below 4096 fixed units. Larger pens bypass thickening and retain their subpixel
cubic silhouette. Geometric frame pens also retain subpixel axes. Enlarging a
cubic ellipse is not equivalent to selecting the diamond.

The stored half-contours retain their terminal vertices. Support searches and
forward walks omit repeated terminals; reverse join walks visit them.
Deduplicating the halves into a ring loses seam ownership.

## Widening and joins

Select support by bisecting edge cross-product signs on a semicircle bracketed
by reflected seam neighbours. A global support maximum is not equivalent when
fixed-point flattening produces collinear edges. Use the same search for every
stroke; a wholly zero-length wide stroke uses a horizontal surrogate direction.

Opposite support vertices supply the two body offsets, rounded to half pixels.
At integer centres, intermediate cap vertices inset by one fixed unit toward
zero; fractional centres retain their offsets. Traverse the appropriate half
of the pen at each open endpoint. Zero-length wide segments retain both caps.

Connected segments add the exterior wedge between support vertices. Round
joins traverse the pen contour, including a half-contour at a 180-degree
reversal. Turn direction compares product signs before magnitudes, retaining
the factors' signs even for zero products. A zero cross product alone cannot
choose the contour walk for an axial reversal; that choice controls seam
ownership and can change a boundary pixel. Miter joins intersect the two offset segment lines. Curve segments
retain endpoint tangents through [flattening](gdi-curves.md).

Direct Rectangle uses mitered corners. Recording a Rectangle in a path and
widening that path instead uses the selected pen's round joins. For direct
frames, horizontal support offsets own half-step ties toward zero; vertical
support retains the round stroker's outward tie.

Wide stroke coverage is unioned before painting. Cosmetic strokes retain
repeated pixel visits. Fill/stroke ordering and mix behaviour are described in
[ROP2 painting](gdi-rop2.md).

## Clipping and tests

The application clip retains device-coordinate constraints outside the bitmap;
discarding them loses information needed by OffsetClipRgn. Save/restore keeps
immutable clip state. All primitives use the same final pixel-write clip.

Exact tests cover realized pen contours, support-edge ties, fractional cap
origins, collapsed axes, the thickening size guard and connected joins. See
[pen realization](../test/unit/wmf/test_pen_realization.py) and
[stroke edges](../test/unit/wmf/test_stroke_edges.py). WMF/PNG comparisons run
locally or on Linux; Windows is only the oracle for new references and targeted
path measurements.
