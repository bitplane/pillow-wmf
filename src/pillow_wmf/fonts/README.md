# Pillow WMF Wingdings Fallback

`PillowWMFWingdingsFallback.ttf` is a subset of Noto Sans Symbols 2, renamed
and adapted to measured Wingdings design metrics. It contains Noto-derived
artwork, not Microsoft's outlines. Its licence remains the SIL Open Font
License 1.1; see [OFL.txt](OFL.txt) for the copyright notice and full terms.

`FontFace.bundled_wingdings()` loads this prebuilt Unicode face offline.
`FontCollection(wingdings_fallback=True)` enables the associated byte mapping
when the requested Wingdings face is unavailable. Nothing is installed on the
host or regenerated at runtime.

From a repository checkout, `make font` rebuilds this file using
`scripts/build-font.py` and the source inputs in `src/fonts/`. Package
distributions contain only this derivative, not the full source font or the
build-time metrics table.
