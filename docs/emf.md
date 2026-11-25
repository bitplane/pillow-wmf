# EMF support

EMF files are decoded by `pillow_wmf.emf`, played into the shared GDI call
vocabulary by `pillow_wmf.emf.play`, and drawn by the raster backend. The goal
is native parity for every record and playback behaviour; this page states
what each currently does.

## Playback model

Playback follows `PlayEnhMetaFile` on the reference oracle:

- The target DC is put in `GM_ADVANCED` and stays in `MM_TEXT`. The metafile's
  mapping records do not reach it. Playback keeps the metafile's own page state
  and world transform, and sets the DC world transform to *world, then page,
  then frame fit* as one float32 matrix (`emf/transform.py`).
- The frame fit maps the header frame (0.01 mm) onto the target rectangle using
  the header's device pixels and millimetres. Fits within 0.001 of 1:1 on both
  axes use exactly 1.0. A reversed frame does not play.
- Physical mapping modes take their extents from the header millimetres.
  Singular world transforms, unknown `ModifyWorldTransform` modes and isotropic
  adjustments that would collapse an axis leave the state unchanged.
- `GM_ADVANCED` drawing keeps 28.4 path vertices, includes the lower-right edges
  of boxes, builds curves from the transformed box in world orientation and
  scales width-1 pens. Device-space clip regions are fitted like points.
  `SetDIBitsToDevice` with every scan line plays as a `SRCCOPY` stretch.

The raster refuses operations whose `GM_ADVANCED` output has no native
references yet (`UNVERIFIED_IN_ADVANCED_MODE` in `raster.py`), and the player
reports records it cannot translate as omissions. `render()` and the Pillow
plugin raise on either rather than return partial art.

## Records

*Codec*: `typed` records decode into fields; `opaque` ones round-trip as bytes.
*Playback*: `full`, `partial` (see notes) or `no`. *References*: whether the
EMF compatibility fixtures exercise the record. `test_emf_coverage.py` checks
the codec and reference columns against the code and fixtures.

| Record | Codec | Playback | References | Notes |
| --- | --- | --- | --- | --- |
| `HEADER` | typed | full | yes | Frame fit, reference device and handle-table size. |
| `POLYBEZIER` | typed | full | yes |  |
| `POLYGON` | typed | full | yes |  |
| `POLYLINE` | typed | full | yes |  |
| `POLYBEZIERTO` | typed | full | yes |  |
| `POLYLINETO` | typed | full | yes |  |
| `POLYPOLYLINE` | typed | full | yes | Each figure is stroked separately. |
| `POLYPOLYGON` | typed | full | yes |  |
| `SETWINDOWEXTEX` | typed | full | yes | Folded into the playback world transform. |
| `SETWINDOWORGEX` | typed | full | yes | Folded into the playback world transform. |
| `SETVIEWPORTEXTEX` | typed | full | yes | Folded into the playback world transform. |
| `SETVIEWPORTORGEX` | typed | full | yes | Folded into the playback world transform. |
| `SETBRUSHORGEX` | typed | full | yes | Device-space origin for patterns and hatches. |
| `EOF` | typed | full | yes | Its palette is not applied. |
| `SETPIXELV` | typed | full | yes |  |
| `SETMAPPERFLAGS` | typed | full | yes | Font mapping; text is font-limited. |
| `SETMAPMODE` | typed | full | yes | Physical extents from the header millimetres. |
| `SETBKMODE` | typed | full | yes |  |
| `SETPOLYFILLMODE` | typed | full | yes |  |
| `SETROP2` | typed | full | yes |  |
| `SETSTRETCHBLTMODE` | typed | full | yes |  |
| `SETTEXTALIGN` | typed | full | no | Text is not yet drawn in GM_ADVANCED. |
| `SETCOLORADJUSTMENT` | typed | no | yes | Changes HALFTONE stretching. |
| `SETTEXTCOLOR` | typed | full | yes |  |
| `SETBKCOLOR` | typed | full | yes |  |
| `OFFSETCLIPRGN` | typed | partial | yes | Offsets scale through the world transform; rounding ties are unverified. |
| `MOVETOEX` | typed | full | yes |  |
| `SETMETARGN` | typed | full | yes |  |
| `EXCLUDECLIPRECT` | typed | full | yes |  |
| `INTERSECTCLIPRECT` | typed | full | yes |  |
| `SCALEVIEWPORTEXTEX` | typed | partial | no | Transforms whose offsets overflow are not rejected as natively. |
| `SCALEWINDOWEXTEX` | typed | partial | no | As SCALEVIEWPORTEXTEX. |
| `SAVEDC` | typed | full | yes |  |
| `RESTOREDC` | typed | full | yes | Absolute levels are ignored natively. |
| `SETWORLDTRANSFORM` | typed | partial | yes | Rotations and shears cover shapes, lines and SRCCOPY DIB transfers; see below. |
| `MODIFYWORLDTRANSFORM` | typed | partial | yes | As SETWORLDTRANSFORM. |
| `SELECTOBJECT` | typed | partial | yes | Stock brushes, pens and palette; stock fonts need the font work. |
| `CREATEPEN` | typed | full | yes |  |
| `CREATEBRUSHINDIRECT` | typed | full | yes | Solid, null and hatched brushes. |
| `DELETEOBJECT` | typed | full | no |  |
| `ANGLEARC` | typed | partial | yes | Sweeps of a full turn or more are not yet drawn. |
| `ELLIPSE` | typed | full | yes |  |
| `RECTANGLE` | typed | full | yes |  |
| `ROUNDRECT` | typed | full | yes |  |
| `ARC` | typed | full | yes |  |
| `CHORD` | typed | full | yes |  |
| `PIE` | typed | full | yes |  |
| `SELECTPALETTE` | typed | full | yes | Including the stock default palette. |
| `CREATEPALETTE` | typed | full | yes |  |
| `SETPALETTEENTRIES` | typed | full | yes | Edits the named palette; other objects fail natively. |
| `RESIZEPALETTE` | typed | full | yes | As SETPALETTEENTRIES. |
| `REALIZEPALETTE` | typed | full | yes |  |
| `EXTFLOODFILL` | typed | full | yes |  |
| `LINETO` | typed | full | yes |  |
| `ARCTO` | typed | full | yes |  |
| `POLYDRAW` | typed | full | yes |  |
| `SETARCDIRECTION` | typed | full | yes | Clockwise figures are the y-mirror of counterclockwise ones. |
| `SETMITERLIMIT` | typed | full | yes | Recorded as an integer; limits geometric miter joins. |
| `BEGINPATH` | typed | full | yes |  |
| `ENDPATH` | typed | full | yes |  |
| `CLOSEFIGURE` | typed | full | yes |  |
| `FILLPATH` | typed | full | yes |  |
| `STROKEANDFILLPATH` | typed | full | yes |  |
| `STROKEPATH` | typed | full | yes |  |
| `FLATTENPATH` | typed | full | yes |  |
| `WIDENPATH` | typed | partial | yes | Extended geometric pens other than round caps with round joins; other pens are refused. |
| `SELECTCLIPPATH` | typed | full | yes | The path interior becomes a region by its fill coverage. |
| `ABORTPATH` | typed | full | yes |  |
| `COMMENT` | typed | partial | yes | Never draws; EMF+ is not rendered and embedded metafiles are not played. |
| `FILLRGN` | typed | full | yes | Region corners take the ceiling of their 28.4 position. |
| `FRAMERGN` | typed | full | yes | As FILLRGN. |
| `INVERTRGN` | typed | full | yes | As FILLRGN. |
| `PAINTRGN` | typed | full | yes | As FILLRGN. |
| `EXTSELECTCLIPRGN` | typed | full | yes | Device-space regions fitted like points; a missing clip combines with the whole surface. |
| `BITBLT` | typed | partial | yes | Source transforms and palette-indexed sources are missing. |
| `STRETCHBLT` | typed | partial | yes | As BITBLT. |
| `MASKBLT` | typed | full | yes | Per-pixel ROP3 from the mask; scaled transfers pad as their foreground ROP decides. |
| `PLGBLT` | typed | full | yes | Identity source transforms and RGB sources. |
| `SETDIBITSTODEVICE` | typed | partial | yes | Partial bands are unverified under scaling. |
| `STRETCHDIBITS` | typed | full | yes |  |
| `EXTCREATEFONTINDIRECTW` | typed | full | no | Text is font-limited. |
| `EXTTEXTOUTA` | typed | partial | no | Not yet drawn in GM_ADVANCED; font-limited. |
| `EXTTEXTOUTW` | typed | partial | no | Glyph indices only; not yet drawn in GM_ADVANCED; font-limited. |
| `POLYBEZIER16` | typed | full | yes |  |
| `POLYGON16` | typed | full | yes |  |
| `POLYLINE16` | typed | full | yes |  |
| `POLYBEZIERTO16` | typed | full | yes |  |
| `POLYLINETO16` | typed | full | yes |  |
| `POLYPOLYLINE16` | typed | full | yes | As POLYPOLYLINE. |
| `POLYPOLYGON16` | typed | full | yes |  |
| `POLYDRAW16` | typed | full | yes |  |
| `CREATEMONOBRUSH` | typed | full | yes | Colours come from the text and background colours. |
| `CREATEDIBPATTERNBRUSHPT` | typed | full | yes |  |
| `EXTCREATEPEN` | typed | full | yes | Cosmetic, alternate and user-styled pens; geometric pens with any cap, join, dash, hatch or DIB pattern. |
| `POLYTEXTOUTA` | typed | no | no |  |
| `POLYTEXTOUTW` | typed | no | no |  |
| `SETICMMODE` | typed | full | yes | No effect on a bitmap DC. |
| `CREATECOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `SETCOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `DELETECOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `GLSRECORD` | typed | full | yes | No effect on a bitmap DC. |
| `GLSBOUNDEDRECORD` | typed | full | yes | No effect on a bitmap DC. |
| `PIXELFORMAT` | typed | full | yes | No effect on a bitmap DC. |
| `DRAWESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `EXTESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `SMALLTEXTOUT` | typed | no | no |  |
| `FORCEUFIMAPPING` | typed | full | yes | No effect on shapes; font-limited. |
| `NAMEDESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `COLORCORRECTPALETTE` | typed | full | yes | No effect on a bitmap DC. |
| `SETICMPROFILEA` | typed | full | yes | No effect on a bitmap DC. |
| `SETICMPROFILEW` | typed | full | no | No effect on a bitmap DC; unreferenced. |
| `ALPHABLEND` | typed | partial | yes | Constant and per-pixel alpha with nearest sampling; per-pixel alpha below full constant alpha is unreferenced. |
| `SETLAYOUT` | typed | no | yes | Refused in GM_ADVANCED until referenced. |
| `TRANSPARENTBLT` | typed | full | yes | Stretches without combining samples, skipping the key colour. |
| `GRADIENTFILL` | typed | full | yes | Rectangle records reserve twelve bytes per mesh; playback refuses them without it. |
| `SETLINKEDUFIS` | typed | full | yes | No effect on shapes; font-limited. |
| `SETTEXTJUSTIFICATION` | typed | full | no | Text is font-limited. |
| `COLORMATCHTOTARGETW` | typed | no | yes | The fixture record stops native playback; its validity rules are unknown. |
| `CREATECOLORSPACEW` | typed | full | no | No effect on a bitmap DC; unreferenced. |

## Geometric pens

Extended geometric pens (`widen.py`) widen each figure into closed outlines
filled with the winding rule, matching native `WidenPath` output point for
point:

- Round caps with round joins use the support-vertex construction shared with
  wide `CreatePen` strokes. Square caps with round joins keep those bodies.
- Every other combination places the body on a perpendicular chosen from the
  realized pen polygon: a line parallel to a pen edge uses the edge midpoint,
  a line parallel to the chord across a vertex uses that vertex, and other
  directions interpolate between them by cross-product weights before snapping
  to the half-pixel grid. Flat and square caps, bevels and miters share it.
- Inner joins pass through the vertex; round inner joins also sweep the pen.
  Miter tips round to the nearest 28.4 point; miters longer than the limit
  bevel.
- Square caps extend along the logical direction by the device half-width of
  the larger axis, rounded to 28.4; under a scaling mapping it is first rounded
  to sixteenths of a 28.4 unit.
- Predefined geometric styles are multiples of the width (dash 3:1, dot 1:1,
  and so on); user styles are logical lengths. Dashes are measured in logical
  units, cut by interpolating along the device segment, and drawn as open
  figures. Round and square caps pull each dash end back by one width, so
  dots become zero-length dashes.
- Cosmetic alternate and user styles step through device pixels, user style
  entries in units of three pixels like the predefined styles. Cosmetic pens
  are always one pixel wide and solid.
- `WidenPath` flattens each figure and replaces it with these outlines as
  closed polygon figures, one per dash for patterned pens. Round caps with
  round joins, and pens that are not extended geometric pens, have no outline
  construction and are refused.
- Hatched and DIB pattern pens fill the widened footprint with the brush,
  tiled from the brush origin like any brush; a DIB pattern pen's LOGBRUSH
  colour is its colour usage.

## Gradient fills

`GradientFill` maps each vertex to a whole device pixel and writes inside the
clip region without applying ROP2 (the ROP2 interaction is unverified):

- Rectangles shade from the corner nearer the leading edge, whichever index
  holds it. Each 16-bit channel advances by a floored 16.16 step per pixel
  and keeps its top 8 bits. The far column or row is not drawn.
- Triangles cover rows from the top vertex to the row before the bottom
  vertex; each row runs from the ceiling of its left edge crossing to before
  the ceiling of its right one. A pixel's colour is the exact plane through
  the corner colours, rounded to a 16-bit unit, then its top 8 bits.

## Rotated and sheared transforms

A world transform that mixes the axes needs an identity page mapping, as EMF
playback provides. Points map to 28.4 as the float32 sum of the two float32
products plus the 28.4 translation.

- Box shapes map their left-top, right-top and left-bottom corners and
  reflect the fourth through them. Ellipses, arcs, chords, pies and rounded
  rectangles are built on those corners with the axis-aligned GM_ADVANCED
  constructions as their special case: edge midpoints take floored halves,
  the circle-constant insets round per device component, and the lower half
  reflects the upper through the right-top and left-bottom corners.
- A CreatePen pen keeps its device-aligned small-pen shape. Each device axis
  rounds the logical width vector along it to 28.4 and truncates its length,
  so a pen narrows slightly at oblique angles.
- DIB transfers with SRCCOPY map their destination rectangle to a
  parallelogram and copy as PlgBlt does.

PlgBlt inverts the mapping at each pixel's integer point against the 28.4
parallelogram. A source column on an exact boundary belongs to the column it
starts; a source row on an exact boundary belongs to the row just above the
pixel in device space. A mask bit of 1 copies the source pixel.

## Playback behaviours not yet modelled

- Tie rounding of the geometric pen perpendicular: about one direction in
  twenty, at exact half-pixel ties, snaps the other way natively.
- A triangle gradient's flat top row: native colours along a horizontal top
  edge fall just below exact 8-bit boundaries, one unit lower than the
  rounded plane.

- Whether playback resets DC attributes before the first record, and whether it
  clips to the target rectangle.
- Absolute `RestoreDC` levels and the native limit on transform offsets.
- Under rotating or shearing transforms: text, regions, clip rectangles,
  gradients, legacy and non-SRCCOPY transfers, extended geometric pens, pens
  wider than the small-pen table, and wide pens under non-uniform transforms
  are refused. Direct drawing with a small wide pen can be a fraction of a
  pixel thinner natively across some edge directions than `WidenPath`
  reports; the renderer follows `WidenPath`.
- A masked PlgBlt onto a parallelogram mirrored against its source reads the
  mask mirrored within the source rectangle; only fully mirrored cases have
  native references.
- Metafiles embedded in comment records, and EMF+ (GDI+) drawing.
- Text in `GM_ADVANCED`, Unicode text and stock fonts. Text output is
  font-limited and reported separately from exact comparisons.
