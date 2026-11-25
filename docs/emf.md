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
| `POLYBEZIER` | typed | no | no | Needs Bézier drawing. |
| `POLYGON` | typed | full | yes |  |
| `POLYLINE` | typed | full | no |  |
| `POLYBEZIERTO` | typed | no | no | Needs Bézier drawing and the current position. |
| `POLYLINETO` | typed | no | no | Needs current-position drawing. |
| `POLYPOLYLINE` | typed | no | no | Separate figures in one call; not equivalent to repeated Polyline under every ROP. |
| `POLYPOLYGON` | typed | full | no |  |
| `SETWINDOWEXTEX` | typed | full | yes | Folded into the playback world transform. |
| `SETWINDOWORGEX` | typed | full | yes | Folded into the playback world transform. |
| `SETVIEWPORTEXTEX` | typed | full | yes | Folded into the playback world transform. |
| `SETVIEWPORTORGEX` | typed | full | yes | Folded into the playback world transform. |
| `SETBRUSHORGEX` | typed | no | no | Needs a brush origin in the shared state. |
| `EOF` | typed | full | yes | Its palette is not applied. |
| `SETPIXELV` | typed | full | yes |  |
| `SETMAPPERFLAGS` | typed | full | no | Font mapping; text is font-limited. |
| `SETMAPMODE` | typed | full | yes | Physical extents from the header millimetres. |
| `SETBKMODE` | typed | full | no |  |
| `SETPOLYFILLMODE` | typed | full | no |  |
| `SETROP2` | typed | full | yes |  |
| `SETSTRETCHBLTMODE` | typed | full | yes |  |
| `SETTEXTALIGN` | typed | full | no | Text is not yet drawn in GM_ADVANCED. |
| `SETCOLORADJUSTMENT` | typed | no | no | Affects HALFTONE stretching only. |
| `SETTEXTCOLOR` | typed | full | no |  |
| `SETBKCOLOR` | typed | full | no |  |
| `OFFSETCLIPRGN` | typed | no | no | Refused in GM_ADVANCED until referenced. |
| `MOVETOEX` | typed | full | yes |  |
| `SETMETARGN` | typed | no | no | Needs a meta region in the clip state. |
| `EXCLUDECLIPRECT` | typed | full | yes |  |
| `INTERSECTCLIPRECT` | typed | full | yes |  |
| `SCALEVIEWPORTEXTEX` | typed | partial | no | Transforms whose offsets overflow are not rejected as natively. |
| `SCALEWINDOWEXTEX` | typed | partial | no | As SCALEVIEWPORTEXTEX. |
| `SAVEDC` | typed | full | no |  |
| `RESTOREDC` | typed | partial | no | Relative levels only. |
| `SETWORLDTRANSFORM` | typed | partial | no | Axis-aligned transforms only. |
| `MODIFYWORLDTRANSFORM` | typed | partial | no | Axis-aligned results only. |
| `SELECTOBJECT` | typed | partial | yes | Stock brushes and pens; stock fonts and the DC brush and pen are missing. |
| `CREATEPEN` | typed | full | yes |  |
| `CREATEBRUSHINDIRECT` | typed | full | yes | Solid, null and hatched brushes. |
| `DELETEOBJECT` | typed | full | no |  |
| `ANGLEARC` | typed | no | no | Needs current-position arcs. |
| `ELLIPSE` | typed | full | yes |  |
| `RECTANGLE` | typed | full | yes |  |
| `ROUNDRECT` | typed | full | yes |  |
| `ARC` | typed | full | yes | Counterclockwise only. |
| `CHORD` | typed | full | yes | Counterclockwise only. |
| `PIE` | typed | full | yes | Counterclockwise only. |
| `SELECTPALETTE` | typed | partial | no | The stock default palette is missing. |
| `CREATEPALETTE` | typed | full | no |  |
| `SETPALETTEENTRIES` | typed | no | no | Names a palette handle; the shared call edits the selected one. |
| `RESIZEPALETTE` | typed | no | no | As SETPALETTEENTRIES. |
| `REALIZEPALETTE` | typed | full | no |  |
| `EXTFLOODFILL` | typed | no | no | Refused in GM_ADVANCED until referenced. |
| `LINETO` | typed | full | yes |  |
| `ARCTO` | typed | no | no | Needs current-position arcs. |
| `POLYDRAW` | typed | no | no | Needs paths and Béziers. |
| `SETARCDIRECTION` | typed | no | no | Needs clockwise arcs. |
| `SETMITERLIMIT` | typed | no | no | Needs geometric pen joins. |
| `BEGINPATH` | typed | no | no | Needs path recording. |
| `ENDPATH` | typed | no | no | Needs path recording. |
| `CLOSEFIGURE` | typed | no | no | Needs path recording. |
| `FILLPATH` | typed | no | no | Needs path recording. |
| `STROKEANDFILLPATH` | typed | no | no | Needs path recording. |
| `STROKEPATH` | typed | no | no | Needs path recording. |
| `FLATTENPATH` | typed | no | no | Needs path recording. |
| `WIDENPATH` | typed | no | no | Needs path recording and geometric pens. |
| `SELECTCLIPPATH` | typed | no | no | Needs path recording. |
| `ABORTPATH` | typed | no | no | Needs path recording. |
| `COMMENT` | typed | partial | no | Never draws; EMF+ is not rendered and embedded metafiles are not played. |
| `FILLRGN` | opaque | no | no | Region records are not decoded. |
| `FRAMERGN` | opaque | no | no | Region records are not decoded. |
| `INVERTRGN` | opaque | no | no | Region records are not decoded. |
| `PAINTRGN` | opaque | no | no | Region records are not decoded. |
| `EXTSELECTCLIPRGN` | typed | partial | yes | RGN_COPY only. |
| `BITBLT` | typed | partial | yes | Source transforms and palette-indexed sources are missing. |
| `STRETCHBLT` | typed | partial | yes | As BITBLT. |
| `MASKBLT` | opaque | no | no |  |
| `PLGBLT` | opaque | no | no | Needs rotated transfers. |
| `SETDIBITSTODEVICE` | typed | partial | yes | Partial bands are unverified under scaling. |
| `STRETCHDIBITS` | typed | full | yes |  |
| `EXTCREATEFONTINDIRECTW` | typed | full | no | Text is font-limited. |
| `EXTTEXTOUTA` | typed | partial | no | Not yet drawn in GM_ADVANCED; font-limited. |
| `EXTTEXTOUTW` | typed | partial | no | Glyph indices only; not yet drawn in GM_ADVANCED; font-limited. |
| `POLYBEZIER16` | typed | no | no | Needs Bézier drawing. |
| `POLYGON16` | typed | full | no |  |
| `POLYLINE16` | typed | full | yes |  |
| `POLYBEZIERTO16` | typed | no | no | Needs Bézier drawing and the current position. |
| `POLYLINETO16` | typed | no | no | Needs current-position drawing. |
| `POLYPOLYLINE16` | typed | no | no | As POLYPOLYLINE. |
| `POLYPOLYGON16` | typed | full | no |  |
| `POLYDRAW16` | typed | no | no | Needs paths and Béziers. |
| `CREATEMONOBRUSH` | typed | no | no |  |
| `CREATEDIBPATTERNBRUSHPT` | typed | full | no |  |
| `EXTCREATEPEN` | typed | partial | no | Pens CreatePen can express; caps, joins, styles and pattern pens are missing. |
| `POLYTEXTOUTA` | opaque | no | no |  |
| `POLYTEXTOUTW` | opaque | no | no |  |
| `SETICMMODE` | typed | no | no |  |
| `CREATECOLORSPACE` | opaque | no | no |  |
| `SETCOLORSPACE` | typed | no | no |  |
| `DELETECOLORSPACE` | typed | no | no |  |
| `GLSRECORD` | opaque | no | no | OpenGL. |
| `GLSBOUNDEDRECORD` | opaque | no | no | OpenGL. |
| `PIXELFORMAT` | opaque | no | no | OpenGL. |
| `DRAWESCAPE` | opaque | no | no |  |
| `EXTESCAPE` | opaque | no | no |  |
| `SMALLTEXTOUT` | opaque | no | no |  |
| `FORCEUFIMAPPING` | typed | no | no |  |
| `NAMEDESCAPE` | opaque | no | no |  |
| `COLORCORRECTPALETTE` | typed | no | no |  |
| `SETICMPROFILEA` | opaque | no | no |  |
| `SETICMPROFILEW` | opaque | no | no |  |
| `ALPHABLEND` | opaque | no | no | Needs alpha compositing. |
| `SETLAYOUT` | typed | no | no | Refused in GM_ADVANCED until referenced. |
| `TRANSPARENTBLT` | opaque | no | no |  |
| `GRADIENTFILL` | opaque | no | no |  |
| `SETLINKEDUFIS` | opaque | no | no |  |
| `SETTEXTJUSTIFICATION` | typed | full | no | Text is font-limited. |
| `COLORMATCHTOTARGETW` | opaque | no | no |  |
| `CREATECOLORSPACEW` | opaque | no | no |  |

## Playback behaviours not yet modelled

- Whether playback resets DC attributes before the first record, and whether it
  clips to the target rectangle.
- Absolute `RestoreDC` levels and the native limit on transform offsets.
- Rotated and sheared world transforms, in every drawing primitive.
- Metafiles embedded in comment records, and EMF+ (GDI+) drawing.
- Text in `GM_ADVANCED`, Unicode text and stock fonts. Text output is
  font-limited and reported separately from exact comparisons.
