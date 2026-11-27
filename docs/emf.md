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
- Before the first record, the DC's clip becomes its meta region (so a
  metafile's `SelectClipRgn(NULL)` returns to it), the white brush, black
  pen and default palette are selected, and the attributes are reset: white
  background, black text, no character extra, `OPAQUE`, `ALTERNATE`,
  `R2_COPYPEN`, `BLACKONWHITE`, text alignment 0, mapper flags 0, brush
  origin (0, 0), miter limit 10, no justification, counter-clockwise arcs
  and the current position at (0, 0). Native playback also selects the
  device default font; that waits for the text work. Colour adjustment is
  not reset.
- Native playback reads the clip box, in the metafile's logical units, once
  before the first record, and widens it on each axis by one unit, or by one
  more than the whole number of reference-display pixels per metafile
  device pixel when the header's device is denser than the 1024x768,
  271x203 mm reference display. Transfers (`BitBlt`, `StretchBlt`,
  `StretchDIBits`, `SetDIBitsToDevice`, `MaskBlt`, `PlgBlt`, `AlphaBlend`,
  `TransparentBlt`) and region painting (`FillRgn`, `FrameRgn`,
  `InvertRgn`, `PaintRgn`) whose record bounds lie wholly outside that box
  are skipped; reversed (empty) bounds never are. Nothing plays when the
  clip is empty.
- The frame fit maps the header frame (0.01 mm) onto the target rectangle using
  the header's device pixels and millimetres, in binary32. A reversed frame
  does not play.
- The page state lives in a hidden DC. After a mapping record it reads that
  DC's world-to-device transform, multiplies it by the frame fit and sets the
  product on the target DC; a left-multiplying `ModifyWorldTransform` is
  applied to the target's transform directly instead. Products follow GDI's
  binary32 order (`multiply` in `emf/transform.py`): each offset is the
  second matrix's off-diagonal term on the first's other offset, plus the
  second's offset, plus the diagonal product. A product whose offset reaches
  2^32, or a transform that is singular in binary32, leaves the target's
  transform unchanged. `ScaleWindowExtEx` and `ScaleViewportExtEx` multiply
  in wrapping 32-bit integers and divide truncating toward zero, and only
  play in the isotropic and anisotropic modes.
- The frame fit is composed with the target DC's own transform before its
  scales snap to exactly 1 when both lie within [0.999, 1.001] and neither
  matrix has off-diagonal terms.
- Physical mapping modes take their extents from the header millimetres.
  Singular world transforms, unknown `ModifyWorldTransform` modes and isotropic
  adjustments that would collapse an axis leave the state unchanged.
- `GM_ADVANCED` drawing keeps 28.4 path vertices, includes the lower-right edges
  of boxes, builds curves from the transformed box in world orientation and
  scales width-1 pens. Device-space clip regions are fitted like points.
  `SetDIBitsToDevice` with every scan line plays as a `SRCCOPY` stretch.
  A partial band carries only its own scan lines. They form a bitmap whose
  top row is a bottom-up band's last line or a top-down band's first, and
  the source rectangle's top is row `start + count - ySrc - cySrc` of it,
  a bottom-up count being limited to the lines the DIB has. The whole
  rectangle stretches; its rows outside the band draw nothing. A compressed
  band is its stream from the start, decoded into the band's lines and
  ended there; like any compressed source, it skips unwritten pixels only
  when copied directly from the DIB origin, and otherwise realizes them as
  index 0.
- `AngleArc` builds its arc from the start and end angles directly, each in
  the quadrant of its angle's floor, with the arc constructions of `Arc`.
  A sweep of a turn or more draws the remainder (the sweep less its whole
  turns) and then, for each turn, the arc from the remainder's end round to
  the start followed by the remainder again; a zero remainder is one
  zero-length Bezier. The current position ends at the final angle.
- After `ArcTo` and `AngleArc` the DC keeps the arc's exact 28.4 end, and
  the next `LineTo`, `PolylineTo` or `PolyBezierTo` starts from it, so a
  path figure continues across the arc. Drawing starts from it as it is in
  GM_ADVANCED under a page or world transform, and otherwise from it floored
  to a whole device pixel.
- Otherwise `ArcTo` starts from the DC's cached device position, which a
  world transform change does not update: the device origin on a fresh DC,
  the device end point after `LineTo`, `PolylineTo`, `PolyBezierTo` or
  `PolyDraw`, and the logical position mapped afresh after `MoveTo` or any
  other drawing. Other calls start from the logical position
  ([`test_current_position.py`](../test/unit/test_current_position.py)).
- `PolyDraw` with an invalid point type fails. Inside a path bracket the
  points before the invalid one stay in the path, and the current position
  is left where it was, so the next call opens a new figure there; outside
  one nothing is drawn.
- In GM_COMPATIBLE (direct drawing; EMF playback is always GM_ADVANCED),
  `ArcTo` draws the figure `Arc` would, and `AngleArc` maps its circle's box
  to whole device pixels and builds the arc about that box's centre in
  device space. `AD_CLOCKWISE` reverses GM_COMPATIBLE arcs, chords and pies
  in device space
  ([`test_compatible_arcs.py`](../test/unit/test_compatible_arcs.py)).
- Device coordinates are 28.4 values in 32 bits, which wrap. A figure whose
  28.4 extent overflows 32 bits is not drawn, and `LineTo` fails once its end
  point's next 28.4 pixel overflows. Cosmetic `Polyline` and `PolyPolyline`
  through a unit transform take GDI's integer path: the stroke is clipped to
  the points' whole-pixel bounds, one past the far edges unless either far
  edge is the largest 32-bit value (then neither is extended), the 28.4
  points wrap, and a segment whose 28.4 span overflows is dropped. A
  rectangle's outline runs through the wrapped box (GM_COMPATIBLE:
  inclusive far edges): it is drawn where it wraps to, or, when it
  overflows or turns over, dropped, leaving the interior inside it filled
  from the true box under a unit transform (which keeps integer
  coordinates) and nothing drawn under any other. Curved GM_COMPATIBLE
  shapes are built from the wrapped inclusive box, mirrored when the wrap
  reverses it. `PatBlt`'s far edges are 32-bit sums. A unit page scale maps
  integers exactly
  ([`test_coordinate_limits.py`](../test/unit/test_coordinate_limits.py)).
- In GM_ADVANCED, an arc, chord, pie or `ArcTo` whose logical box has no
  width or height sweeps its whole degenerate ellipse, from and back to its
  zero-angle point, and a `RoundRect` of such a box draws as the box; in
  GM_COMPATIBLE such shapes draw nothing
  ([`test_degenerate_shapes.py`](../test/unit/test_degenerate_shapes.py)).
- Transfers with a source bitmap (`BitBlt`, `StretchBlt`, `MaskBlt`,
  `PlgBlt`, `AlphaBlend`, `TransparentBlt`) map their logical source
  rectangle through the recorded source transform, rounding each edge half
  up to a bitmap pixel. A scaled or mirrored source becomes a stretch of that
  rectangle onto the destination (in the DC's stretch mode); a `MaskBlt` mask
  covers the mapped rectangle and stretches with it. A rotated or sheared
  source draws nothing, as GDI rejects such a source DC. A `DIB_PAL_COLORS`
  colour table indexes the default palette, whatever palette the metafile
  selected, with indexes wrapping modulo its 20 entries.

Calls and records that fail natively (invalid modes, unrealizable objects,
malformed bitmaps, masks that are not 1-bpp) fail without effect here too, and
a created object that fails leaves its slot empty; record types playback does
not know are ignored, as natively. The player reports malformed records of
known types, EMF+ drawing without a GDI fallback, and text in a face the font
collection cannot provide (font-limited) as omissions. `render()` and the
Pillow plugin raise on these rather than return partial art.

## Text

Text records play through the font collection's faces:

- `EMR_EXTTEXTOUTA/W` always read the fixed layout, rectangle included,
  whatever `ETO_NO_RECT` says; a record native validation rejects ends
  playback. Unicode text has one advance per UTF-16 code unit.
- `EMR_POLYTEXTOUTA/W` play each entry as ExtTextOut, always with its
  rectangle and advances (a zero advance offset addresses the record's own
  header); an entry with options GDI rejects ends the record's output.
- `EMR_SMALLTEXTOUT` widens 8-bit characters to code units without a code
  page and draws without advances.
- A GM_COMPATIBLE record plays with GM_COMPATIBLE text rules and its font
  transform scales, which size the font in place of the page scale.
- Under rotating or shearing transforms glyphs are scan-converted from the
  outline through the full notional-to-device matrix by the TrueType rules
  (each axis scaled by its column's larger component in 16.16 per unit, then
  the remaining matrix, the driver's 16.16 matrix divided by those scales;
  a scale-only matrix holds its x scale in 16.16 unless it is uniform and
  unmirrored). At 32 pixels per em and below, dropout control fills the
  pixel to the left or below, or the other neighbour when that falls outside
  the glyph bitmap (the pixels whose centres lie within the outline's
  extent). The cell spans the head table's bounds
  widened by 1/64 em, rounded out to pixels along the ascender; opaque cells,
  underline and strikeout are parallelograms along the baseline. A logical
  unit along the baseline spans `1 / |W⁻¹d|` device units, for the world
  transform `W` and the font's unit device baseline `d`. Without explicit
  spacing, glyphs are placed by their logical extents: the glyphs' 28.4
  device advances (fxD) accumulated, converted back to logical units and
  rounded half up; a recorded EXTTEXTOUT stores the same extents. Escaped GM_COMPATIBLE text under a world
  transform kept from GM_ADVANCED rotates in device space the same way.
  When a GM_ADVANCED escapement differs from the orientation, each glyph's
  centre (origin plus half its advance) sits on the escapement at its back
  extent past the running sum of the earlier glyphs' extents, with that sum
  rounded to whole logical units. A glyph's extents are the distances from
  its centre, along the escapement, to an ellipse through the half advance
  and the whole-pixel ink top or bottom widened by a sixteenth of the font's
  ascent.
- A zero font height takes the device's default 16 pixel em, converted to a
  whole number of logical units along the world y axis, on every text path.
- Under a non-uniform positive GM_ADVANCED scale, glyphs round from the
  precise reference point; TA_CENTER halves the device advance and TA_RIGHT
  subtracts the run's logical width converted back to whole device pixels.
- Current-position text continues from the 28.4 device point the previous run
  left. An opaque cell widens over ink protruding past the advances, and, with
  explicit advances, to the left of the origin. Under rotation or shear the
  drawn cell also reaches each glyph's ink end rounded up to a whole pixel;
  a metafile's recorded bounds keep the unrounded cell, and without explicit
  advances span the run's notional width through the x column of the
  glyph matrix (each component rounded to 28.4), measured and rounded to
  whole logical units.
- A character the face lacks draws the face's glyph 0 (`.notdef`), as
  natively; `FontCollection(missing_glyph="error")` refuses such text.
- A missing weight or slant is simulated from the family's nearest face.
  Italic shears the outline by 0x5700/65536. Bold adds a device pixel to each
  advance (and its logical equivalent to each logical extent); under rotating
  or shearing transforms the outline is emboldened as the TrueType scaler
  does it ([`embolden.py`](../src/pillow_wmf/embolden.py)): in the scaler's
  first stage (each axis scaled by its column's larger component, 16.16 per
  unit), before the remaining matrix. The strengths are 20 per mille of the
  pixels per em along the y column, plus one pixel horizontally; a
  one-pixel strength moves right-facing edges right. Once the vertical scale
  gives a vertical strength, the outline is first scaled down by that many
  pixels per em: along x by the world's vertical scale, along y by the
  vertical scale including the italic shear, leaving the cross terms
  whole. Horizontal monochrome text of an unhinted face takes the same
  TrueType scan rules and emboldening.
- Stock fonts select their logical fonts (mostly raster faces, so
  font-limited). Charset 254 decodes UTF-8 with any face (a symbol face maps
  the Latin-1 range to its F0xx glyphs).
- A face whose OS/2 code pages lack the requested charset gives way, as in
  Windows' mapper, to Wingdings (SYMBOL_CHARSET), MS PGothic (128), Gulim
  (129), Nirmala UI Semilight (130), SimSun (134), PMingLiU (136), Leelawadee
  UI (222) or otherwise Arial; a symbol face takes Arial for any charset but
  DEFAULT, SYMBOL and UTF-8. Undefined charset values realize ANSI. A
  `FontCollection` uses the substitute when it is supplied and refuses the
  text otherwise, naming it
  ([`probe-windows-charset-mapping.py`](../scripts/probe-windows-charset-mapping.py)).

Exact comparisons use the controlled fonts in `test/fonts`; real fonts are
font-limited and reported separately.

TrueType, CFF (PostScript-outline OpenType) and variable faces are accepted;
a variable face draws its default instance, and FreeType rasterizes CFF
glyphs, with no attempt to match the native OpenType driver. Glyph-index text
draws the indices in whichever face was realized, as natively, even when
that face substitutes for the requested one (the substitution is reported).

Layout, metrics and face selection follow native GDI, but antialiased glyph
coverage is FreeType's (gray for ANTIALIASED_QUALITY, LCD filtering for the
ClearType qualities), so smoothed glyphs differ slightly from Windows. They are
reviewed by eye: [`text_samples.py`](../scripts/text_samples.py) defines EMF
sheets of common Windows faces across sizes, qualities, styles, rotations and
character sets; the `text-samples` probe plays them natively, and
`python scripts/text-samples-side-by-side.py NATIVE_DIR OUTPUT_DIR` renders the
same files with the host's fonts beside the native images.

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
| `SETBKMODE` | typed | full | yes | Values other than OPAQUE are transparent; hatched `PatBlt` always paints its background. |
| `SETPOLYFILLMODE` | typed | full | yes | Values other than WINDING fill as ALTERNATE. |
| `SETROP2` | typed | full | yes | The low byte b selects mix ((b - 1) & 15) + 1, so 0 is R2_WHITE. |
| `SETSTRETCHBLTMODE` | typed | full | yes | Values outside 1-4 stretch as WHITEONBLACK. |
| `SETTEXTALIGN` | typed | full | yes |  |
| `SETCOLORADJUSTMENT` | typed | full | yes | Scaled HALFTONE copies; transfers under rotating transforms sample without it. |
| `SETTEXTCOLOR` | typed | full | yes |  |
| `SETBKCOLOR` | typed | full | yes |  |
| `OFFSETCLIPRGN` | typed | full | yes | Offsets scale through the world transform, ties rounding away from zero. |
| `MOVETOEX` | typed | full | yes |  |
| `SETMETARGN` | typed | full | yes |  |
| `EXCLUDECLIPRECT` | typed | full | yes |  |
| `INTERSECTCLIPRECT` | typed | full | yes |  |
| `SCALEVIEWPORTEXTEX` | typed | full | yes | 32-bit products and truncating division, as natively. |
| `SCALEWINDOWEXTEX` | typed | full | yes | As SCALEVIEWPORTEXTEX. |
| `SAVEDC` | typed | full | yes |  |
| `RESTOREDC` | typed | full | yes | Absolute levels are ignored natively. |
| `SETWORLDTRANSFORM` | typed | partial | yes | Rotations and shears cover all drawing, text included; see below. |
| `MODIFYWORLDTRANSFORM` | typed | partial | yes | As SETWORLDTRANSFORM. |
| `SELECTOBJECT` | typed | partial | yes | Stock brushes, pens and palette; stock fonts need the font work. |
| `CREATEPEN` | typed | full | yes |  |
| `CREATEBRUSHINDIRECT` | typed | full | yes | Solid, null and hatched brushes. |
| `DELETEOBJECT` | typed | full | yes |  |
| `ANGLEARC` | typed | full | yes | Sweeps of a full turn or more repeat the circle. |
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
| `SETARCDIRECTION` | typed | full | yes | Clockwise figures are the y-mirror of counterclockwise ones; other values fail. |
| `SETMITERLIMIT` | typed | full | yes | Recorded as an integer; limits geometric miter joins. |
| `BEGINPATH` | typed | full | yes |  |
| `ENDPATH` | typed | full | yes |  |
| `CLOSEFIGURE` | typed | full | yes |  |
| `FILLPATH` | typed | full | yes |  |
| `STROKEANDFILLPATH` | typed | full | yes |  |
| `STROKEPATH` | typed | full | yes |  |
| `FLATTENPATH` | typed | full | yes |  |
| `WIDENPATH` | typed | full | yes | `CreatePen` styles widen as solid; cosmetic `ExtCreatePen` pens fail, keeping the path. |
| `SELECTCLIPPATH` | typed | full | yes | The path interior becomes a region by its fill coverage. |
| `ABORTPATH` | typed | full | yes |  |
| `COMMENT` | typed | partial | yes | GDIC multi-format comments play their embedded EMF; EMF+ is not rendered. |
| `FILLRGN` | typed | full | yes | Region corners take the ceiling of their 28.4 position. |
| `FRAMERGN` | typed | full | yes | As FILLRGN. |
| `INVERTRGN` | typed | full | yes | As FILLRGN. |
| `PAINTRGN` | typed | full | yes | As FILLRGN. |
| `EXTSELECTCLIPRGN` | typed | full | yes | Device-space regions fitted like points; a missing clip combines with the whole surface. |
| `BITBLT` | typed | full | yes | Scaled and mirrored source transforms stretch; `DIB_PAL_COLORS` sources use the default palette. |
| `STRETCHBLT` | typed | full | yes | As BITBLT. |
| `MASKBLT` | typed | full | yes | Per-pixel ROP3 from the mask; scaled transfers pad as their foreground ROP decides. |
| `PLGBLT` | typed | full | yes | A masked transfer keeps an identity source transform. |
| `SETDIBITSTODEVICE` | typed | full | yes | Scaled with the playback transform, partial and compressed bands included. |
| `STRETCHDIBITS` | typed | full | yes |  |
| `EXTCREATEFONTINDIRECTW` | typed | full | yes | Faces outside the supplied fonts are font-limited. |
| `EXTTEXTOUTA` | typed | partial | yes | The rectangle field is always read, as natively, whatever `ETO_NO_RECT` says. |
| `EXTTEXTOUTW` | typed | partial | yes | Unicode text or glyph indices; the rectangle field is always read. |
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
| `POLYTEXTOUTA` | typed | partial | yes | Each entry plays as ExtTextOut, always with its rectangle and advances. |
| `POLYTEXTOUTW` | typed | partial | yes | Each entry plays as ExtTextOut, always with its rectangle and advances. |
| `SETICMMODE` | typed | full | yes | No effect on a bitmap DC. |
| `CREATECOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `SETCOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `DELETECOLORSPACE` | typed | full | yes | No effect on a bitmap DC. |
| `GLSRECORD` | typed | full | yes | No effect on a bitmap DC. |
| `GLSBOUNDEDRECORD` | typed | full | yes | No effect on a bitmap DC. |
| `PIXELFORMAT` | typed | full | yes | No effect on a bitmap DC. |
| `DRAWESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `EXTESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `SMALLTEXTOUT` | typed | partial | yes | 8-bit characters widen to UTF-16 code units without a code page. |
| `FORCEUFIMAPPING` | typed | full | yes | No effect on shapes; font-limited. |
| `NAMEDESCAPE` | typed | full | yes | No effect on a bitmap DC. |
| `COLORCORRECTPALETTE` | typed | full | yes | No effect on a bitmap DC. |
| `SETICMPROFILEA` | typed | full | yes | No effect on a bitmap DC. |
| `SETICMPROFILEW` | typed | full | yes | No effect on a bitmap DC. |
| `ALPHABLEND` | typed | full | yes | Constant and per-pixel alpha with nearest sampling. |
| `SETLAYOUT` | typed | full | yes | Mirrors the playback transform about the reference device width; the DC layout is unchanged. |
| `TRANSPARENTBLT` | typed | full | yes | Stretches without combining samples, skipping the key colour. |
| `GRADIENTFILL` | typed | full | yes | Rectangle records reserve twelve bytes per mesh; without it native playback stops. |
| `SETLINKEDUFIS` | typed | full | yes | No effect on shapes; font-limited. |
| `SETTEXTJUSTIFICATION` | typed | full | yes | Spreads break extra over the run's break characters. |
| `COLORMATCHTOTARGETW` | typed | full | yes | `CS_ENABLE` without a profile name stops playback; otherwise no effect on a bitmap DC. |
| `CREATECOLORSPACEW` | typed | full | yes | No effect on a bitmap DC. |

## Recording

[`emf.Recorder`](../src/pillow_wmf/emf/recorder.py) accepts the same GDI calls
as the renderer and writes the records a native enhanced-metafile DC writes,
emulating the recording DC on the reference device (MM_TEXT, GM_COMPATIBLE):

- Pens, brushes, fonts and palettes are written when first selected, into
  the lowest free 1-based slot; objects never selected never appear, nor do
  their deletions. Stock objects are selected as `0x80000000 | index`;
  `CreatePen(PS_NULL)` and a `BS_NULL` brush are the stock null objects.
  Palette edits name the selected palette's slot, `AnimatePalette` is not
  recorded, palette entry flags are cleared, and every colour written to a
  palette is collected, once each, into the EOF palette.
- In GM_COMPATIBLE, box shapes are rewritten lower-right inclusive: the edge
  moves in by the logical size of one device pixel (window over viewport
  extent), rounded half to even. GM_ADVANCED boxes are written as given;
  there is no record for the graphics mode. `SetWorldTransform` is followed
  by `ModifyWorldTransform(MWT_SET)` with the same matrix;
  `ModifyWorldTransform` is written as given. Once the DC has held a
  non-identity world transform, whatever follows, GM_COMPATIBLE ellipses,
  rounded rectangles, arcs, chords and pies keep their far edges in their
  bounds; rectangles do not. A GM_COMPATIBLE ellipse, rounded rectangle,
  arc, chord, pie or `ArcTo` whose inclusive edges turn its box over is not
  recorded at all.
- `OffsetViewportOrgEx` is written as `SetViewportOrgEx` of the result.
  Escapes (`MFCOMMENT` included) and `SetMapperFlags` leave no record;
  `gdi_comment` writes `EMR_GDICOMMENT`.
- `SetArcDirection` is written just before the next arc that uses it.
- Point records use their 16-bit forms when every coordinate fits.
- Bounds are inclusive device pixels. A stroke reaches the miter limit times
  half the device width plus one for mitred strokes (`Rectangle` frames and
  geometric miter joins), and half the width rounded up plus one otherwise;
  one-pixel pens add nothing. Arcs, chords and pies count their drawn sweep,
  `*To` records include the current position (unless `PolyDraw` opens with a
  move; after an arc, a one-pixel pen counts the floored logical point and
  the device pixel the exact point rounds up to), arcs, chords and pies span
  their figure's floored and rounded-up extremes, and a flood fill claims
  the whole device. Under rotation or shear, points count the pixels their
  exact 28.4 positions lie across, and a box its four corners, its far edges
  exclusive except for a rectangle's; ellipses, rounded rectangles, arcs,
  chords and pies (with a visible, non-inside-frame pen) instead span their
  drawn figure's floored and rounded-up 28.4 points, Bézier control points
  included. Record and header bounds
  are clipped to the clip region's bounding box; a figure with neither pen
  nor brush adds nothing.
- Transfer sources are written as `GetDIBits` returns a source DC's bitmap:
  bottom-up, zero-padded, with their image size. Indexed sources carry a full
  zero-padded colour table and declare none used; 4-bpp sources are re-matched
  by colour, so indices past a short table become the first black entry.
  16- and 32-bpp sources are `BI_BITFIELDS` (5-5-5 and 8-8-8 by default). The
  record's background is the DC background colour, or for indexed sources the
  nearest table colour to it. Masks and monochrome pattern brushes are 1-bpp
  without a colour table (`DIB_PAL_INDICES`); a 32-bpp device bitmap brush
  becomes a bit-field DIB pattern brush. Packed DIB pattern brushes and pens
  are re-encoded the same way; `SetDIBitsToDevice` and `StretchDIBits` keep
  the DIB as given. A legacy (Bitmap16) source is selected into a memory DC
  compatible with the recording DC: a monochrome or reference-depth bitmap
  selects and the transfer leaves no record, while any other depth fails to
  select and the transfer records the memory DC's default 1x1 monochrome
  bitmap.
- Bitmap brushes carry a `0x20000000` DWORD before their BitmapInfo. A DIB
  pattern pen carries it in place of the header size; the player reads such
  a header as a 40-byte one.
- Fonts are written as `LOGFONTEXDV`: the LOGFONT, empty full name, style and
  script, and a design vector with no axes.
- `AngleArc` leaves the current position at the exact end point, floored.
  `ArcTo` leaves it at the arc's 28.4 end, floored to a logical point; in
  `GM_COMPATIBLE` its ellipse fills the recorded, inclusive box while its
  radials are measured against the box as given.
- Header bounds count what reaches the device: drawing inside a path bracket
  only measures the path, which `StrokePath` and `FillPath` then add, and a
  point-list record inside the bracket has empty bounds of its own. An
  excluded clip rectangle shrinks the clip box to what it leaves, and
  `SelectClipPath` clips to the bounding box of the path's fill coverage under
  the DC's polygon fill mode. A widened path is its widened outlines, so
  overlapping caps can cancel. Shapes and arcs take the playback figures; in
  `GM_COMPATIBLE`, `AngleArc` builds them as in `GM_ADVANCED`, and `ArcTo` as
  described above. A path without figures makes no region: `SelectClipPath`
  then keeps the clip. A failed `PolyDraw` is still recorded and leaves the
  path as playback describes. The region's box also reaches, for each
  figure without area (an open line closed onto itself), the scan row each
  non-horizontal edge ends at: the first row whose pixel centre it does not
  reach, above the coverage, or the row before it below. A recording DC's
  cached device position follows playback's, except that its drawing calls
  refresh a valid cached position under the current transform instead of
  dropping it; after an arc under rotation or shear, a one-pixel pen's
  bounds count only the exact end point's pixel.
- A wide stroke reaches past its figure's 28.4 bounds by, on each axis, the
  larger device magnitude of the pen width's (w, w) and (w, -w) vectors,
  halved, plus one pixel; square caps add half of that again, and mitred
  strokes (`Rectangle` frames, and geometric pens with miter joins) take it
  times the miter limit. The low edges round down and the high edges up. A
  call following an arc starts from the exact 28.4 point the arc left.
- Without an explicit frame, the frame is the bounds in 0.01 mm of the
  reference device; the header's micrometre extension is the reference
  display's size at 96 DPI.

Recordings of the covered calls are byte-identical to native ones
([`test_emf_recorder.py`](../test/unit/emf/test_emf_recorder.py)). Text records
as `EMR_EXTTEXTOUTW`: ANSI text through the font's code page, advances from
GetTextExtentExPoint-style logical extents unless given (character extra and
justification included; neither has a record), GM_COMPATIBLE font scales of
0.01 mm per logical unit from the page transform, and bounds from the text
cell, opaque and clip rectangles (a rotated cell does not widen over leading
ink, even with explicit advances;
[`test_recorded_text_bounds.py`](../test/unit/emf/test_recorded_text_bounds.py)). GDI leaves an odd-length string's padding
uninitialized; the recorder writes zeros. Recording text needs the selected
face, from the recorder's `fonts`. Null object and palette selections fail
without a record, as natively; so do pattern brushes from device bitmaps other
than 1- and 32-bpp, DIB pattern brushes and pens from RLE DIBs, transfers with
masks that are not 1-bpp, and source-less `MaskBlt`. Compressed or truncated
transfer sources record their decoded bitmap.

## Geometric pens

Wide pens are widened as native GDI widens a path
([`widener.py`](../src/pillow_wmf/widener.py)), point for point: `WidenPath`
replaces each figure with the outlines, and a wide stroke fills them with the
winding rule. `Rectangle` frames are the exception described under
transforms.

- Each figure is walked line by line. A Bézier is flattened as it is walked:
  its first piece takes the start tangent and its last piece the end tangent
  (or the piece's chord where that tangent is zero) as the direction that
  chooses pen vectors, and the joints between its pieces are always round.
  Every other joint, including those at the ends of a Bézier, uses the pen's
  join. Zero-length lines are skipped.
- The pen is held as its first half, from a vertex to the opposite one, after
  the vertex preceding that half around the pen, so its first edge is the
  reverse of its last. A binary search over the edges' cross products with
  the line direction finds the draw vertex where their sign changes, negated
  when the first edge's cross product is negative. The draw vector is that
  vertex rounded to the half-pixel grid, ties away from zero. The
  perpendicular runs from half the adjacent edge before the draw vertex along
  the edge with the smaller cross product, by the share of the other, divided
  with rounding at the half; each component snaps to the half-pixel grid, x
  ties toward zero and y ties away from it.
- A pen with round joins and round or square caps (every `CreatePen` pen)
  uses draw vectors for its round joins and round caps; other pens use
  perpendiculars there. Joints inside a curve always use draw vectors.
- Each line contributes its vector on both sides of the figure. A round join
  walks the pen's vertices between the two lines' draw vertices on the outer
  side, each moved one unit toward the joint when the joint lies on a whole
  pixel; the walk's ends are included according to which neighbouring edge
  each draw vertex lies nearer. Without draw vectors throughout, the inner
  side passes through the vertex, walks back and passes through it again; with
  them it passes through the vertex once. A bevel passes through the vertex
  on the inner side. A miter adds its tip on the outer side: the lines
  through the two offsets along the lines' chords intersect in single
  precision, rounded half away from zero, and the tip is kept when its vector
  from the joint, taken back through the world transform to whole world
  units, is no longer than half the pen width times the miter limit
  (compared squared, in single precision).
- Round caps walk half the pen from the line's draw vertex. Square caps extend
  along the line by the direction scaled, in single precision, by half the
  pen's world width over the direction's length in whole world units, each
  component rounded half away from zero; flat caps join the two offsets.
- A closed figure becomes its left side and its reversed right side. An open
  figure becomes one outline: the start cap, the left side, the end cap and
  the reversed right side. A figure of one point is a round-capped dot, and
  nothing for other caps.
- Vectors are taken to whole world units through the inverse world transform,
  rounding half away from zero; an identity transform converts the 28.4
  components directly, rounding down.
- Predefined geometric styles are multiples of the width (dash 3:1, dot 1:1,
  and so on); user styles are logical lengths. On predefined styles, round
  and square caps pull each dash end back by one width, so dots become
  zero-length dashes; user styles are not pulled back. Each line is measured
  in whole world units, its length in single precision, and style lengths are
  consumed along it in single precision: a dash ends where its length runs
  out, at the line's end included, and a gap only strictly inside the line.
  Dash ends lie on the line by its single-precision unit vector, rounded half
  away from zero. A dash keeps the direction, chord and joint kinds of the
  lines it covers, and a zero-length dash still has caps.
- On a closed figure a dash still drawing at the closing vertex runs on into
  the first dash as one figure, whose outline starts with the right side up
  to the closing joint, reversed. A closed figure drawn as one dash stays
  closed.
- Cosmetic alternate and user styles step through device pixels, user style
  entries in units of three pixels like the predefined styles. Cosmetic pens
  are always one pixel wide and solid.
- A `CreatePen` style is ignored by `WidenPath`: the pen widens as the solid
  pen of its width. A cosmetic `ExtCreatePen` pen cannot be widened; the call
  fails and keeps the path.
- Hatched and DIB pattern pens fill the widened footprint with the brush,
  tiled from the brush origin like any brush; a DIB pattern pen's LOGBRUSH
  colour is its colour usage.

## Gradient fills

`GradientFill` maps each vertex to a whole device pixel and writes inside the
clip region; ROP2 does not apply:

- Rectangles shade from the corner nearer the leading edge, whichever index
  holds it. Each 16-bit channel advances by a floored 16.16 step per pixel
  and keeps its top 8 bits. The far column or row is not drawn.
- Triangles ([`gradient.py`](../src/pillow_wmf/gradient.py)) clamp their
  vertex channels to 0xff00 and cover rows from the top vertex to the row
  before the bottom vertex; each row runs from the ceiling of its left edge
  crossing to before the ceiling of its right one. Each channel's plane is
  stepped in 48-bit fixed point: floored per-pixel and per-row slopes over
  the doubled area, and a half-unit bias at the top vertex. A row starts
  with the colour its leftmost edge reaches, or a horizontal edge's exact
  vertex colour without the bias, and pixels keep each channel's top 8
  bits.
- A mesh whose vertices span 0x4000 pixels or more either way is drawn as a
  stack, last triangle first: triangles outside the clip bounds are dropped
  and any edge longer than 0x4000 splits its triangle at the single-precision
  midpoint of its longest edge, the far half first, with fixed capacity for
  the added triangles and vertices. Drawing clamps shared vertex colours in
  place, so later midpoints see the clamped values.

## Colour adjustment

`SetColorAdjustment` changes only scaled `HALFTONE` copies, whether filtered
or replicated. Each channel maps through its own table
([`color_adjustment.py`](../src/pillow_wmf/color_adjustment.py)), built as the
native table builder does in six-digit fixed point (10^6 is one), in this
order:

1. the level becomes level / 255, rounded half up;
2. the channel's gamma (hundredths of a percent) raises it to a power,
   through GDI's fixed-point logarithm;
3. reference black and white stretch it;
4. contrast multiplies it by 1.015^contrast;
5. brightness adds 0.375 * brightness / 100;
6. `CA_LOG_FILTER` replaces it with log8(1 + 7v);
7. it is clamped to 0..1, and `CA_NEGATIVE` inverts it;

then it is rounded to the nearest 8-bit level.

Colourfulness, red-green tint and illuminants other than the default (D65)
mix channels. Native GDI then maps colours through a colour engine
([`color_engine.py`](../src/pillow_wmf/color_engine.py)), and the channel
tables above apply to the engine's output:

1. Pixels are ordered-dithered to 5 bits per channel: a channel byte `v`
   becomes `(256 + round(v * 7935 / 255) - d) >> 8`, with one threshold `d`
   per pixel shared by the three channels from a 66 x 65 table (64
   thresholds per row and a wrap that repeats the first).
2. The three 5-bit indexes select one of 32**3 precomputed colours. Each is
   its node `(r, g, b) / 31` taken to CIE XYZ with the sRGB primaries and
   the adjustment's illuminant as white, then to CIE L\*u\*v\*, where
   colourfulness multiplies the chroma by `1 + colourfulness / 100` and
   tint rotates its hue 0.6 degrees per step, and back to XYZ and sRGB under
   the D65 device white. Results outside the gamut are rescaled into it.
   All arithmetic is fixed point with six decimal places, rounded half
   up; cube roots go through six-digit base-10 logarithms.

Enlargements map source pixels as their scans are read, before the stretch
replicates or filters them; each scan read advances the dither one row.
Reductions map the reduced destination pixels, dithered at their
destination positions. Dithering starts at the first visible destination
column modulo 65 and at the first visible row, or the last one for a
vertically flipped transfer, whose dither rows count down. Scans start at
the first source column and row that a visible pixel samples, by the
stretch's centre-phase step, and:

- replication reads from there;
- the enlargement filter for up to five times the source size first reads
  two more scans, re-reading the bitmap's top row where it has none above
  (when mirrored, two scans whatever is above);
- larger enlargements, and mirrored ones up to five times, first read up to
  two real columns before; larger ones also read up to two real scans
  before and re-read the bitmap's last scan below it;
- scans repeated beyond the bitmap's edges are each dithered afresh.

The source's storage orientation does not matter.

## Right-to-left layout

Playback never sets the DC's layout. A `SETLAYOUT` with `LAYOUT_RTL` puts a
mirror, x' = device width - 1 - x in the header's reference device pixels,
between the page mapping and the frame fit; `LAYOUT_BITMAPORIENTATIONPRESERVED`
changes nothing more, and other bits leave the layout unchanged. The mirror is
saved and restored with the DC. Mirrored pictures usually land entirely
outside the target, so they draw nothing.

## Embedded metafiles

A GDIC multi-format comment (`GDICOMMENT_MULTIFORMATS`) plays the first of
its formats with the enhanced-metafile signature, as `PlayEnhMetaFile` does:
the embedded frame is fitted to the comment's output rectangle in the outer
metafile's logical units, then mapped by the outer world transform. The
embedded picture is not clipped to that rectangle. It plays inside a saved
DC with its own object table and the same start as a top-level playback,
so the outer clip becomes its meta region and the outer attributes and
objects do not reach it; the outer transform is set again after.
Nesting stops after eight levels.

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
- Under a uniform rotation (orthogonal axes of equal length) a pen within
  the small-pen table keeps its device-aligned shape. Each device axis
  rounds the logical width vector along it to 28.4 and truncates its length,
  so a pen narrows slightly at oblique angles.
- Wider pens, and every pen under a transform that does not keep circles
  round, are cubic ellipses on the transformed logical radius vectors: each
  component's full diameter is rounded to 28.4 and halved outward, the
  second vector is the image of the negative logical y radius, and both
  quarters of the semicircle are flattened outward from the first vector's
  axis. The axis-aligned wide pens are the special case.
- Under a non-uniform transform a `CreatePen` pen is a hairline when its
  transformed x diameter is below 1.5 pixels; a geometric pen never is.
- `Rectangle` frames are mitred: each body lies on the pen perpendicular
  used by geometric pens, one per box axis, taken from the two edges that
  leave the left-top corner and shared by both parallel edges. Other figures
  are widened as described under geometric pens.
- A wide `PS_INSIDEFRAME` pen insets the box at its transformed corners: the
  vectors (-width, width) and (width, width) are mapped through the
  world-to-device transform to 28.4 and halved, rounding up; the right-top
  corner moves by the first, the left-top by the second and the left-bottom
  back by the first. The corners are those of the box as given, in
  `GM_COMPATIBLE` too, where other boxes lose a pixel at the right and bottom.
  Shapes built into a path are inset the same way, and so is `ArcTo`, whose
  current position follows the inset arc. A box narrower than the pen on
  either axis is filled with the pen instead; in a path it keeps its full
  size. Arcs, chords and pies in such a box draw nothing, and `ArcTo` does
  nothing at all, leaving the current position.
- Geometric pens use the caps, joins and styles above with the realized pen.
- `PatBlt` and the DIB transfers (`BitBlt`, `StretchBlt`, `StretchDIBits`
  and `MaskBlt` records, any ROP3) cover the polygon fill of their
  destination rectangle's three 28.4 corners and the reflected fourth. Each
  covered pixel inverts its integer point against that parallelogram and
  takes the source sample at the floor, breaking exact ties as if the point
  were nudged right along device x; samples clamp into the source
  rectangle. The ROP then combines source, brush and destination as usual,
  and a `MaskBlt` mask chooses the ROP per source pixel. The stretch mode
  and colour adjustment do not apply.
- `AlphaBlend` and `TransparentBlt` sample the same way and then blend or
  skip the key colour exactly as unrotated.
- A legacy `BitBlt` or `StretchBlt` that reads the destination DC draws
  nothing: native GDI rejects a source DC under a rotating transform.
  Source-less pattern operations fill the parallelogram as `PatBlt` does.
- A direct `SetDIBitsToDevice` maps only its origin, rounded to a device
  pixel, and copies the scan lines unscaled and unrotated.
- `GradientFill` maps its vertices to whole device pixels. A rectangle is
  shaded as two triangles (left-top, right-top, right-bottom and left-top,
  right-bottom, left-bottom) whose corners take the colour of the edge they
  lie on.
- `AngleArc` and `ArcTo` strokes follow the curve constructions above.
- Clip rectangles become filled parallelograms: `IntersectClipRect` rounds
  the transformed corners to device pixels first, `ExcludeClipRect` keeps
  them in 28.4. `OffsetClipRgn` moves the clip by the offset mapped through
  the transform and rounded; `SelectClipRgn` regions are device pixels as
  always.
- `FillRgn`, `PaintRgn` and `InvertRgn` trace the region's outline (corner
  vertices only), map it to 28.4 and fill it as a polygon.
- `FrameRgn` widens that outline with a geometric pen twice the larger frame
  size wide, with mitred joins and the DC's miter limit, whose world
  transform squeezes the smaller axis by the sizes' ratio (an ellipse of
  twice the frame sizes in logical units), and paints the widened outline's
  winding fill within the region.

PlgBlt onto a parallelogram that is a whole-pixel device rectangle (its
corners on pixel boundaries, its edges along the axes) is a stretch: a copy
at equal extents outside `HALFTONE`, otherwise a stretch in the DC's stretch
mode, a negative extent mirroring the source. Its mask lies over the
destination, so a mirrored axis reads the mask mirrored within the source
rectangle. Any other parallelogram inverts the mapping at each pixel's
integer point nudged right along device x: a source column or row on an
exact boundary is the one just right of the point. Its mask is read at the
source pixel. A mask bit of 1 copies the source pixel.

## Playback behaviours not yet modelled

- EMF+ (GDI+) drawing, which native GDI playback does not draw either.
- Synthetic bold italic above 50 pixels per em under an identity transform
  differs from native along slanted edges.
