# Noto Sans Symbols 2

`NotoSansSymbols2-Regular.ttf` is an unmodified static TrueType font from
[Noto's font distribution](https://github.com/notofonts/noto-fonts/tree/main/hinted/ttf/NotoSansSymbols2).
It is distributed under the SIL Open Font License 1.1; see [OFL.txt](OFL.txt)
for the copyright notice and full terms. The font retains its own licence,
independently of the surrounding Python code.

Load it with `FontFace.bundled_symbols()`. Loading does not install it on the
host, select it automatically, or reinterpret Wingdings bytes as Unicode.
It provides Unicode symbol outlines, not Wingdings-compatible metrics or encoding.

The explicit Wingdings fallback builds a renamed OFL derivative in memory.
`wingdings-metrics.txt` holds measured advances and bounding boxes in Wingdings'
2048-unit design space; it contains no proprietary outlines. These metrics fit
the mapped Noto outlines before ordinary font realization. The original TTF
above is never modified. The native `wingdings` probe measures the source metrics
and verifies that Windows selected the expected face.
