# Solid GDI stroke reconstruction

The renderer uses a shared device-path pipeline for lines, polylines, polygons,
rectangles and ellipses. This replaces the former kernel stamping,
identity-only distance fill, hand-constructed diagonal outlines, and
narrow-ellipse pixel correction.
There is no ImageDraw fallback.

## Evidence and scope

The rules below are a behavioral reconstruction from the native Windows oracle,
not a claim to possess Microsoft's implementation. Microsoft documents the
[cosmetic/geometric distinction](https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-lineattrs),
[logical pen widths](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen),
and [device paths with world-space geometric widening](https://learn.microsoft.com/en-us/windows/win32/api/winddi/nf-winddi-engstrokepath).
Its [PATHOBJ documentation](https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-pathobj)
describes 28.4 coordinates and Grid Intersection Quantization (GIQ).

Wine's [DIB pen renderer](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dibdrv/objects.c)
and [path widening](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/path.c)
are useful comparisons, but are independent implementations. We did not copy
their source or assume that their output defines the Windows oracle.

Native runs:

- [35078466384](https://github.com/bitplane/pillow-wmf/actions/runs/35078466384):
  756 cases covering widths, slopes, anisotropic transforms and reversed endpoints.
- [35079183632](https://github.com/bitplane/pillow-wmf/actions/runs/35079183632):
  3,042 cases, adding reflection, circular scaling, shrinking, and zero-length strokes.
- [35081003802](https://github.com/bitplane/pillow-wmf/actions/runs/35081003802):
  63 additional WMF/PNG cases, including all-octant fans, fractional pen thresholds,
  wide shape outlines, degenerate shapes and clipping. The original 63 PNGs remain.
- [35081379675](https://github.com/bitplane/pillow-wmf/actions/runs/35081379675):
  closed-path outlines to distinguish joins from independent segment caps.

The 3,042 direct native line images match the replacement renderer exactly.
The committed WMFs test actual metafile playback as well as the recorder and
codec. These results cover the current solid/null pen slice; they do not claim
complete GDI support, arbitrary world transforms, other join/cap styles, ROPs,
or exhaustive coverage of every width and coordinate.

## Pipeline

1. Mapping resolves device coordinates. `DevicePath` retains line/cubic commands
   and sixteenths of a pixel through stroke construction. Subdivided cubics
   retain endpoint tangent directions for pen support.
2. Pen realization selects a cosmetic hairline or constructs one polygonal pen
   from the logical width and mapping.
3. Cosmetic segments use GIQ. Wide segments sweep the realized pen along the
   segment, with support vertices selected by a cross-product maximum.
4. Connected segments add their exterior joins; only open endpoints get caps.
   Repeated vertices do not introduce spurious joins or cap directions.
   Filled paths and wide stroke
   polygons use the same fixed-point coverage test.
5. Stroke coverage is unioned per drawing call; pixel writes apply the
   application clip and the selected [ROP2 mix](gdi-rop2.md).

## Cosmetic lines

The rounded device X width selects the hairline case when it is at most one;
logical width zero always selects it. Changing only the Y scale does not widen
an otherwise cosmetic pen.

For each major-axis grid intersection, choose the nearest minor-coordinate
pixel, resolving a half tie toward the smaller coordinate. Intersect the
segment with that pixel's half-pixel diamond. A pixel is emitted only when the
segment visits and exits the diamond; an endpoint inside it is excluded.
Diamond membership follows the legacy GIQ rules in Intel's
[Broadwell PRM, volume 7, printed pages 593–594](https://www.x.org/docs/intel/BDW/intel-gfx-prm-osrc-bdw-vol07-3d_media_gpgpu_0.pdf):
edges are outside except the bottom corner, the right corner (left for slope
+1), and the bottom-left/right edges for slopes +1/-1 respectively.
The implementation clips in rotated coordinates and tests exact membership;
it does not use an epsilon or adjust pixels after stroking.

[Windows run 35096891899](https://github.com/bitplane/pillow-wmf/actions/runs/35096891899)
verifies fractional segment coordinates before stroking and records their
pixels. A shared vertex is **not** universally owned by the following segment.
Correct boundary ownership removes both the former Arc endpoint patch and
the dashed-ellipse phase correction. Existing PNG expectations are unchanged.

The same algorithm accepts integer LineTo coordinates and fractional curve
vertices. Grid enumeration is bounded by the bitmap dimension, without moving
the original endpoints or changing their rounding phase. A zero-length cosmetic
segment paints nothing.

`Polyline` maps its point array once and strokes the connected open path. It
does not use or update the current drawing position. Explicitly repeating its
first point creates a final segment, rather than requesting a closed polygon.
Zero-length segments and joins pass through the same stroke machinery; empty
join wedges add no pixels.

## Polygonal pens and wide strokes

Circular device pens with rounded widths 1 through 6 have discrete native
silhouettes. Their half-pixel vertex tables are pen realization data: all slopes
and primitives consume the same shapes. Uniform scaling can select another
silhouette; for example, a logical width of 3 at half scale selects the width-2
device silhouette. For CreatePen, circularity is tested after quantizing both
transformed diameters to 28.4, not by comparing the original mapping scales.
The slightly unequal scales of the corpus penny and quarter therefore select
the width-3 table: their fixed diameters are both 44.

Other pens are constructed from a cubic semicircle and its central reflection.
The stored half-contours retain their terminal vertices. Support searches and
forward walks omit the repeated terminals; reverse join walks visit them.
This directional traversal matters when a seam's unrounded pen coordinate
differs from its rounded body support. Deduplicating the two halves into a ring
loses that boundary vertex. Native widened nearly-collapsed arcs in
[run 35151070145](https://github.com/bitplane/pillow-wmf/actions/runs/35151070145)
expose the distinction; the measured join is retained as a unit test.
The transformed diameters are quantized to 28.4 units before halving outward.
For CreatePen, a diameter of at most 8 fixed units (half a pixel) selects a
diamond contour with that axis replaced by a one-pixel diameter. It does not
construct a cubic ellipse at the enlarged thickness. Larger subpixel diameters
keep the ordinary cubic contour. Geometric frame pens retain subpixel axes.
Cubic control quantization preserves the orientation of the transformed first
basis vector; reflection
can consequently change a boundary vertex by one fixed-point unit.

This construction is inferred from the native `pen-radius-probe-*` PNGs and
the [pen-support probe](https://github.com/bitplane/pillow-wmf/actions/runs/35311068688).
The latter measures widened contours in exact device sixteenths and verifies
direct LineTo against WidenPath/FillPath. Diameter-first rounding changes the
`corpus-fdo39256-2.wmf` pen radii from (23, 23) to (22, 23)
fixed units, resolving its nine differing pixels. Applying that rounding without
collapsed-axis replacement regresses `corpus-lady4.wmf` by 104 pixels. A blanket
one-pixel minimum instead regresses the existing fractional inside-frame curves.
Both failures distinguish the measured collapse rule from a clamp. The synthetic
PNGs cover solid and inside-frame pens around fractional-radius boundaries,
collapsed axes and fixed-point circularity. Retaining logical stroke directions
instead was rejected because it regressed other native
references; endpoint mapping and support selection remain unchanged.

The original collapse measurements used a short major axis, for which cubic
flattening also produced a diamond. The `screwdrv` corpus polygon distinguishes
the constructions: enlarging its ellipse before flattening adds shoulder
vertices and five unwanted pixels along shallow edges.
[Polygon-support run 35321454120](https://github.com/bitplane/pillow-wmf/actions/runs/35321454120)
measures the native diamond at multiple aspect ratios, solid/inside-frame styles
and reflected mapping, alongside the ordinary contours just above the collapse
boundary. Native centreline coordinates already matched. Only pen realization
changes; support selection, body rounding, joins and scan conversion are shared.
Unit tests retain exact native contours, and the unchanged `corpus-screwdrv`
pair and `pen-collapsed-shallow-fan` guard the resulting pixels. Six additional
`pen-radius-probe` PNGs retain steeper-angle and adjacent-contour holdouts.

Against the 3,367 existing native corpus pairs at data-repository commit
`4abfe2a`, this realization change increases exact matches from 3,305 to 3,326,
leaving 24 pixel differences and 17 font-creation failures. No previously exact
image regresses and no remaining pixel difference increases.

Cubic flattening uses integer hybrid forward differencing with a near-half-pixel
error bound. The shifts used when changing step size matter: exact midpoint
subdivision can choose the same samples but round them differently. See
[the curve algorithm and native evidence](gdi-curves.md).

For segment vector `(dx, dy)`, maximize `px * dy - py * dx` over the pen's
vertices. The opposite vertex gives the other side. The two body offsets round
to half pixels. At integer centers, intermediate cap vertices inset by one
fixed-point unit toward zero; fractional centers retain their offsets.
Traverse the relevant half of the same pen contour at each open endpoint.
No slope, width, or transform chooses a different line-body algorithm.

Equal-support vertices preserve half-contour traversal order: visit the
reflected half backwards, then the original half forwards, retaining the first
maximum. This is one contour-index rule for every pen, independent of screen
axes and vertex count. The former X/Y preference by shape failed at the seams.
[Run 35104558437](https://github.com/bitplane/pillow-wmf/actions/runs/35104558437)
captures native support choices around every edge of six pen shapes, including
the seams. The traversal model also passes all **846** native pixel comparisons
in [run 35104948443](https://github.com/bitplane/pillow-wmf/actions/runs/35104948443),
which adds widths 9, 12 and 17, and checks slopes on either side of each tie and
three subpixel origins. This is a reconstruction of observable ordering, not
a claim about Microsoft's internal search implementation.

Wide zero-length segments retain their two caps and paint the native pen
footprint. Connected segments add the exterior wedge between their support
vertices. Round joins traverse the intervening pen contour; miter joins intersect
the two offset segment lines.

Direct `Rectangle` drawing uses square (mitered) corners. Recording a Rectangle
in a path and calling WidenPath instead exposes the selected pen's round joins;
those two native operations must not be conflated. Rectangle requests mitered
joins from the shared stroker; Ellipse requests round joins.
For these direct frames, horizontal support offsets own exact half-step ties
toward zero, while vertical support retains the round stroker's outward tie.
Non-ties use the same half-pixel quantization. This is the measured direct-frame
contract, not a claim about arbitrary ExtCreatePen miter paths.

## Clipping

The application clip retains its device-coordinate rectangle constraints,
including portions outside the current bitmap. Trimming it when selected loses
information needed by a later OffsetClipRgn. Its immutable representation can
be saved/restored without a bitmap-sized set or mutable aliasing. Every primitive
uses the same final pixel-write clip.

## Re-running the measurements

On Windows, `python scripts/probe-windows-strokes.py` compares the matrix directly
against native GDI and fails on any differing pixel. Add `--dump-paths` to print
geometry and native raster observations to the log instead. There are no
per-fixture metadata files.

The Windows workflow runs this larger matrix only on manual dispatch. Ordinary
reference updates retain the missing-PNG rule and the native device-profile
check. Local `make test-all` uses the committed PNGs and needs no Windows access.
