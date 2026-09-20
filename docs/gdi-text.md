# GDI text support and development plan

The target is Windows WMF playback, including text's effects on subsequent
drawing. Glyph rasterization uncertainty must not weaken existing exact tests.

## Current support

Font creation, selection and saved state retain the logical request. Text
drawing resolves an exact family, weight and italic style from caller-supplied
TrueType faces; it never searches host font directories or silently substitutes.

The supported rendering slice is single-byte Western, Central European,
Cyrillic, Greek, Turkish, Baltic and symbol text, with
positive or negative heights, zero-height realization, explicit average width,
axis scaling and translation. It supports natural or signed explicit
advances, character extra, justification, horizontal/vertical alignment,
TA_UPDATECP, opaque backgrounds, ETO_OPAQUE, ETO_CLIPPED and the DC clip.
Escapement, reflected axis mappings, underline/strikeout and explicitly enabled
style synthesis are implemented, but transformed text remains experimental:
rotated line/background bounds and reflected opaque extents still differ from
Windows. These are layout discrepancies, not merely glyph-mask differences.
RTL layout, automatic font selection and other encodings remain unsupported.
An initial logical font can be supplied with `FontCollection(default_font=...)`.
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
this does not provide Hebrew/Arabic shaping or RTL layout. The named
`text-options` probe checks these distinctions, current-position updates and
smoothing modes using the controlled test font. Glyph-index output and paired
horizontal/vertical advances remain unsupported rather than being ignored.

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
classic metafile playback. Probe ETO_GLYPH_INDEX, ETO_PDY and language/RTL flags
through actual WMFs before interpreting their payloads as modern API inputs.
See [WMF text flags](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/830cec14-2f3c-46f3-8f20-82b3da370573).

## First oracle experiments

Use a tiny, uniquely named, redistributable test font with known metrics,
asymmetric glyphs and a space. Use identical font bytes locally and on Windows;
load it privately for the oracle. Private loading is supported by
[AddFontResourceEx](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-addfontresourceexw).
Confirm the selected face and charset, not just successful font creation.

Start with compact, discriminating cases rather than a Cartesian-product matrix:

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

## Delivery gates

1. **Resolution and state:** font objects, selection and saved state; explicit
   environment and resolver policy. Unit-test layout against controlled metrics.
2. **First visible slice:** horizontal monochrome ASCII using the controlled
   font, explicit advances, alignment, clipping and background painting. Include
   an empty opaque text call and a current-position-dependent drawing operation.
3. **Measured layout:** derived advances, height/width realization, spacing and
   justification, rotation/reflection, underline/strikeout and synthesized styles.
4. **Encoding:** Western/Cyrillic and symbol runs, then DBCS and language
   processing. Add synthetic coverage where corpora provide no evidence.
5. **Real fonts:** pinned, legally usable font inputs, fallback diagnostics and
   corpus comparisons. Expand to raster/vector legacy fonts and smoothing only
   with explicit scope and evidence; do not substitute silently and call it parity.

The mask provider uses FreeType's monochrome TrueType path, but does not assume
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

Before freezing interfaces, resolve rounding order, actual charset selection,
malformed-byte behaviour, explicit spacing versus character extra/justification,
and the distinction between ordinary opaque backgrounds and ETO_OPAQUE.
Investigate one contract at a time and retain the resulting rules, not a history
of workflow runs or temporary experiments.
