# Machine guidance

- `/tmp` is RAM-backed on the development machine. Keep its use below roughly
  100 MB; use `/home/gaz/tmp` for larger temporary work, downloads and build trees.

# Testing and runner costs

- Run unit tests and exact compatibility comparisons locally (`make test-all`)
  or on Linux CI against the committed Windows PNGs. Do not run pytest or the
  development test suite on a Windows runner.
- Use Windows only as the native GDI oracle: generate missing reference PNGs or
  run the particular native probe needed to answer the current question.
- The reference workflow defaults to **no probes**. Select a named probe when
  needed, for example:
  `gh workflow run update-goldens.yml -f probe=patblt`.
- Never dispatch `probe=all` as routine verification, including after a shared
  implementation change. Get explicit user approval for a full native matrix
  run. Start with local regressions and narrowly targeted native probes instead.
- Reuse committed references. New WMFs need PNGs; changed cases are regenerated
  by deliberately deleting their PNGs. Do not add per-fixture metadata, relax
  pixel comparisons, or regenerate existing PNGs to hide implementation failures.
- Preserve the Linux preflight that skips Windows when no references are
  missing and no probe was selected. Changes to probe scripts, documentation or
  workflow configuration must not automatically launch Windows probes.
- Keep probes deterministic, capture useful discoveries as compact WMF/PNG
  regressions, and inspect each result before starting another native run.
- Treat runner time as a limited resource even on subsidised public repositories;
  forks may pay for the same workflows. Do not use repeated broad CI runs as a
  substitute for local investigation.

# Font work

- Keep non-font compatibility comparisons exact while developing text support.
- Use identical controlled font bytes locally and on the native oracle. Verify
  the selected native face; do not accept unnoticed font substitution as evidence
  about glyph rasterization. Separate layout/state errors from mask differences.
- Report font-blocked files separately; do not count them as pixel-perfect or
  assume their non-font operations have been validated.

# Documentation

- Document current contracts, algorithms, limitations and how to use or test
  them. Do not turn documentation into an investigation diary or changelog.
- Do not cite workflow runs, artifacts, commit hashes, Microsoft binary
  downloads, disassembly addresses or temporary files. Preserve useful findings
  as explanations and executable regression tests instead.
- Prefer stable specifications and links to maintained repository files. Avoid
  historical pass counts, failure counts and progress reports that become stale.
