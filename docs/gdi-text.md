# GDI text support

## Installed-font policy

`SystemFontCollection()` is an opt-in alternative to controlled `FontCollection`
inputs. Discovery happens on first text use, using Fontconfig's installed-file
inventory when available, otherwise conventional system/user font directories.
Only static TrueType faces supported by the renderer are eligible; CFF and
variable fonts are ignored. `paths=[...]` supplies an application-owned inventory
instead. Font collection files are enumerated by face index; outlines are loaded
only when selected. No fonts are downloaded or discovered from WMF-supplied paths.

Resolution prefers the named family and requested weight/style, then known
substitute families for Arial/Helvetica, Times and Courier, then the LOGFONT
pitch/family category. Ties are deterministic within an inventory. Missing
Unicode glyphs use other installed faces, preserving the primary line metrics.
Input bytes retain the requested Windows code page regardless of the substitute's
advertised charset bits. If coverage is exhausted, `.notdef` is used and reported.

Wingdings uses the bundled Unicode mapping when its original face is unavailable.
Symbol uses the bundled Wine Symbol font and its legacy symbol cmap. Other
specialist encodings require separate mappings; an ordinary family substitute
does not establish correct symbol identity. Glyph-index runs require a matching
family, weight and style and cannot use the bundled substitutes; even matching
names cannot guarantee glyph-ID compatibility across different font versions.

The initial font is a 16-pixel-em Arial request unless `default_font=Font(...)`
is supplied. An environment with no usable ordinary fonts fails explicitly;
the symbol subset is not a general-purpose text font.

Use one collection per rendering job. Its `substitutions` list contains immutable
`FontSubstitution(requested, selected, reason)` records for family/style changes,
symbol mapping, glyph coverage and unresolved glyphs. `render(..., fonts=fonts)`
copies these into `image.info["wmf_font_substitutions"]`. This is a best-effort
display policy, not a Windows-parity claim. Explicit `FontCollection` behavior
and exact compatibility tests remain independent of installed fonts.

The target is Windows WMF playback, including text's effects on subsequent
drawing. Glyph rasterization uncertainty must not weaken existing exact tests.

## Current support

Font creation, selection and saved state retain the logical request. With the
controlled `FontCollection`, drawing resolves an exact family, weight and italic style from caller-supplied
TrueType faces; it never searches host font directories or silently substitutes.

The supported rendering slice is single-byte Western, Central European,
Cyrillic, Greek, Turkish, Baltic and symbol text, with
positive or negative heights, zero-height realization, explicit average width,
axis scaling and translation. It supports natural or signed explicit
advances, character extra, justification, horizontal/vertical alignment,
TA_UPDATECP, opaque backgrounds, ETO_OPAQUE, ETO_CLIPPED and the DC clip.
Escapement, reflected axis mappings, RTL device layout, underline/strikeout and
explicitly enabled style synthesis are implemented. Transformed real-font masks
remain approximate; controlled geometry regressions retain exact comparisons.
Other encodings remain unsupported by either font policy.
An initial logical font can be supplied with `FontCollection(default_font=...)`.

### Symbol fallback

`FontCollection(symbol_fallback=True)` opts into Wine's Symbol font when no
supplied Symbol face is available. `SystemFontCollection` enables it by default
and reports its use as `bundled symbol font`. A supplied/installed Symbol face
still takes precedence. The font is a separately licensed LGPL-2.1-or-later
resource; its licence, editable source and build script ship alongside the TTF.
See the [font resource notice](../src/pillow_wmf/fonts/symbol/README.md).

GDI forces SYMBOL_CHARSET when the requested family is named `Symbol`,
regardless of the requested charset. This is a legacy font-selection rule,
not a property of every symbol-cmap font: an ANSI request for a custom symbol
face may instead select a Latin font. Explicit collections reject that
incompatible request rather than silently substitute. Each Symbol byte retains its
legacy position (`U+F000 | byte`) in the symbol cmap. Greek letters, operators
and extensible bracket/integral pieces are not decoded as Latin text or linked
to unrelated Unicode glyphs. The fallback uses the defined Windows byte ranges
0x20–0x7E, 0xA1–0xEF and 0xF1–0xFE. Other slots use the missing-glyph policy;
notably 0xA0 is not a Euro mapping and 0xF0 is not an Apple logo in this encoding.
Outlines/hinting differ from Microsoft's Symbol and require visual review.
MT Extra, MT Symbol, Zapf Dingbats and other specialist fonts are not aliases.
When a requested symbol family is unavailable, `SystemFontCollection` follows
native missing-family selection for `SYMBOL_CHARSET`: a Roman family hint
uses Symbol; fixed pitch with a Roman or unspecified family uses Webdings;
other combinations use Wingdings. Webdings currently requires an installed
face; its absence is reported rather than silently choosing another encoding.
Installed requested faces take
precedence, and the chosen substitute may itself use a bundled fallback.
This is reported as `symbol charset fallback`, not equivalent glyph coverage
for the absent font. Explicit `FontCollection` policies remain unchanged and
require the requested family or an explicit alias. Glyph-index text cannot use
a substituted family.

MT Extra is version-sensitive: the small Equation Editor font and the larger
MathType font share a family name but differ in glyph coverage. Its encoding
includes spacing accents and extensible equation pieces, not just ordinary
Unicode mathematical characters. A Unicode substitution must preserve those
pieces and their positioning; matching a few letters or operators is insufficient.
See [Mozilla's encoding notes](https://www-archive.mozilla.org/projects/mathml/fonts/encoding/mtextra)
and [Wiris's font-version guidance](https://docs.wiris.com/editing-formatting-equations/mathtype-requires-a-newer-version-of-mt-extra-warning-message).
No MT Extra remapping is bundled. An installed face is preferred; generic
missing-family substitution does not imply fidelity to the absent font.
The `mt-extra` native probe privately loads the checksum-pinned Equation Editor
font from Microsoft, verifies its selection for DEFAULT/SYMBOL charset requests,
and reports other charset selections separately. The font is not committed,
packaged, or included in probe artifacts.
Missing glyphs raise by
default; callers may explicitly choose the supplied face's `.notdef` glyph.

Supported ANSI environments are Windows-1250, 1251, 1252, 1253, 1254 and 1257.
DEFAULT_CHARSET uses that explicit environment; ANSI_CHARSET selects 1252.
Decoding follows Windows NLS, including private-use mappings for otherwise
undefined Greek and Baltic bytes. The native byte tables in
[the encoding regression data](../test/unit/windows_sbcs.txt) cover all 256
inputs for each newly supported code page. Font coverage bits must advertise
the requested character set; a matching family name alone is insufficient.

NONANTIALIASED_QUALITY uses monochrome masks. DEFAULT_QUALITY, DRAFT_QUALITY and
PROOF_QUALITY share the same outline-font rendering policy, currently a
fixed RGB-subpixel profile matching the oracle's smoothing mode; it does not
inherit the Linux desktop configuration. Its FreeType filtering and direct RGB
coverage composition are an approximation, not an implementation of Windows'
ClearType contrast/filtering. ANTIALIASED_QUALITY uses grayscale coverage;
CLEARTYPE_QUALITY and CLEARTYPE_NATURAL_QUALITY use the RGB-subpixel policy.
These modes express smoothing intent, not exact Windows mask reproduction. Real-font
mapped ink placement also remains subject to visual comparison even when native
glyph indices and device advances agree.

Draft/proof are font-matching hints, not independent antialiasing algorithms.
Their legacy bitmap-font scaling/nearest-strike distinction is outside the
static TrueType outline backend. The original quality value remains in the WMF,
selected font and realization cache. Use the named `text-quality` probe to
compare default, draft, proof and explicit monochrome with identical native
font inputs; it checks small text, cell sizing and width-scaled rotated text.

With an explicitly supplied static TrueType face, mapper flags and the tested
output/clip precision hints do not change rendering. Reading-order and numeric
substitution flags are accepted for the supported left-to-right code pages;
this does not provide Hebrew/Arabic shaping. The named
`text-options` probe checks these distinctions, current-position updates and
smoothing modes using the controlled test font.

`ETO_GLYPH_INDEX` consumes little-endian WORD glyph IDs from the WMF text byte
array. It bypasses character decoding, shaping and font linking. An odd trailing
byte is ignored; spacing entries are consumed per glyph, not summed per byte
pair. Invalid IDs select the supplied face's `.notdef` glyph independently of
the Unicode missing-character policy.

`ETO_PDY` consumes horizontal/vertical advance pairs. Positive vertical values
move upwards along the font's vertical axis, before escapement rotation. Glyph
placement and current-position updates share the same accumulated displacement;
right alignment reverses the horizontal current-position displacement, not its
vertical component. Decorations use each glyph's unrotated ink span. A record
with PDY but no advance array does not draw or change the current position.

Unrotated opaque PDY output bounds the positioned glyph cells, including ink
overhangs and the final advance. Rotated output bounds the positioned ink spans
with a quarter-pixel horizontal margin, excluding the final advance. Horizontal
cell metrics use the ordinary font realization. Quarter turns use Windows cell
bounds and oblique transforms use the font-wide outline bounds, each expanded
by an em/64 safety margin and rounded outwards. Rotation combines separately
quantized 28.4 corner contributions; axis-aligned output includes the terminal
baseline column or row. Oblique ink spans are outward-rounded before placement.
Glyph masks remain subject to the approximation described above. The named
`text-placement` probe checks glyph IDs, spacing, alignment, background bounds
and decorations; `text-glyph-*` and `text-pdy-*` retain compact exact regressions.

RTL device layout mirrors reference points and swaps left/right alignment, not
the glyph masks or the byte sequence. Centre alignment uses the reflected
rounding direction. Mirrored rectangles retain pixel-edge ownership. With paired
advances, the alignment displacement has both horizontal and vertical components;
current-position updates are converted back to logical coordinates. The named
`text-rtl` probe covers alignment, rectangles, rotation, fractional mapping and
paired advances. These rules do not implement bidirectional script shaping.
Right alignment subtracts the fractional run width from the fixed-point device
reference before pixel rounding; rounding the two independently shifts text at
half-pixel boundaries.

Supply fonts explicitly, for example:

```python
from pillow_wmf import FontCollection, FontFace, RasterContext, play

fonts = FontCollection([FontFace.from_path("my-font.ttf")])
context = RasterContext(128, 128, fonts=fonts)
play(metafile, context, strict=True)
```

FontTools reads Windows ascent/descent and face metadata. The `freetype-py`
binding supplies individual masks, actual bitmap bearings and advances; glyph
indices come from the selected font cmap. GDI alignment, positioning, clipping and composition remain
in this renderer. TrueType instructions are honoured, with automatic hint
synthesis and embedded bitmap strikes disabled for this outline-only slice.
Odd-width centred runs choose the lower integer origin in monochrome output.
Windows line metrics are not interchangeable with FreeType's default metrics.
Glyph masks are checked against the context's bitmap-pixel budget before
allocation, including when another context has already cached a glyph.

Cell height is converted to fractional em size using the Windows ascent and
descent. Outline ppem, fractional advance scaling and line metrics are separate:
rounding one does not justify rounding all three. With no explicit width, classic
GDI uses vertical scale for the font's natural proportions. An explicit width
requests average character width, transformed on the horizontal axis.

Compatible-mode text ignores `lfOrientation` independently of `lfEscapement`.
Axis reflection keeps glyphs upright and left-to-right; an orientation reversal
changes the sign of escapement. Glyph outlines are transformed before mask
rasterization, using the same 16.16 rotation as baseline placement. Non-cardinal
rotations retain fractional advances; current-position conversion remains a
device-to-logical operation. Background and decoration contours use the existing
polygon rasterizer and text clipping, not image rotation or `ImageDraw`.
See [LOGFONT](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-logfonta)
and [compatible graphics mode](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setgraphicsmode).

`FontCollection(..., synthesize_styles=True)` permits requests for bold or italic
to use a supplied regular face when the exact requested face is absent. Exact
faces take precedence; synthesis is disabled by default. The monochrome model
widens outlines horizontally by one pixel and increases advances by one for
synthetic bold, and applies a measured approximately 0.34 shear for italic.
Real-font masks remain approximate. Underline and strikeout use the font's
`post`/`OS/2` metrics. Axis-aligned rules have at least one device pixel of
thickness, including quarter-turns and reflected mappings. Oblique rules retain
zero realized thickness and then paint nothing; nonzero thickness still draws.
Decorations do not alter advances. Style and transform parameters participate
in font-cache keys.

The named `text-styles` native probe uses original controlled glyphs and pinned
real fonts, verifies the selected font bytes and records outline coordinates.
The same mismatch gallery accepts `--synthesize-styles` for visual comparison.

For square device pixels, a matching ANSI-subset
[`VDMX` table](https://learn.microsoft.com/en-us/typography/opentype/spec/vdmx)
overrides line metrics at its recorded ppem sizes. Positive cell requests search
in ppem order: the first exact cell wins; an overshoot selects the preceding
entry. Repeated and non-monotonic cell heights must not be sorted or interpolated.
Requests outside the table use ordinary outline scaling. A cell-size override
also scales an explicitly requested width, preserving the font's aspect.

Text spacing retains fractional remainders until placement. Explicit advances
replace natural widths and justification but retain character extra. Placement
rounds accumulated device advances to nearest-even before the separate
logical-coordinate conversion. Break-character selection comes from native
font metrics rather than assuming every
font justifies ASCII spaces. Opaque bounds cover protruding glyphs as well as
the run advance. Text-updated current positions retain sublogical precision so
a subsequent line starts at the same device position.

The controlled font lives in `test/fonts`.
Run the focused native experiment with
`gh workflow run update-goldens.yml -f probe=text`. It measures WMF playback and
uploads its input/output pairs without replacing committed references.

## Real-font visual comparisons

The package includes a prebuilt, metric-compatible Wingdings subset derived from
Noto Sans Symbols 2, with its SIL Open Font License.
`FontFace.bundled_wingdings()` loads the packaged bytes without a download
or dependency on installed system fonts. Add the returned face to a
`FontCollection` to make it available for explicit selection or Unicode fallback.
It is not automatically substituted for Wingdings. Opt in explicitly with
`FontCollection(wingdings_fallback=True)` (or `text-gallery.py --wingdings-fallback`).
An available requested Wingdings face wins; otherwise this maps Wingdings bytes
to Unicode and selects the prebuilt derivative,
named `Pillow WMF Wingdings Fallback` (not Microsoft Wingdings).
This is not a Wingdings 2/3 or Webdings substitution, and it accepts only symbol
or default charset requests. Bold/italic synthesis still requires its own opt-in.

The mapping follows [Unicode's Wingdings mapping appendix](https://www.unicode.org/wg2/docs/n4363.pdf).
Space is preserved; control bytes, DEL and the unencoded Windows-logo byte raise
an error. Supplementary-plane symbols remain one character per input byte, so
explicit WMF advance arrays retain their original indexing. The fallback uses
measured Wingdings design-space advances, side bearings, glyph bounds, average
width, line metrics and underline/strikeout positions and thicknesses.
Each available Noto outline is affinely fitted to its
mapped glyph's design bounds before ordinary GDI realization. This rule is
independent of the input file, requested size and canvas. Native hinting and
original artwork are not reproduced; glyph appearance remains approximate.
The full source font and measured metrics live outside the package in `src/fonts/`.
`make font` invokes `scripts/build-font.py` to regenerate the derivative when
its inputs change; development, tests and distribution builds depend on it.
The generated TTF is committed so direct package installs need no font compiler
step. Both wheel and source distribution contain only the subset and licence;
no font conversion runs at import or rendering time.
The `wingdings` native probe verifies the selected Windows face
and reports metrics without distributing its outlines.
The bundled font does not cover every mapped character (including smileys,
zodiac signs and some numbered circles). Normal strict missing-glyph handling
still applies; callers can supply explicit Unicode fallback faces using
`Pillow WMF Wingdings Fallback` as the fallback-chain key. Such additional faces
retain their own metrics; they are not automatically made metric-compatible.

The named `real-text` probe downloads checksum-pinned, SIL Open Font License
Noto Sans and Noto Serif files and renders a small horizontal Latin size sweep.
It verifies the selected native face and its metric, outline and character-map
tables, and records glyph indices, advances and line metrics. It only generates
oracle data; comparisons run locally. Font inputs, their license, observations
and WMF/PNG pairs are uploaded together, not committed to this repository.

```sh
gh workflow run update-goldens.yml -f probe=real-text
# Download the real-text-probe artifact into a scratch directory, then:
python scripts/text-gallery.py /path/to/real-text-probe --output /path/to/gallery
```

Open `gallery/index.html` for Windows/local/difference images at selectable
integer zoom. Exact matches are omitted, while unsupported cases are reported
separately. The first batch uses explicit monochrome quality and negative
character heights; it does not establish default-quality or cell-height support.
Use the native observations to check glyph selection and spacing before treating
a visible difference as a mask-quality judgment. No tolerance is applied.

Use `probe=text-layout` for the horizontal sizing/mapping/spacing batch. It
includes controlled-font cases and records native device advances separately
from logical prefix extents. Reuse the same gallery output directory and pass
`--title` to identify the current review; previously approved size sweeps need
not be included in every new review. Keep scratch data under `~/tmp`.

For extracted release corpora, use parallel WMF and PNG trees:

```sh
python scripts/text-gallery.py /path/to/sources --reference-root /path/to/128x128 \
  --font /path/to/font.ttf --limit 12 --output /path/to/gallery
```

This selects text-bearing files, derives canvas sizes from the PNGs, and compares
all selected inputs while limiting the displayed mismatches. Supply each needed
font explicitly; unavailable faces remain blocked. Release font versions and
native substitutions are unverified, so these images support visual integration
review, not claims about controlled-font rasterizer parity.

## Boundaries

Keep the parser lossless: font names, text bytes and advance arrays remain raw.
Decoding belongs to playback, after font selection. Extend the existing GDI
calls rather than introducing a separate text-only playback path.

Keep four responsibilities separate:

- **Font resolution:** logical font request to physical font identity, face
  index, selected charset, metrics and any synthesized style. A missing face
  must have an explicit fallback policy; strict comparisons cannot silently use
  whatever font happens to be installed.
- **Text interpretation:** source bytes to characters and, where required,
  shaped glyphs. Preserve source-byte spans so spacing survives conversion.
- **GDI layout:** logical positions, advances, alignment, transforms, rounding
  and current-position updates. Keep this independent of glyph bitmap creation.
- **Glyph masks:** obtain masks and bearings from a replaceable font backend;
  paint them through the renderer's clipping and colour handling. Do not assume
  that text uses the same raster-operation rules as strokes: probe that contract.

Font selection participates in object lifetime and SaveDC/RestoreDC. Backend
caches must not become hidden DC state. A playback profile should explicitly
describe environment-dependent inputs such as default font, ANSI/OEM code pages
and font smoothing, rather than inheriting the host's locale or desktop settings.

## Encoding and font mapping

The WMF specification ties text decoding to the playback font. ANSI_CHARSET
uses Windows-1252; RUSSIAN_CHARSET uses Windows-1251. DEFAULT_CHARSET uses the
collection's `ansi_codepage` (1252 by default, or explicitly 1251). Face names
always use that environment code page, independently of the text charset.
Undefined single-byte values retain their same-valued control code points;
embedded NULs and tabs are not stripped or expanded. Explicit advances remain
byte-indexed. Other code pages, including OEM and DBCS, are not implemented.

A supplied face with a Microsoft symbol cmap uses that cmap under SYMBOL_CHARSET
or DEFAULT_CHARSET: bytes select U+F000–U+F0FF, not Unicode lookalike icons.
Glyph identity depends on the actual font file, including for Symbol/Wingdings.
For ordinary faces the requested code page must be advertised by the font;
unsupported charset/face combinations fail rather than silently substituting.
See the [WMF text record contract](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/7d07c44a-a828-4b82-9af0-e0a81cced5a8).

`FontCollection(..., aliases={"Requested family": "Supplied family"})` allows
deliberate substitution while retaining exact weight/style selection.
`missing_glyph="notdef"` opts into glyph zero of the selected face; the default
`"error"` preserves missing-glyph diagnostics.
`fallbacks={"Base family": ("Fallback family",)}` supplies an ordered chain of
faces for missing characters. Present base glyphs and base line metrics are
preserved; fallback faces supply their own masks and advances. All faces must be
supplied explicitly, with matching weight/style. This does not discover Windows
registry links or host fonts.

TextOut/ExtTextOut are not multiline formatters: tab, LF and CR shape to blank,
zero-width glyphs. Their byte positions still consume explicit advance entries.
This differs from TabbedTextOut/DrawText tab-stop or line-break processing.

Single-byte controls are shaped as runs. A run containing a missing nonblank
control (other than DEL) falls back to raw character output through the first
supplied fallback face and its remaining links. This can make an otherwise
invisible C1 control visible. Separators end runs, so this effect does not cross
tabs or line breaks.
The replacement is realized from the base font's cell height, rather than
reusing its original negative em request. Its raw GDI links inherit the
replacement's realized em size and horizontal scale. Ordinary character
fallback and control-run replacement therefore have distinct realizations;
neither changes the base font's line metrics or existing glyphs.
Raw linking skips zero-advance candidates and retries U+30FB (the standard GDI
link replacement character) if no linked face supplies the character. A suffix
consisting entirely of C1 controls bypasses linking and uses the raw face's
missing-glyph policy. Thus embedded NULs are neither string terminators nor
automatically zero-width: their width comes from the chosen font.
Matching native control output requires the corresponding fallback faces and
metrics. The explicit `.notdef` policy alone does not establish Windows parity.
Broad control-symbol coverage still needs matching native linked-font inputs;
outline-only rendering cannot establish parity with embedded bitmap strikes.
Fractional positive-cell advance rounding also retains discrepancies at some
half-pixel boundaries and needs further native verification.

The named `text-encoding` probe checks native byte conversion, glyph indices
and Western/Cyrillic/symbol WMF playback. Its controlled fonts are original test
geometry. Installed Symbol/Wingdings are queried without redistributing their
font files. Use `text-gallery.py --missing-glyph notdef` for the intentional
missing-glyph review; that choice is shown in the page.

For DBCS, ANSI ExtTextOut advances are byte-indexed: the two entries belonging
to a double-byte character are combined. Preserve that relationship instead of
zipping decoded characters with the raw array. Test malformed sequences, embedded
NULs and missing glyphs before choosing replacement behaviour. GDI can perform
language processing; neither unconditional modern shaping nor unconditional
one-character/one-glyph placement is a sound default.
See [ExtTextOutA](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-exttextouta).

The WMF option vocabulary does not establish how every flag works through
classic metafile playback. Glyph-index, paired-advance and RTL contracts above
are tested through actual WMFs, not inferred from modern API inputs.
See [WMF text flags](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/830cec14-2f3c-46f3-8f20-82b3da370573).

## Native verification

Use a tiny, uniquely named, redistributable test font with known metrics,
asymmetric glyphs and a space. Use identical font bytes locally and on Windows;
load it privately for the oracle. Private loading is supported by
[AddFontResourceEx](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-addfontresourceexw).
Confirm the selected face and charset, not just successful font creation.

Use compact, discriminating cases rather than a Cartesian-product matrix:

| Question | Distinguishing cases |
| --- | --- |
| Realization and metrics | Positive, negative and zero height; zero/explicit width; two mapping scales; default and missing face |
| Origins and advances | Baseline/top/bottom; left/right/centre; explicit/derived advances; negative/zero advances; fractional device scale |
| State effects | TA_UPDATECP followed by a line; SaveDC/RestoreDC; font switching and deletion; character extra and justification |
| Background and clipping | Empty ETO_OPAQUE; opaque background mode; ETO_CLIPPED intersecting the DC clip; text/background colours |
| Transforms | Rotation, reflection and anisotropic scaling; differing escapement/orientation |
| Decoding | Western high bytes, Cyrillic, symbol charset/default charset, a DBCS lead/trail pair with unequal advances |

Positive font height requests cell height; negative height requests character
height. Width is not a glyph bounding-box width, and compatible-mode rotation
has its own constraints. These belong in realization/layout, not ad-hoc Pillow
font-size adjustments. See [LOGFONTA](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/ns-wingdi-logfonta).

Use a named native probe for metrics and current-position observations, alongside
WMF/PNG fixtures for visible results. Reuse references, run comparisons on Linux,
and retain only compact regressions locally. Do not introduce per-image metadata
or launch a broad Windows matrix as routine verification.

The mask provider uses FreeType's TrueType rasterization, but does not assume
general GDI parity. Bitmap format and hinting target are separate controls; request and measure
both. Keep positioned glyphs inspectable so bitmap differences can be separated
from layout errors. See [FreeType glyph loading](https://freetype.org/freetype2/docs/reference/ft2-glyph_retrieval.html).

Exact unit assertions and controlled-font pixel comparisons remain the ratchet.
Real-font visual inspection supplements those tests; it does not justify a
blanket tolerance for every image containing text. Existing release PNGs may
reflect substituted or differently versioned fonts, so they alone cannot
identify a glyph rasterizer bug.

For real-font investigations, inspect native/local images and difference images
alongside the selected font, decoded characters, glyph identities, advances and
metrics. Cover Western/Cyrillic bytes, symbol cmaps, charset/font mismatches,
DBCS and missing glyphs, then sizes and style requests. Encoding and positioning
assertions can stay exact even where hinting or antialiasing needs visual review.
Do not assume that either TrueType or bitmap fonts guarantee cross-engine pixel
identity; qualify the actual font and rendering configuration.

## Further investigation

Wine is useful corroborating implementation evidence, not the Windows oracle.
Its [metafile playback](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/metafile.c)
routes classic font/text records through ANSI APIs and widens stored spacing
values. Its [text implementation](https://github.com/wine-mirror/wine/blob/master/dlls/gdi32/text.c)
and [font implementation](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/font.c)
are starting points for studying conversion, realization and fallback.

Investigate one contract at a time and retain the resulting rules, not a history
of workflow runs or temporary experiments.
