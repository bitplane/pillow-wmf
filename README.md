# pillow-wmf

A Windows Metafile renderer for Pillow. Under development; no plugin yet.

The goal is a pixel-perfect version with WMF and EMF playback and recording
using a GDI driver.

This is a correctness-first, pure-Python GDI emulator. Per-pixel drawing can be
slow on large canvases; it is not yet a high-throughput document-image loader.

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
