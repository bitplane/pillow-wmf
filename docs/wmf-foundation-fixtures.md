# Compatibility fixtures

The local suite retains compact edge cases and regressions. The authoritative
synthetic selection is [local_regressions.py](../scripts/local_regressions.py),
grouped by mapping, curves, state, bitmaps and device behaviour.
[The generator](../scripts/generate-wmf-fixtures.py) uses the library recorder;
its `--corpus` option exports the complementary synthetic suite.

WMFs live beside a `128x128` directory containing their Windows-rendered PNGs.
Comparisons take the canvas dimensions from the PNG itself. Each active profile
must contain a PNG for every WMF in its parent directory; orphan PNGs, missing
references and unsupported playback fail tests. No per-image metadata is used.
See [the fixture contract](../test/compatibility/wmf/README.md).

## Updating references

1. Add or change a discriminating WMF and check its byte reproducibility.
2. For a changed input, deliberately delete its PNG. Existing references are
   never refreshed merely because code or WMF bytes changed.
3. Push. Linux preflight starts Windows only if references are missing.
   Windows renders the missing PNGs and commits them.
4. Pull and run `make test-all` locally. Inspect mismatches before changing the
   implementation; keep pixel comparisons exact.

Named native probes are separate, opt-in investigations. They do not run as
part of ordinary reference generation. Use their observations to establish
algorithms and retain useful boundaries as unit tests or compact WMF/PNG pairs.

The oracle's device profile and coordinate rounding rules are documented in
[coordinate mapping](gdi-coordinate-mapping.md). Related contracts cover
[layout](gdi-layout.md), [bitmap transfers](gdi-dib-transfers.md),
[strokes](gdi-strokes.md) and [text](gdi-text.md).
