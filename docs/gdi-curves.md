# Integer curve flattening

The 257×193 `corpus-nopark` comparison exposed eight wrong stroke pixels.
Native cubic controls and the realized pen already matched; two flattened
vertices differed by one 28.4 unit. This was not a pen or scan-conversion rule.

[Native probe run 35326780819](https://github.com/bitplane/pillow-wmf/actions/runs/35326780819)
records controls, flattened vertices, widened outlines and isolated pen contours
for `switch`, `nopark`, and odd-sized `nopark`. All four odd-sized quarters'
native vertices are retained in `test/unit/wmf/test_flatten.py`.

## Shared circle controls

Ellipse, RoundRect, full Arc quadrants and cubic pen outlines share a signed
integer circle coefficient. Windows 26100.9444 multiplies the oriented radius
by `0x729d7775` and arithmetically shifts by 32 to obtain the control inset.
This approximates `1 - 4*(sqrt(2)-1)/3`; recomputing the irrational expression
is not equivalent at large radii. `gdi_math.circle_control` expresses that
multiply as an oriented handle length for all three constructors.
[Run 35329745361](https://github.com/bitplane/pillow-wmf/actions/runs/35329745361)
captures Ellipse and RoundRect controls for widths 88281–88283; width 88282
distinguishes the integer coefficient by one fixed unit without allocating
a large bitmap.

## Recovered arithmetic

The public-symbol Windows 10.0.26100.9444 `win32kbase.sys` identifies
`BEZIER32::bInit`, `BEZIER32::bNext` and
`HFDBASIS32::lParentErrorDividedBy4`. Inspection confirms integer hybrid forward
differencing, rather than recursive de Casteljau subdivision. The binary is
available from the [Microsoft symbol server](https://msdl.microsoft.com/download/symbols/win32kbase.sys/1AE11BF2346000/win32kbase.sys);
SHA-256 `a78ed89e69a0a12809af16da7da8bece1609e9acffc297b962c24245b745443d`.
No binary or disassembly is stored in this repository.

For one axis with cubic controls `(a,b,c,d)`, the basis is:

- Position: `a`.
- Advance: `d-a`.
- End curvature: `6*(b-2*c+d)`.
- Start curvature: `6*(a-2*b+c)`.

Initialization adds ten fractional bits. Initial step halving delays curvature
rescaling; its error threshold is `0xffc0` shifted by twice the halving count.
After initialization the basis carries thirteen fractional bits. Each advance
uses additions; arithmetic right shifts perform the precision-losing step
changes. The steady error threshold is `0x7fe00`, with parent error divided by
four compared against `0x1ff80`. Doubling is only allowed when the remaining
step count is even. Emission rounds using `(position + 0x1000) >> 13`.

These operations explain the asymmetry: the first and third `nopark` quarters
increase their step before the midpoint, producing Y=539 and Y=2548. The fourth
quarter's exact midpoint also has Y=2548.5, but emits 2549. Changing a global
halfway-rounding rule would fix one quarter and break another.

The same flattener serves curve paths and pen construction; there is no
fixture-, size-, quadrant- or stroke-specific correction.

## Large curves and the native precision switch

Windows translates controls to a local bounding box before using its 32-bit
implementation. Python's unbounded integers make that translation unnecessary,
but do not eliminate the need to reproduce the separate native precision paths.
Controls spanning at least 16384 fixed units on either axis select `BEZIER64`.

The large-curve path carries 28 fractional bits. Its outer walk uses curvature
error `196608 << 28`; each interval is converted back to rounded 28.4 controls
before an inner walk uses error `64 << 28`. Reconstructing the handles divides
the inverse-basis numerators by 18 towards zero, then rounds to fixed device
coordinates. This two-level rounding is part of the algorithm, not an optional
optimization. Both walks share the same advance/halve/double operations as the
small-curve path. The small path additionally has its lazy initial scaling.

[Boundary probe run 35328303288](https://github.com/bitplane/pillow-wmf/actions/runs/35328303288)
captures all vertices for spans 16368, 16384, 16400 and 65536, on both axes.
The last case exercises coarse interval subdivision. Unit regressions retain
the complete paths. The probe captures stored controls before flattening:
`PolyBezier` rounds its mapped inputs to device pixels, so requesting spans
16383/16384/16385 does **not** produce three distinct boundary cases. The
corrected probe uses adjacent pixel-aligned spans instead.

The shared implementation is expressed as named curve state and operations,
not register-like array indices. No runtime DLL dependency or binary assets
are introduced. These tests establish the measured paths, not exhaustive
parity over every possible coordinate, clipping or error-tolerance input.
