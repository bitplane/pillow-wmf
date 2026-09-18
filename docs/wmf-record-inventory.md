# WMF record inventory

Specification baseline: Microsoft [MS-WMF], revision 18.0, 2024-04-23. This is a scope inventory, not a claim of implementation support.
See [format scope](wmf-format-research.md) for architecture and caveats.

Source: [Microsoft's specification](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/4813e7fd-52d0-4f42-965f-228c8b7488d2),
sections 2.1.1.1, 2.1.1.17, and 2.3. Section numbers below refer to that revision.
Codes are the enumeration values; record-function high bytes are not universally
fixed identifiers. Preserve the original function word when reading.

## Top-level records: 70 codes

Every entry needs reader/writer coverage, including preserved reserved fields,
applicable optional fields, and malformed-input tests. Playback and rendering
coverage must be tracked separately when implementation starts.

### Bitmap transfers (6)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_BITBLT` | `0x0922` | 2.3.1.1 | Bitmap16; with-source and no-embedded-source layouts. |
| `META_DIBBITBLT` | `0x0940` | 2.3.1.2 | DIB; with-source and no-embedded-source layouts. |
| `META_DIBSTRETCHBLT` | `0x0B41` | 2.3.1.3 | DIB; two layouts, independent source/destination sizes. |
| `META_SETDIBTODEV` | `0x0D33` | 2.3.1.4 | DIB scan range and color usage; unsigned coordinate fields in spec. |
| `META_STRETCHBLT` | `0x0B23` | 2.3.1.5 | Bitmap16; two layouts, independent source/destination sizes. |
| `META_STRETCHDIB` | `0x0F43` | 2.3.1.6 | DIB, color usage, ROP3, source/destination sizes. |

### Control (1)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_EOF` | `0x0000` | 2.3.2.1 | Stream terminator; no drawing. |

### Drawing (20)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_ARC` | `0x0817` | 2.3.3.1 | Fixed fields; operation-specific state/geometry tests. |
| `META_CHORD` | `0x0830` | 2.3.3.2 | Fixed fields; operation-specific state/geometry tests. |
| `META_ELLIPSE` | `0x0418` | 2.3.3.3 | Fixed fields; operation-specific state/geometry tests. |
| `META_EXTFLOODFILL` | `0x0548` | 2.3.3.4 | Boundary/surface mode; destination-dependent fill. |
| `META_EXTTEXTOUT` | `0x0A32` | 2.3.3.5 | Raw text, conditional rectangle, padding, optional advances. |
| `META_FILLREGION` | `0x0228` | 2.3.3.6 | Explicit region and brush handles. |
| `META_FLOODFILL` | `0x0419` | 2.3.3.7 | Destination-dependent boundary fill. |
| `META_FRAMEREGION` | `0x0429` | 2.3.3.8 | Explicit region and brush handles; frame dimensions. |
| `META_INVERTREGION` | `0x012A` | 2.3.3.9 | Destination-dependent output. |
| `META_LINETO` | `0x0213` | 2.3.3.10 | Fixed fields; operation-specific state/geometry tests. |
| `META_PAINTREGION` | `0x012B` | 2.3.3.11 | Fixed fields; operation-specific state/geometry tests. |
| `META_PATBLT` | `0x061D` | 2.3.3.12 | ROP3 family with no source bitmap. |
| `META_PIE` | `0x081A` | 2.3.3.13 | Fixed fields; operation-specific state/geometry tests. |
| `META_POLYLINE` | `0x0325` | 2.3.3.14 | Signed point count; PointS array. |
| `META_POLYGON` | `0x0324` | 2.3.3.15 | Signed point count; PointS array. |
| `META_POLYPOLYGON` | `0x0538` | 2.3.3.16 | Polygon counts, per-polygon lengths, concatenated point array. |
| `META_RECTANGLE` | `0x041B` | 2.3.3.17 | Fixed fields; operation-specific state/geometry tests. |
| `META_ROUNDRECT` | `0x061C` | 2.3.3.18 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETPIXEL` | `0x041F` | 2.3.3.19 | Fixed fields; operation-specific state/geometry tests. |
| `META_TEXTOUT` | `0x0521` | 2.3.3.20 | Byte count, raw text, padding, then coordinates. |

### Object management (11)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_CREATEBRUSHINDIRECT` | `0x02FC` | 2.3.4.1 | Fixed fields; operation-specific state/geometry tests. |
| `META_CREATEFONTINDIRECT` | `0x02FB` | 2.3.4.2 | Logical font; preserve face-name bytes. |
| `META_CREATEPALETTE` | `0x00F7` | 2.3.4.3 | Start field is 0x0300 when creating. |
| `META_CREATEPATTERNBRUSH` | `0x01F9` | 2.3.4.4 | Deprecated but played by Windows; special bitmap/reserved layout. |
| `META_CREATEPENINDIRECT` | `0x02FA` | 2.3.4.5 | Fixed fields; operation-specific state/geometry tests. |
| `META_CREATEREGION` | `0x06FF` | 2.3.4.6 | Scan bands and repeated endpoint counts. |
| `META_DELETEOBJECT` | `0x01F0` | 2.3.4.7 | Free file slot; verify selected/saved object behavior. |
| `META_DIBCREATEPATTERNBRUSH` | `0x0142` | 2.3.4.8 | Style-dependent interpretation; verify BS_PATTERN case. |
| `META_SELECTCLIPREGION` | `0x012C` | 2.3.4.9 | Region selection; verify reset/null convention experimentally. |
| `META_SELECTOBJECT` | `0x012D` | 2.3.4.10 | Resolve file index to backend object; palette selection is separate. |
| `META_SELECTPALETTE` | `0x0234` | 2.3.4.11 | Fixed fields; operation-specific state/geometry tests. |

### DC state (31)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_ANIMATEPALETTE` | `0x0436` | 2.3.5.1 | Only reserved palette entries are modified. |
| `META_EXCLUDECLIPRECT` | `0x0415` | 2.3.5.2 | Fixed fields; operation-specific state/geometry tests. |
| `META_INTERSECTCLIPRECT` | `0x0416` | 2.3.5.3 | Fixed fields; operation-specific state/geometry tests. |
| `META_MOVETO` | `0x0214` | 2.3.5.4 | Fixed fields; operation-specific state/geometry tests. |
| `META_OFFSETCLIPRGN` | `0x0220` | 2.3.5.5 | Fixed fields; operation-specific state/geometry tests. |
| `META_OFFSETVIEWPORTORG` | `0x0211` | 2.3.5.6 | Fixed fields; operation-specific state/geometry tests. |
| `META_OFFSETWINDOWORG` | `0x020F` | 2.3.5.7 | Fixed fields; operation-specific state/geometry tests. |
| `META_REALIZEPALETTE` | `0x0035` | 2.3.5.8 | Fixed fields; operation-specific state/geometry tests. |
| `META_RESIZEPALETTE` | `0x0139` | 2.3.5.9 | Fixed fields; operation-specific state/geometry tests. |
| `META_RESTOREDC` | `0x0127` | 2.3.5.10 | Signed absolute/relative saved-state reference. |
| `META_SAVEDC` | `0x001E` | 2.3.5.11 | Save context state; not a copy of destination pixels. |
| `META_SCALEVIEWPORTEXT` | `0x0412` | 2.3.5.12 | Signed numerators/denominators; zero and rounding probes. |
| `META_SCALEWINDOWEXT` | `0x0410` | 2.3.5.13 | Signed numerators/denominators; zero and rounding probes. |
| `META_SETBKCOLOR` | `0x0201` | 2.3.5.14 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETBKMODE` | `0x0102` | 2.3.5.15 | Optional reserved word. |
| `META_SETLAYOUT` | `0x0149` | 2.3.5.16 | Graphics/text layout; reserved word. |
| `META_SETMAPMODE` | `0x0103` | 2.3.5.17 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETMAPPERFLAGS` | `0x0231` | 2.3.5.18 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETPALENTRIES` | `0x0037` | 2.3.5.19 | Modify selected palette; variable entries. |
| `META_SETPOLYFILLMODE` | `0x0106` | 2.3.5.20 | Optional reserved word. |
| `META_SETRELABS` | `0x0105` | 2.3.5.21 | Reserved/undefined; playback must ignore. |
| `META_SETROP2` | `0x0104` | 2.3.5.22 | 16 Boolean mix modes; optional reserved word. |
| `META_SETSTRETCHBLTMODE` | `0x0107` | 2.3.5.23 | Four modes; optional reserved word. |
| `META_SETTEXTALIGN` | `0x012E` | 2.3.5.24 | Alignment flags; optional reserved word. |
| `META_SETTEXTCHAREXTRA` | `0x0108` | 2.3.5.25 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETTEXTCOLOR` | `0x0209` | 2.3.5.26 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETTEXTJUSTIFICATION` | `0x020A` | 2.3.5.27 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETVIEWPORTEXT` | `0x020E` | 2.3.5.28 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETVIEWPORTORG` | `0x020D` | 2.3.5.29 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETWINDOWEXT` | `0x020C` | 2.3.5.30 | Fixed fields; operation-specific state/geometry tests. |
| `META_SETWINDOWORG` | `0x020B` | 2.3.5.31 | Fixed fields; operation-specific state/geometry tests. |

### Escapes (1)

| Record | Code | Section | Particular scope |
| --- | --- | --- | --- |
| `META_ESCAPE` | `0x0626` | 2.3.6.1 | Length-delimited extension envelope; see escape inventory. |

## Headers outside the opcode enumeration

| Structure | Bytes | Section | Responsibility |
| --- | --- | --- | --- |
| META_HEADER | 18 | 2.3.2.2 | Type/version, word sizes, object capacity, maximum record size |
| META_PLACEABLE | 22 | 2.3.2.3 | Optional prefix, bounds, units per inch, XOR checksum |

## Escapes: 60 enumerated functions

These are subfunctions of META_ESCAPE, not 60 additional top-level record codes.
There are 43 dedicated payload sections (2.3.6.2 through 2.3.6.44); 17 functions
are enumerated without a dedicated payload section. All need lossless envelope
preservation; implementing their printer effects is a separate scope decision.
An absent payload section is not evidence that the payload is empty.

The embedded enhanced-metafile entry is included because it is part of the WMF
format. Preserve its data; interpreting that embedded format is deferred.

| Escape | Code | Payload section |
| --- | --- | --- |
| `NEWFRAME` | `0x0001` | 2.3.6.27 |
| `ABORTDOC` | `0x0002` | 2.3.6.2 |
| `NEXTBAND` | `0x0003` | 2.3.6.28 |
| `SETCOLORTABLE` | `0x0004` | 2.3.6.38 |
| `GETCOLORTABLE` | `0x0005` | 2.3.6.16 |
| `FLUSHOUT` | `0x0006` | Not separately specified |
| `DRAFTMODE` | `0x0007` | Not separately specified |
| `QUERYESCSUPPORT` | `0x0008` | 2.3.6.37 |
| `SETABORTPROC` | `0x0009` | Not separately specified |
| `STARTDOC` | `0x000A` | 2.3.6.44 |
| `ENDDOC` | `0x000B` | 2.3.6.13 |
| `GETPHYSPAGESIZE` | `0x000C` | 2.3.6.21 |
| `GETPRINTINGOFFSET` | `0x000D` | 2.3.6.22 |
| `GETSCALINGFACTOR` | `0x000E` | 2.3.6.24 |
| `META_ESCAPE_ENHANCED_METAFILE` | `0x000F` | 2.3.6.25 |
| `SETPENWIDTH` | `0x0010` | Not separately specified |
| `SETCOPYCOUNT` | `0x0011` | 2.3.6.39 |
| `SETPAPERSOURCE` | `0x0012` | Not separately specified |
| `PASSTHROUGH` | `0x0013` | 2.3.6.29 |
| `GETTECHNOLOGY` | `0x0014` | Not separately specified |
| `SETLINECAP` | `0x0015` | 2.3.6.40 |
| `SETLINEJOIN` | `0x0016` | 2.3.6.41 |
| `SETMITERLIMIT` | `0x0017` | 2.3.6.42 |
| `BANDINFO` | `0x0018` | Not separately specified |
| `DRAWPATTERNRECT` | `0x0019` | 2.3.6.10 |
| `GETVECTORPENSIZE` | `0x001A` | Not separately specified |
| `GETVECTORBRUSHSIZE` | `0x001B` | Not separately specified |
| `ENABLEDUPLEX` | `0x001C` | Not separately specified |
| `GETSETPAPERBINS` | `0x001D` | Not separately specified |
| `GETSETPRINTORIENT` | `0x001E` | Not separately specified |
| `ENUMPAPERBINS` | `0x001F` | Not separately specified |
| `SETDIBSCALING` | `0x0020` | Not separately specified |
| `EPSPRINTING` | `0x0021` | 2.3.6.14 |
| `ENUMPAPERMETRICS` | `0x0022` | Not separately specified |
| `GETSETPAPERMETRICS` | `0x0023` | Not separately specified |
| `POSTSCRIPT_DATA` | `0x0025` | 2.3.6.30 |
| `POSTSCRIPT_IGNORE` | `0x0026` | 2.3.6.32 |
| `GETDEVICEUNITS` | `0x002A` | 2.3.6.17 |
| `GETEXTENDEDTEXTMETRICS` | `0x0100` | 2.3.6.18 |
| `GETPAIRKERNTABLE` | `0x0102` | 2.3.6.20 |
| `EXTTEXTOUT` | `0x0200` | 2.3.6.15 |
| `GETFACENAME` | `0x0201` | 2.3.6.19 |
| `DOWNLOADFACE` | `0x0202` | 2.3.6.8 |
| `METAFILE_DRIVER` | `0x0801` | 2.3.6.26 |
| `QUERYDIBSUPPORT` | `0x0C01` | 2.3.6.36 |
| `BEGIN_PATH` | `0x1000` | 2.3.6.3 |
| `CLIP_TO_PATH` | `0x1001` | 2.3.6.6 |
| `END_PATH` | `0x1002` | 2.3.6.12 |
| `OPENCHANNEL` | `0x100E` | 2.3.6.35 |
| `DOWNLOADHEADER` | `0x100F` | 2.3.6.9 |
| `CLOSECHANNEL` | `0x1010` | 2.3.6.7 |
| `POSTSCRIPT_PASSTHROUGH` | `0x1013` | 2.3.6.34 |
| `ENCAPSULATED_POSTSCRIPT` | `0x1014` | 2.3.6.11 |
| `POSTSCRIPT_IDENTIFY` | `0x1015` | 2.3.6.31 |
| `POSTSCRIPT_INJECTION` | `0x1016` | 2.3.6.33 |
| `CHECKJPEGFORMAT` | `0x1017` | 2.3.6.4 |
| `CHECKPNGFORMAT` | `0x1018` | 2.3.6.5 |
| `GET_PS_FEATURESETTING` | `0x1019` | 2.3.6.23 |
| `MXDC_ESCAPE` | `0x101A` | Not separately specified |
| `SPCLPASSTHROUGH2` | `0x11D8` | 2.3.6.43 |

The enumeration codes above are intentional: the payload prose for
POSTSCRIPT_IDENTIFY and POSTSCRIPT_INJECTION disagrees with the enumeration
(0x1005/0x1006 versus 0x1015/0x1016). This discrepancy needs an independent Windows
SDK/native check before typed interpretation. Raw preservation is unaffected.
