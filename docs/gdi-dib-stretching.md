# DIB stretching: integer modes and native HALFTONE

`dib_stretch_blt`, `stretch_dib`, and mapped/scaled `dib_bit_blt` share transfer
preparation, scan selection and the existing brush/ROP3 compositor. Modes 1
(BLACKONWHITE), 2 (WHITEONBLACK) and 3 (COLORONCOLOR) are implemented for the
24-bit BI_RGB profile. Stretch mode defaults to 1 and is saved/restored with DC
state. Mode 4 implements HALFTONE reduction, enlargement and mixed-axis transfers
including reflected extents, large-image classification and source clipping
on both replication and filtered paths.

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

The 26 integer-mode references and all 16 HALFTONE references now pass exactly.
The HALFTONE failures were resolved in the renderer without skips, tolerances,
xfails or reference regeneration.

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
compatibility tests; their enlargement transfers now pass exactly too.

Initial rational-arithmetic experiments suggested area averaging followed by a
small sharpening stencil, but missed one-level differences in basis/2D probes.
The cumulative fixed-point weighting recovered below resolves those errors.

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

### Recovered reduction arithmetic

Microsoft's public symbol server supplies a
[2016 win32kfull.sys image](https://msdl.microsoft.com/download/symbols/win32kfull.sys/5801A1AB39D000/win32kfull.sys)
and its [matching public symbols](https://msdl.microsoft.com/download/symbols/win32kfull.pdb/E69974E58A0046638B59EEC62ECEE7DC1/win32kfull.pdb).
Inspection of `BuildShrinkAAInfo`, `ShrinkDIB_CX`, `ShrinkDIB_CY`, and
`ShrinkDIB_CY_SrkCX` identified 13-bit weights, remainder carry and the
intermediate shifts. The implementation expresses those arithmetic rules;
no binary, disassembly or extracted tables are included in the repository.
The older binary is a research lead, not an assumption that every Windows
version is identical: the committed runner outputs independently validate it.

For source extent S, destination extent D and destination index j, source
cell k occupies `[k*D, (k+1)*D)` and the destination cell occupies
`[j*S, (j+1)*S)`. Intersect those intervals to get `[left, right)`. Its weight is:

```
weight = floor(right * 8192 / S) - floor(left * 8192 / S)
```

Quantize the **cumulative boundaries**, then subtract; do not independently
round overlap fractions or source colour contributions. This is the closed
form of the native remainder-carrying scan accumulator. The weights sum to
8192 for every unclipped output sample, preserving all constant colours exactly.

- Both axes shrink: horizontally area-average and round each channel to a byte
  with `(sum + 4096) >> 13`, then vertically area-average without discarding
  the 13 fractional bits. Apply the destination-grid Laplacian:
  `(12*C - L - R - U - D) >> 16`, saturating to 0..255.
- One axis shrinks and the other is unchanged: retain the area accumulator's
  13 fractional bits and use `(6*C - previous - next) >> 15`, then saturate.
- Neighbour addresses repeat the destination edge sample. Do not clamp or
  round fractional accumulators before sharpening. Equal-size copies are
  unchanged.

`HalftoneReduction` is a lazy RGB bitmap view consumed by the existing blit
compositor, with bounded per-transfer caches, not a second rasterizer. Clipping
the destination does not restart the filter or replace its neighbours.

Run `.venv/bin/python scripts/analyze-halftone.py` to compare the **production**
sampler directly with the WMF inputs/Windows PNGs. Its old rational candidate
has been removed. All 9,966 measured channels match, including the 60 previous
one-level differences. A further 727 individual native-reference transfer tests
cover the non-enlarging portions of the atlases, including all 256 constant
levels, both DIB orientations and both stretch record types. These supplement
the unchanged full-image comparisons, which now pass on enlargement as well.

### Fixed-decimal enlargement

`BuildExpandAAInfo` and `ExpandDIB_CX` reveal an area/tent construction with a
nonlinear modification of the tent weights, rather than cubic interpolation:

1. Sharpen source samples as `clamp((6*C - previous - next) >> 2)`.
2. For S < D, build symmetric output-space weights at integer offsets
   `-radius..radius`, where `radius = ceil(D/S)-1` and `t = 1-abs(offset)*S/D`.
   Below 1/2, the weight is `t**1.414214`; above 1/2, `t**(1/1.414214)`.
   Exactly 1/2 is left unchanged. The native calculation uses six-decimal
   fixed-point `DivFD6`, `RaisePower`, and table-based logarithm/antilogarithm
   helpers. The implementation reproduces that fixed-decimal calculation;
   it does not substitute an ordinary floating-point power.
3. Convolve those weights with area overlaps of the source cells. Extend the
   already-sharpened endpoint samples outside the source rectangle. Normalize
   the combined weights to 8192, carrying remainders from the rightmost source
   contribution towards the left. Round the weighted result with
   `(sum + 4096) >> 13`.

Run `.venv/bin/python scripts/analyze-halftone-expansion.py` to compare the
production renderer against all enlargement/mixed transfers in the actual WMF
inputs. The earlier floating-point model has been removed.
For mixed-axis transfers in the 2D atlas, **reduce the shrinking axis first**,
including its sharpening and saturation, then enlarge the other axis. That
order matches all 1,980 tested channel samples; the opposite order does not.
This does not replace the two-axis reducer with two independent sharpen passes.

The logarithm table consists of `round(1e6 * log10(i/1000))` for integers
1000..10000. Native code packs differences of these samples; we generate their
mathematical values with a fixed Decimal context and cache them. All subsequent
interpolation uses integers, rounding ties away from zero. Logarithms normalize
to [1,10), interpolate the neighbouring samples, then restore the decimal
exponent. Antilogarithms invert that same piecewise-linear table, rounding the
fractional interval to 1/100000 before the final decimal scale division. Results
at or below log10(0.000001) saturate to one fixed-decimal unit. Local isolated
calls to the native arithmetic helpers confirmed all 1,000,001 possible
fixed-decimal tent inputs, with zero differences (including the builder's
exact-half bypass). No native executable code or extracted table data is a
runtime dependency.

Prefix sums integrate the discrete tent across source-cell boundaries. Each
destination sample has at most four source contributors, even at large scale
factors. Per-transfer sample caches are bounded. An explicit 65,536-tap resource
limit rejects excessively large kernels before allocation; it is a resource
bound, not a change in the sampling algorithm.

### Filtering versus replication

The same `ComputeAABBP` decision is visible in the older binary and a
[Windows 26100.9444 binary](https://msdl.microsoft.com/download/symbols/win32kfull.sys/A326E51B431000/win32kfull.sys)
with [matching public symbols](https://msdl.microsoft.com/download/symbols/win32kfull.pdb/5CD57181BCFDC5AE8F4819BEB1196F091/win32kfull.pdb).
The committed runner uses Windows Server 2025, build family 26100.

For each axis, compute `(destination * 1000 + 500) // source`. Both must exceed
667 to enable the content-classification path. The `+500` is literal, not half
the source extent. For small source images (at most 2304 pixels), classification
selects replication without counting colours. A reduction in **total pixel
area** overrides that decision and restores filtering. These interacting rules
explain 3x2-to-17x1 replication, 9x2-to-17x1 filtering, and 9x2-to-61x1
replication. For 3x3-to-17x1, the vertical ratio alone prevents replication.

Larger eligible images use the content-dependent colour census described below.

Replication itself has a different reduction phase from COLORONCOLOR. It builds
the inverse enlargement's run lengths and retains the **last source scan** in
each run. For S > D, output index j therefore selects
`(2*(j+1)*S - D - 1) // (2*D)`. For enlargement it uses
`((2*j+1)*S - 1) // (2*D)`: exact centre ties go to the earlier scan.
This resolves the original 7x9-to-5x13 colour atlas:
its shrinking axis selects `[0,2,3,5,6]`, not `[0,2,3,4,6]`. This is mode-specific
scan arithmetic, not a per-ratio rendering exception.

### Colour census and fast enlargement

`CheckBMPNeedFixup` clips the census to the available source rectangle. At most
2304 pixels always select replication. Through 16384 pixels it scans every row,
initially permitting `area >> 3` distinct colour keys. A row with no new colours
subtracts its width from the remaining area: reaching 2304 selects replication;
otherwise the new colour limit becomes `remaining >> 4`. Scanning stops when
the colour count exceeds the limit. Above 16384 pixels, it samples every sixth
row with a limit of 20 colours. The final count must be **less than** 20 to
select replication. Keys mask each channel with 252 when red equals blue.
The implementation uses a bounded set rather than the native linear search.

If both axes enlarge by at most 5x and the census does not select replication,
native `FastExpAA_CY`/`FastExpAA_CX` use replication runs of lengths 1 through 5.
Each run has a fixed three-source-sample stencil. The coefficients in
`RunExpansionAxis.kernels` express those native arithmetic stencils in units of
1/32; they are not fitted fixture corrections. For example, a one-pixel run uses
`(5*previous + 22*center + 5*next + 16) >> 5`, whereas a two-pixel run uses
`(previous + 3*center + 2) >> 2` then `(3*center + next + 2) >> 2`.

First apply the two-dimensional source Laplacian
`clamp((12*C - L - R - U - D) >> 3)`. Fast enlargement extends raw source rows
before sharpening, then filters vertically to bytes and horizontally to bytes.
General two-axis tent enlargement (either axis above 5x) sharpens the source,
extends its sharpened endpoints, then filters horizontally followed by vertically.
These different orders and boundary stages are observable in the PNGs.

### Boundary and ROP validation

48 additional WMF/PNG pairs cover the 2304/16384-pixel classifier thresholds,
19/20/21 colours, repeated rows, every fast run length, general two-axis expansion,
destination clipping, cropped source rectangles, all extent-sign combinations,
both DIB orientations and record types, replication source clipping, and all
256 ROP3 truth tables. References came from two missing-only Windows runs
([boundary census](https://github.com/bitplane/pillow-wmf/actions/runs/35210925583),
[enlargement runs](https://github.com/bitplane/pillow-wmf/actions/runs/35211885627));
all comparisons run locally with exact pixels.

HALFTONE reflects the realized output, including its sampling phase. Replication
reduction retains the last available source scan in a partially clipped run;
unavailable output pixels are black. Ternary operations instead use native
`EngStretchBltROP`'s downgrade to COLORONCOLOR, without changing the DC's stored
stretch mode. The shared brush/ROP compositor remains in use.

### Filtered source clipping

Filtering retains the original source/destination extents and fractional phase;
it does not rescale the available intersection. The native scan builders and
their consumers determine which output cells exist and how their history is
initialized:

- Reduction starts at the first destination area cell touched by the available
  source. Its leading missing contribution is prefilled from the first sample.
  The builder appends a closing entry at the trailing source edge, including
  when that edge is exactly on a destination-cell boundary. Horizontal reduction
  closes with zero for the unavailable contribution; the vertical loader repeats
  its final row. Sharpening clamps neighbours to this realized cell interval.
- The colour-census eligibility decision also selects a buffered source reader.
  A total-area decrease overrides replication, but does **not** disable that
  reader. A partial first reduction cell preloads and then replays its first
  scan. With only one available row, current is primed but previous is not, so
  replay reads zero. For a 5-to-3 vertical reduction with only the last requested
  row available, this leaves the 3276/8192 prefill contribution. This is a
  scan-history rule, not a changed kernel or a special ratio. Isolated native
  builder/reader/reducer calls reproduce it; the WMFs validate the full pipeline.
- General tent enlargement stops advancing its source cursor when it reaches
  the available edge, while fractional weights continue advancing. Thus it can
  continue producing varying output beyond the nominal source intersection.
  Unfilled history slots are zero; a single available sample still has its
  primed lookahead. One virtual leading sample can be primed, but skipping more
  than one starting sample makes the native builder return no transfer.
- Fast-run enlargement instead clips the emitted run interval at rounded
  source-to-destination boundaries and extends its raw edge samples before
  sharpening. Unavailable output cells are black. A wholly unavailable source,
  or a failed general-filter startup, leaves the destination untouched.

Reflection reverses the finished filtered output, including these boundaries;
it does not reverse or restart the filter weights.

37 additional WMF/PNG pairs cover clipped reduction/mixed transfers, all extent
signs, both DIB orientations and record types, fast/general large-image
enlargement, reflected trailing clips, and one-to-three-scan slivers. References
were generated in missing-only Windows runs:
[clipped transfers](https://github.com/bitplane/pillow-wmf/actions/runs/35212500830),
[large images](https://github.com/bitplane/pillow-wmf/actions/runs/35213271351),
[edge cells/reflection](https://github.com/bitplane/pillow-wmf/actions/runs/35213594840),
[vertical slivers](https://github.com/bitplane/pillow-wmf/actions/runs/35214679997),
[horizontal/grid boundaries](https://github.com/bitplane/pillow-wmf/actions/runs/35215512931).
All pixel comparisons run locally, with no tolerance or replacement of existing
reference images.

Additional depths and RLE compression are covered by the subsequent
[DIB format slice](gdi-dib-formats.md), including source-scan fixup and
format-dependent channel conversion. Logical palettes, legacy Bitmap16 and
fonts are still deferred.
