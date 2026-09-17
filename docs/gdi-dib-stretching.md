# DIB stretching: integer modes and remaining HALFTONE research

`dib_stretch_blt`, `stretch_dib`, and mapped/scaled `dib_bit_blt` share transfer
preparation, scan selection and the existing brush/ROP3 compositor. Modes 1
(BLACKONWHITE), 2 (WHITEONBLACK) and 3 (COLORONCOLOR) are implemented for the
24-bit BI_RGB profile. Stretch mode defaults to 1 and is saved/restored with DC
state. Mode 4 state is retained, but scaled HALFTONE rendering raises explicitly.

## Integer scan selection

For source extent S and destination extent D, the source scan selected for
destination index j is `floor((2*j + 1)*S / (2*D))`. This is the closed form of
the centre-phase integer DDA. Enlargement repeats scans, and COLORONCOLOR
reduction discards scans between selected positions.

For an axis being reduced in modes 1 and 2, accumulate scans after the previous
selected position through the current selected position, starting at zero for
the first destination scan. Combine the Cartesian product of the selected row
and column groups by bitwise AND or OR. For example, 9 scans reduced to 2 use
groups `[0,1,2]` and `[3,4,5,6]`; scans 7 and 8 are discarded. This is **not** an
area-box reduction. The rule is observed for RGB pixels, not only monochrome.

Source clipping must retain the selected scan; an incomplete preceding group
cannot cause an extra output pixel. Group iteration is bounded to the actual
bitmap, rather than the potentially much larger requested source rectangle.
Negative extents use the existing pixel-addressed normalization. Reflection
reverses source addresses within the clipped source interval without restarting
the DDA or reversing destination sample positions. Destination clipping also
leaves the sampling phase unchanged.

Unscaled transfers preserve the previously measured copy/ternary realization
rules in [DIB transfers](gdi-dib-transfers.md). Scaled ternary operations compose
the realized source, with black for unavailable pixels, into the full target.
All 256 ROP3 functions are tested for each implemented stretch mode.

`STRETCHDIB` uses DIB-origin source coordinates, whereas `DIBSTRETCHBLT` adapts
the coordinates as `DIBBITBLT` does. Both pass through the same source-Y
normalization and geometry. No per-fixture rendering paths are used.

## Native references and outstanding work

Thirty new WMF/PNG pairs cover the four modes, a matrix of enlargement/reduction
ratios, both DIB orientations, all combinations of extent signs, copy/ternary
operations, mapped `DIBBITBLT` clipping and all ROP3 tables. Windows only generated
missing PNGs; tests and pixel comparisons run on Linux/local machines.
The [initial reference run](https://github.com/bitplane/pillow-wmf/actions/runs/35200147446)
generated 24 cases; a subsequent missing-only run generated six ROP/mapping cases.

The 26 integer-mode references pass exactly. The four `dib-stretch-ratios-*-4`
references remain **ordinary failing tests**, not skipped, tolerated or xfailed.
They are the ratchet for HALFTONE discovery, so the full suite is not yet green.

HALFTONE observations that constrain the next investigation:

- Results show overshoot beyond the source colour range: a source red ramp
  beginning at 17 can produce values around 12 near the enlarged boundary.
  Positive-weight bilinear interpolation or averaging cannot explain that.
- Some two-axis enlargement cases match nearest-neighbour sampling, while
  mixed enlargement/reduction cases interpolate.
- At a 1x1 destination, the observed result can be an average, but extending
  that rule to other ratios does not explain the committed outputs.
- Changing the horizontal ratio can affect a channel constant across source
  columns. Separate one-dimensional impulse/constant-field probes are needed
  to isolate boundary handling, intermediate surfaces and quantization before
  choosing a kernel.

Sources inspected: Microsoft's [SetStretchBltMode](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setstretchbltmode),
[Wine's integer stretch setup](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dibdrv/bitblt.c),
and [current Wine sampling primitives](https://github.com/wine-mirror/wine/blob/master/dlls/win32u/dibdrv/primitives.c).
Wine's HALFTONE implementation uses bilinear interpolation; it does not explain
the native overshoot and has not been transcribed into this renderer.

### HALFTONE characterization and implementation cross-check

Eight further missing-only references isolate constants, horizontal/vertical
ramps and impulses (`halftone-kernel-*`), and independent RGB basis vectors
(`halftone-basis-*`). The basis vectors use a nonzero baseline so negative
weights remain measurable without clipping at black. These remain exact
compatibility tests; the renderer still explicitly rejects scaled HALFTONE.

Local rational-arithmetic experiments reproduce the non-enlarging ramp and
impulse cases with area averaging followed by a small sharpening stencil.
The candidate uses a gain of 1/8 when both axes shrink and 1/4 when only one
shrinks, with horizontal intermediate rounding in the two-axis case. This is
**not yet an established general algorithm**: two-dimensional colour patterns,
intermediate clipping and mixed enlargement/reduction still need validation.
The apparent enlargement curve alone is insufficient evidence for cubic
interpolation. Investigate scan accumulators, fixed-point quantization and
small separable passes before selecting a fitted reconstruction kernel.

The source cross-check does not supply the missing Windows algorithm:

- Wine's `calc_halftone_params` uses 32.32 fixed-point increments;
  `bilinear_interpolate` performs nested, rounded linear interpolation.
  Interior interpolation cannot produce the measured negative impulse lobes.
- libwmf's [GD bitmap drawing path](https://github.com/caolanm/libwmf/blob/master/src/ipa/xgd/bmp.h)
  uses endpoint-aligned floating-point coordinates and calls
  [`wmf_ipa_bmp_interpolate`](https://github.com/caolanm/libwmf/blob/master/src/ipa/ipa/bmp.h),
  which combines four pixels with bilinear weights and truncates/clamps the
  result. The drawing path does not select a HALFTONE-specific kernel and
  explicitly describes its extra destination-size increment as a fudge factor.
  Its boundary coordinate adjustments can extrapolate, but they do not explain
  our negative lobes around an interior impulse.

These are useful comparisons, not pixel-exact authorities. Neither inspected
path implements cubic scaling, nor does that rule out a cubic component in
Windows. The committed Windows outputs remain the oracle.

#### Follow-up measurements

Four more compact atlases are committed: `halftone-long-basis`,
`halftone-two-dimensional`, `halftone-cross-axis-basis`, and
`halftone-constant-levels`. They were generated in two missing-only Windows
runs ([long scans/2D](https://github.com/bitplane/pillow-wmf/actions/runs/35205366725),
[cross-axis/constants](https://github.com/bitplane/pillow-wmf/actions/runs/35206240518));
all mathematical comparisons run locally.

Run `.venv/bin/python scripts/analyze-halftone.py` to reproduce the reduction
hypothesis comparison directly from the WMF inputs, without regenerating data.
This is a read-only research tool, not another rendering path or a replacement
for the exact compatibility tests. Currently:

- The rational area/Laplacian candidate matches all 6,000 tested channel
  samples in the five constant/ramp/impulse atlases' non-enlarging transfers.
- The basis atlases expose 18 one-level differences out of 2,700 channel
  samples; the nonseparable 2D atlas exposes 40 out of 1,200, and the original
  colour-ratio atlas has two out of 66. All these differences are candidate
  values one above Windows, but ordinary floating-point evaluation, fixed-point
  truncation and fixed-point rounding experiments have **not** recovered the
  complete rounding rule. Do not introduce an epsilon or subtract one to fit
  these cases.
- All 256 constant grey levels survive both 3x3-to-2x1 and 3x3-to-3x1
  transfers exactly. A blanket colour-conversion bias cannot explain the
  differences.
- Long scans reveal curved responses and apparent slope changes around
  half-pixel boundaries. This constrains the interpolation construction, but
  does not establish a particular polynomial or filter family.
- There is a dispatch boundary within mixed enlargement/reduction, not simply
  “filter whenever either axis shrinks.” With identical source rows and a 1-row
  destination, 3x2-to-17x1 and 3x2-to-61x1 replicate scans; 3x3 with either
  destination width filters. A 9x2 source filters at width 17 but replicates at
  width 61. For the measured filtered cases, increasing source height through
  3, 5, 9 and 17 leaves the horizontal basis response unchanged.

The dispatch rule, enlargement reconstruction and exact reduction quantization
are still unresolved. Keep these as ordinary failing pixel tests rather than
promoting a close mathematical model into production.

Additional depths, compression, palettes and legacy Bitmap16 remain outside
this slice; fonts are still deferred.
