# Integer curve flattening

Curve paths and polygonal pens share the integer hybrid-forward-differencing
flattener in `geometry.py`. Exact midpoint subdivision is not interchangeable:
arithmetic shifts during step-size changes affect the emitted vertices.

## Shared circle controls

Ellipse, RoundRect, full Arc quadrants and cubic pen outlines share a signed
integer circle coefficient. Multiply the oriented radius by `0x729d7775` and
arithmetically shift by 32 to obtain the control inset. This approximates
`1 - 4*(sqrt(2)-1)/3`; recomputing the irrational expression is not equivalent
at large radii. `gdi_math.circle_control` expresses the multiply as an oriented
handle length for all consumers.

## Forward-difference basis

For one axis with cubic controls `(a,b,c,d)`, the basis is:

- Position: `a`.
- Advance: `d-a`.
- End curvature: `6*(b-2*c+d)`.
- Start curvature: `6*(a-2*b+c)`.

Initialization adds ten fractional bits. Initial step halving delays curvature
rescaling; its error threshold is `0xffc0` shifted by twice the halving count.
After initialization the basis carries thirteen fractional bits. Each advance
uses additions; arithmetic right shifts perform precision-losing step changes.
The steady error threshold is `0x7fe00`, with parent error divided by four
compared against `0x1ff80`. Doubling is allowed only when the remaining step
count is even. Emit coordinates using `(position + 0x1000) >> 13`.

Step history can make geometrically symmetric quarters round differently.
Preserve that history rather than imposing a global halfway-rounding correction.

## Large curves

Controls spanning at least 16384 fixed units on either axis select the
large-curve precision path. Python's unbounded integers do not remove the need
to model this switch.

The large path carries 28 fractional bits. Its outer walk uses curvature error
`196608 << 28`; convert each interval back to rounded 28.4 controls before an
inner walk uses error `64 << 28`. Reconstructing handles divides inverse-basis
numerators by 18 towards zero, then rounds to device fixed coordinates.
This two-level rounding is part of the algorithm. Both walks share the small
path's advance/halve/double operations; only the small path uses lazy initial
scaling.

[Flattening tests](../test/unit/wmf/test_flatten.py) retain complete paths on
both sides of the precision switch and through coarse subdivision.
[Circle-control tests](../test/unit/wmf/test_circle_controls.py) exercise the
integer coefficient and signed rounding. Pixel comparisons exercise the same
flattener through shape and pen rendering.
