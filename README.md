# pillow-wmf

A Windows Metafile loader and renderer for Pillow. Requires Python 3.13 or newer.

WMF playback and recording share a GDI backend. Non-font rasterization targets
Windows pixel parity; text uses modern font rendering and best-effort substitution.
EMF rendering is not implemented by this package.

This is a correctness-first, pure-Python GDI emulator. Per-pixel drawing can be
slow on large canvases; it is not yet a high-throughput document-image loader.

```python
from PIL import Image
import pillow_wmf  # registers the WMF loader ahead of Pillow's built-in stub

with Image.open("drawing.wmf") as image:
    image.load(size=(640, 480))
    image.save("drawing.png")
```

Importing the package replaces Pillow's WMF opening entry point, while EMF
continues through Pillow's existing handler. The loader uses installed fonts
automatically, including bundled Symbol/Wingdings fallbacks. It does not download
fonts. Systems without usable ordinary fonts still need fonts installed.
Substitutions are reported in `image.info["wmf_font_substitutions"]`.

Placeable WMFs default to their header size at 72 DPI. `load(dpi=144)` selects
another density; `load(size=(width, height))` selects an explicit canvas instead.
Plain WMFs, or invalid placeable sizing metadata, default to 128×128 and require
an explicit size for other dimensions. Placeable bounds initialize the logical
window; WMF mapping records can override it. Choose options before first loading
pixels; reopen the image to change them. `load(fonts=FontCollection(...))`
overrides automatic font selection. WMF saving through Pillow is not provided;
use `Recorder` for WMF output.

For explicit canvas/mapping control without placeable-header fitting:

```python
from pathlib import Path
from pillow_wmf import render

image = render(Path("drawing.wmf").read_bytes(), (640, 480))
image.save("drawing.png")
```

`render` returns an RGB Pillow image and raises if playback is incomplete.
The size sets the canvas; the WMF's mapping records control drawing coordinates,
without implicit fit-to-bounds scaling. Text requires explicitly supplied fonts.
Use `FontCollection(faces, default_font=Font(...))` to configure the initial
font, including its size, for files that draw text without selecting one;
`Font` is available from `pillow_wmf`. No host font is selected silently.
For best-effort rendering with installed fonts, pass
`fonts=SystemFontCollection()` (also exported from `pillow_wmf`). This opts into
family and missing-glyph substitution, including the bundled Wingdings mapping.
Symbol also has a bundled fallback; its font resources carry their own
[LGPL licence and source](src/pillow_wmf/fonts/symbol/README.md).
Inspect `image.info["wmf_font_substitutions"]` for the replacements used.
This does not promise Windows font metrics or pixel parity.
For partial output, use `play(metafile, context, strict=False)` and inspect the
returned omissions. Malformed embedded bitmap inputs are omitted before state
changes, but malformed WMF structure and resource-limit violations remain fatal.

`make test` runs unit tests; `make compatibility` runs the compatibility suite;
`make test-all` runs both. Synthetic WMFs and their Windows-rendered reference
PNGs are committed as compatibility inputs. Delete a PNG to have the Windows
workflow recreate it. Compatibility tests compare rendered pixels with these PNGs.

Unit and compatibility CI run on Linux. The reference workflow checks for
missing PNGs on Linux before allocating a Windows runner; ordinary pushes never
run native probe matrices. Manual dispatch defaults to no probes. To investigate
one area, select its probe explicitly, for example:

```sh
gh workflow run update-goldens.yml -f probe=patblt
```

Each dispatch selects one named probe; there is no catch-all choice. Broad
native testing requires deliberate selection and explicit approval when an
agent is doing the work. This keeps runner costs down for forks too.

- [Implementation contracts and coverage](docs/wmf-implementation.md)
- [Format research and scope](docs/wmf-format-research.md)
- [Complete record inventory](docs/wmf-record-inventory.md)
- [Stroke algorithms and native validation](docs/gdi-strokes.md)
- [ROP2 painting and native validation](docs/gdi-rop2.md)
- [Text support](docs/gdi-text.md)

## Releasing

`make dist` builds the wheel and source archive. The tag-triggered Linux release
workflow runs the existing tests, checks distribution metadata, and smoke-tests
the installed wheel before uploading. Configure the repository's `PYPI_TOKEN`
Actions secret with a PyPI upload token, then push a tag exactly matching
`project.version` in `pyproject.toml` (without a `v` prefix). Never reuse a
published version. No corpus download or Windows runner is required for release.
