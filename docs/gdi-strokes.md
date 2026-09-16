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

1. Mapping resolves device coordinates. The path retains sixteenths of a pixel
   through cubic flattening and stroke construction.
2. Pen realization selects a cosmetic hairline or constructs one polygonal pen
   from the logical width and mapping.
3. Cosmetic segments use GIQ. Wide segments sweep the realized pen along the
   segment, with support vertices selected by a cross-product maximum.
4. Connected segments add their exterior joins. Filled paths and wide stroke
   polygons use the same fixed-point coverage test.
5. Stroke coverage is unioned per drawing call; pixel writes apply the
   application clip and the selected [ROP2 mix](gdi-rop2.md).

## Cosmetic lines

The rounded device X width selects the hairline case when it is at most one;
logical width zero always selects it. Changing only the Y scale does not widen
an otherwise cosmetic pen.

For each major-axis grid intersection, choose the nearest minor-coordinate
pixel, resolving a half tie toward the smaller coordinate. Intersect the
segment with that pixel's half-pixel diamond. The segment owns the pixel when
it exits the diamond before its endpoint. A shared vertex belongs to the next
segment; this matters where flattened ellipse segments meet on a diamond edge.

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
device silhouette.

Other pens are constructed from a cubic semicircle and its central reflection.
The transformed radii are quantized to 28.4 units. Cubic control quantization
preserves the orientation of the transformed first basis vector; reflection
can consequently change a boundary vertex by one fixed-point unit.

Cubic subdivision uses the standard second-difference chord-error bound:
three quarters of the largest second difference must be at most half a pixel.
In 28.4 units this is `3 * difference <= 32`. Midpoint subdivision is dyadic;
only emitted vertices are rounded. This replaces the unexplained constant 10.

For segment vector `(dx, dy)`, maximize `px * dy - py * dx` over the pen's
vertices. The opposite vertex gives the other side. The two body offsets round
to half pixels; intermediate cap vertices inset by one fixed-point unit toward
zero. Traverse each half of the same pen contour to construct the two caps.
No slope, width, or transform chooses a different line-body algorithm.

Equal-support vertices require a tie convention because their subsequent
rounding can change coverage. The native diamond and hexagonal contours prefer
Y, then X; the other measured contours prefer X, then Y. This convention is
inferred from the matrix, including negative slopes and reflections. Some tied
choices produce different GetPath sequences with identical raster coverage;
pixel equality remains the compatibility criterion.

Wide zero-length segments retain their two caps and paint the native pen
footprint. Connected segments add the exterior wedge between their support
vertices. Round joins traverse the intervening pen contour; miter joins intersect
the two offset segment lines.

Direct `Rectangle` drawing uses square (mitered) corners. Recording a Rectangle
in a path and calling WidenPath instead exposes the selected pen's round joins;
those two native operations must not be conflated. Rectangle requests mitered
joins from the shared stroker; Ellipse requests round joins.

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
