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
| `POLYBEZIER` | typed | no | yes | Needs Bézier drawing. |
| `POLYGON` | typed | full | yes |  |
| `POLYLINE` | typed | full | yes |  |
| `POLYBEZIERTO` | typed | no | yes | Needs Bézier drawing and the current position. |
| `POLYLINETO` | typed | no | yes | Needs current-position drawing. |
| `POLYPOLYLINE` | typed | no | yes | Separate figures in one call; not equivalent to repeated Polyline under every ROP. |
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
| `SETWORLDTRANSFORM` | typed | partial | yes | Axis-aligned transforms only. |
| `MODIFYWORLDTRANSFORM` | typed | partial | yes | Axis-aligned results only. |
| `SELECTOBJECT` | typed | partial | yes | Stock brushes, pens and palette; stock fonts need the font work. |
| `CREATEPEN` | typed | full | yes |  |
| `CREATEBRUSHINDIRECT` | typed | full | yes | Solid, null and hatched brushes. |
| `DELETEOBJECT` | typed | full | no |  |
| `ANGLEARC` | typed | no | yes | Needs current-position arcs. |
| `ELLIPSE` | typed | full | yes |  |
| `RECTANGLE` | typed | full | yes |  |
| `ROUNDRECT` | typed | full | yes |  |
| `ARC` | typed | full | yes | Counterclockwise only. |
| `CHORD` | typed | full | yes | Counterclockwise only. |
| `PIE` | typed | full | yes | Counterclockwise only. |
| `SELECTPALETTE` | typed | full | yes | Including the stock default palette. |
| `CREATEPALETTE` | typed | full | yes |  |
| `SETPALETTEENTRIES` | typed | full | yes | Edits the named palette; other objects fail natively. |
| `RESIZEPALETTE` | typed | full | yes | As SETPALETTEENTRIES. |
| `REALIZEPALETTE` | typed | full | yes |  |
| `EXTFLOODFILL` | typed | full | yes |  |
| `LINETO` | typed | full | yes |  |
| `ARCTO` | typed | no | yes | Needs current-position arcs. |
| `POLYDRAW` | typed | no | yes | Needs paths and Béziers. |
| `SETARCDIRECTION` | typed | no | yes | Needs clockwise arcs. |
| `SETMITERLIMIT` | typed | partial | yes | Stored; geometric joins that use it are not yet drawn. |
| `BEGINPATH` | typed | no | yes | Needs path recording. |
| `ENDPATH` | typed | no | yes | Needs path recording. |
| `CLOSEFIGURE` | typed | no | yes | Needs path recording. |
| `FILLPATH` | typed | no | yes | Needs path recording. |
| `STROKEANDFILLPATH` | typed | no | yes | Needs path recording. |
| `STROKEPATH` | typed | no | yes | Needs path recording. |
| `FLATTENPATH` | typed | no | yes | Needs path recording. |
| `WIDENPATH` | typed | no | yes | Needs path recording and geometric pens. |
| `SELECTCLIPPATH` | typed | no | yes | Needs path recording. |
| `ABORTPATH` | typed | no | yes | Needs path recording. |
| `COMMENT` | typed | partial | yes | Never draws; EMF+ is not rendered and embedded metafiles are not played. |
| `FILLRGN` | typed | full | yes | Region corners take the ceiling of their 28.4 position. |
| `FRAMERGN` | typed | full | yes | As FILLRGN. |
| `INVERTRGN` | typed | full | yes | As FILLRGN. |
| `PAINTRGN` | typed | full | yes | As FILLRGN. |
| `EXTSELECTCLIPRGN` | typed | full | yes | Device-space regions fitted like points; a missing clip combines with the whole surface. |
| `BITBLT` | typed | partial | yes | Source transforms and palette-indexed sources are missing. |
| `STRETCHBLT` | typed | partial | yes | As BITBLT. |
| `MASKBLT` | typed | full | yes | Per-pixel ROP3 from the mask; scaled transfers pad as their foreground ROP decides. |
| `PLGBLT` | typed | no | yes | Needs rotated transfers. |
| `SETDIBITSTODEVICE` | typed | partial | yes | Partial bands are unverified under scaling. |
| `STRETCHDIBITS` | typed | full | yes |  |
| `EXTCREATEFONTINDIRECTW` | typed | full | no | Text is font-limited. |
| `EXTTEXTOUTA` | typed | partial | no | Not yet drawn in GM_ADVANCED; font-limited. |
| `EXTTEXTOUTW` | typed | partial | no | Glyph indices only; not yet drawn in GM_ADVANCED; font-limited. |
| `POLYBEZIER16` | typed | no | yes | Needs Bézier drawing. |
| `POLYGON16` | typed | full | yes |  |
| `POLYLINE16` | typed | full | yes |  |
| `POLYBEZIERTO16` | typed | no | yes | Needs Bézier drawing and the current position. |
| `POLYLINETO16` | typed | no | yes | Needs current-position drawing. |
| `POLYPOLYLINE16` | typed | no | yes | As POLYPOLYLINE. |
| `POLYPOLYGON16` | typed | full | yes |  |
| `POLYDRAW16` | typed | no | yes | Needs paths and Béziers. |
| `CREATEMONOBRUSH` | typed | full | yes | Colours come from the text and background colours. |
| `CREATEDIBPATTERNBRUSHPT` | typed | full | yes |  |
| `EXTCREATEPEN` | typed | partial | yes | Pens CreatePen can express; caps, joins, styles and pattern pens are missing. |
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
| `ALPHABLEND` | typed | no | yes | Needs alpha compositing. |
| `SETLAYOUT` | typed | no | yes | Refused in GM_ADVANCED until referenced. |
| `TRANSPARENTBLT` | typed | full | yes | Stretches without combining samples, skipping the key colour. |
| `GRADIENTFILL` | typed | no | yes |  |
| `SETLINKEDUFIS` | typed | full | yes | No effect on shapes; font-limited. |
| `SETTEXTJUSTIFICATION` | typed | full | no | Text is font-limited. |
| `COLORMATCHTOTARGETW` | typed | no | yes | The fixture record stops native playback; its validity rules are unknown. |
| `CREATECOLORSPACEW` | typed | full | no | No effect on a bitmap DC; unreferenced. |

## Playback behaviours not yet modelled

- Whether playback resets DC attributes before the first record, and whether it
  clips to the target rectangle.
- Absolute `RestoreDC` levels and the native limit on transform offsets.
- Rotated and sheared world transforms, in every drawing primitive.
- Metafiles embedded in comment records, and EMF+ (GDI+) drawing.
- Text in `GM_ADVANCED`, Unicode text and stock fonts. Text output is
  font-limited and reported separately from exact comparisons.
