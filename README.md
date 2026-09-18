# pillow-wmf

A Windows Metafile loader for Pillow. Under development; no plugin yet.

The goal is a pixel-perfect version with WMF and EMF playback and recording
using a GDI driver.

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

The `all` choice runs every native probe and should only be used deliberately,
with explicit approval when an agent is doing the work. This keeps runner costs
down for forks as well as the main repository.

- [Implementation contracts and coverage](docs/wmf-implementation.md)
- [Format research and scope](docs/wmf-format-research.md)
- [Complete record inventory](docs/wmf-record-inventory.md)
- [Stroke algorithms and native validation](docs/gdi-strokes.md)
- [ROP2 painting and native validation](docs/gdi-rop2.md)
- [Text support and development plan](docs/gdi-text.md)
