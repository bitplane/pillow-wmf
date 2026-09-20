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

Unscaled transfers preserve the copy/ternary realization
rules in [DIB transfers](gdi-dib-transfers.md). Scaled ternary operations compose
the realized source, with black for unavailable pixels, into the full target.
All 256 ROP3 functions are tested for each implemented stretch mode.

`STRETCHDIB` uses DIB-origin source coordinates, whereas `DIBSTRETCHBLT` adapts
the coordinates as `DIBBITBLT` does. Both pass through the same source-Y
normalization and geometry. No per-fixture rendering paths are used.

## HALFTONE reduction

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

Use `scripts/reference_compare.py CORPUS_DIR` to compare production rendering
against WMF inputs and Windows PNGs.

### Fixed-decimal enlargement

Enlargement uses an area/tent construction with a nonlinear modification of
the tent weights:

1. Sharpen source samples as `clamp((6*C - previous - next) >> 2)`.
2. For S < D, build symmetric output-space weights at integer offsets
   `-radius..radius`, where `radius = ceil(D/S)-1` and `t = 1-abs(offset)*S/D`.
   Below 1/2, the weight is `t**1.414214`; above 1/2, `t**(1/1.414214)`.
   Exactly 1/2 is left unchanged. Use six-decimal fixed-point division,
   exponentiation and table-based logarithm/antilogarithm operations, not an
   ordinary floating-point power.
3. Convolve those weights with area overlaps of the source cells. Extend the
   already-sharpened endpoint samples outside the source rectangle. Normalize
   the combined weights to 8192, carrying remainders from the rightmost source
   contribution towards the left. Round the weighted result with
   `(sum + 4096) >> 13`.

The same comparison command covers enlargement and mixed-axis transfers. Reduce
the shrinking axis first, including sharpening and saturation, then enlarge the
other axis.
This does not replace the two-axis reducer with two independent sharpen passes.

The logarithm table consists of `round(1e6 * log10(i/1000))` for integers
1000..10000. Native code packs differences of these samples; we generate their
mathematical values with a fixed Decimal context and cache them. All subsequent
interpolation uses integers, rounding ties away from zero. Logarithms normalize
to [1,10), interpolate the neighbouring samples, then restore the decimal
exponent. Antilogarithms invert that same piecewise-linear table, rounding the
fractional interval to 1/100000 before the final decimal scale division. Results
at or below log10(0.000001) saturate to one fixed-decimal unit. There is no
runtime dependency on native arithmetic helpers.

Prefix sums integrate the discrete tent across source-cell boundaries. Each
destination sample has at most four source contributors, even at large scale
factors. Per-transfer sample caches are bounded. An explicit 65,536-tap resource
limit rejects excessively large kernels before allocation; it is a resource
bound, not a change in the sampling algorithm.

### Filtering versus replication

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
For a 7x9-to-5x13 transfer, the shrinking axis selects `[0,2,3,5,6]`, not `[0,2,3,4,6]`. This is mode-specific
scan arithmetic, not a per-ratio rendering exception.

### Colour census and fast enlargement

The colour census is clipped to the available source rectangle. At most
2304 pixels always select replication. Through 16384 pixels it scans every row,
initially permitting `area >> 3` distinct colour keys. A row with no new colours
subtracts its width from the remaining area: reaching 2304 selects replication;
otherwise the new colour limit becomes `remaining >> 4`. Scanning stops when
the colour count exceeds the limit. Above 16384 pixels, it samples every sixth
row with a limit of 20 colours. The final count must be **less than** 20 to
select replication. Keys mask each channel with 252 when red equals blue.
The implementation uses a bounded set rather than the native linear search.

If both axes enlarge by at most 5x and the census does not select replication,
fast enlargement uses replication runs of lengths 1 through 5.
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

### Reflection and ROPs

HALFTONE reflects the realized output, including its sampling phase. Replication
reduction retains the last available source scan in a partially clipped run;
unavailable output pixels are black. Ternary operations instead downgrade to COLORONCOLOR, without changing the DC's stored
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
  scan-history rule, not a changed kernel or a special ratio.
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

Additional depths and RLE compression are covered by
[DIB formats](gdi-dib-formats.md), including source-scan fixup and
format-dependent channel conversion. [Logical palettes](gdi-palettes.md)
resolve into the same transfer pipeline. [Legacy Bitmap16](gdi-bitmap16.md)
covers modern playback and reuses that pipeline for source-free copies.
