# Font build inputs

`NotoSansSymbols2-Regular.ttf` is an unmodified static TrueType font from
[Noto's font distribution](https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSansSymbols2).
The copyright notice and SIL Open Font License 1.1 are in [OFL.txt](OFL.txt).

`wingdings-metrics.txt` contains measured advances and bounding boxes, in a
2048-unit design space, but no proprietary glyph outlines. The named
`wingdings` native probe reports these metrics and verifies the selected face.

Run `make font` to rebuild the renamed, metric-compatible subset in
`src/pillow_wmf/fonts/`. The same conversion rule applies to every available
mapped outline; it does not depend on individual WMFs or canvas dimensions.
The build removes hinting instructions that would be invalid after transforming
the outlines, retains Noto's licence, and fixes timestamps for reproducibility.
These source inputs are not shipped in the wheel or source distribution.
