# Symbol fallback

`symbol.ttf` is Wine's unmodified Symbol font, copyright Jon Parshall for
CodeWeavers (2009), distributed under LGPL-2.1-or-later. Its notices are also
embedded in the font. The complete licence is in `COPYING.LIB`.

The editable `symbol.sfd` source and upstream `genttf.ff` build script accompany
the font in both wheels and source distributions. These files come from
[Wine's font distribution](https://github.com/wine-mirror/wine/tree/wine-11.0/fonts).
They are separately licensed font resources, not WTFPL code.

To rebuild with FontForge, run from this directory:

```sh
fontforge -script genttf.ff symbol.sfd symbol.ttf
```

The packaged binary is the upstream font, not a newly generated derivative.
Its Microsoft symbol cmap preserves byte positions, including Greek letters,
mathematical signs and extensible equation pieces. It is not a Unicode font
alias and does not implement MT Extra, Wingdings or Zapf Dingbats.
At runtime, `FontFace.bundled_symbol()` limits cmap use to the Windows Symbol
repertoire, excluding Wine's PostScript Apple glyph at byte 0xF0. The font file
and editable source remain unmodified.
