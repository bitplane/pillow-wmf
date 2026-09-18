# GDI text support and development plan

The target is Windows WMF playback, including text's effects on subsequent
drawing. Glyph rasterization uncertainty must not weaken existing exact tests.

## Current support

Font creation, selection and saved state retain the logical request. Text
drawing resolves an exact family, weight and italic style from caller-supplied
TrueType faces; it never searches host font directories or silently substitutes.

The supported rendering slice is printable ASCII and ANSI charset, with
positive or negative heights, zero-height realization, explicit average width,
positive axis scaling and translation. It supports natural or signed explicit
advances, character extra, justification, horizontal/vertical alignment,
TA_UPDATECP, opaque backgrounds, ETO_OPAQUE, ETO_CLIPPED and the DC clip.
Rotation, reflection, synthesized styles, decorations, default-font selection
and other encodings remain explicitly unsupported. Missing glyphs also raise.

NONANTIALIASED_QUALITY uses monochrome masks. DEFAULT_QUALITY currently uses a
fixed RGB-subpixel profile matching the oracle's smoothing mode; it does not
inherit the Linux desktop configuration. Its FreeType filtering and direct RGB
coverage composition are an approximation, not an implementation of Windows'
ClearType contrast/filtering. Explicit smoothing modes are deferred. Real-font
mapped ink placement also remains subject to visual comparison even when native
glyph indices and device advances agree.

Supply fonts explicitly, for example:

```python
from pillow_wmf import FontCollection, FontFace, RasterContext, play

fonts = FontCollection([FontFace.from_path("my-font.ttf")])
context = RasterContext(128, 128, fonts=fonts)
play(metafile, context, strict=True)
```

FontTools reads Windows ascent/descent and face metadata. The `freetype-py`
binding supplies individual masks, actual bitmap bearings, glyph
indices and advances; GDI alignment, positioning, clipping and composition remain
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

Text spacing retains fractional remainders until placement. Explicit advances
replace natural widths and justification but retain character extra. Break
character selection comes from native font metrics rather than assuming every
font justifies ASCII spaces. Opaque bounds cover protruding glyphs as well as
the run advance. Text-updated current positions retain sublogical precision so
a subsequent line starts at the same device position.

The controlled font lives in `test/fonts`.
Run the focused native experiment with
`gh workflow run update-goldens.yml -f probe=text`. It measures WMF playback and
uploads its input/output pairs without replacing committed references.

## Real-font visual comparisons

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

The WMF specification ties text decoding to the playback font. Start with
Windows-1252 and Windows-1251, then symbol fonts and the remaining single-byte
charsets. DEFAULT_CHARSET and OEM_CHARSET require an explicit environment;
they are not aliases for UTF-8. Font face-name decoding is a separate question
from the encoding of text drawn with that font.

Keep requested and selected charsets distinct. In particular, a Symbol face
requested with DEFAULT_CHARSET cannot safely be treated as Western text merely
from its request. Determine symbol cmap selection and fallback through probes.
See the [WMF text record contract](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/7d07c44a-a828-4b82-9af0-e0a81cced5a8).

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
