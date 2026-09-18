# ROP2 painting

`SetROP2` selects one of the 16 Boolean functions of a source colour and the
existing destination colour. The [WMF enumeration][wmf-rop2] numbers those
functions from 1 to 16. Subtracting one gives a four-bit truth table for
`(source, destination) = 00, 01, 10, 11`. `paint.rop2` applies that same table
to every bit of each RGB channel. The default is `R2_COPYPEN` (13); the
selected mode is part of saved DC state.

The compositor runs after path coverage and application clipping. Wide strokes
union segment bodies and joins before painting. Cosmetic strokes instead emit
pixels in path order: a retraced pixel is painted again, so XOR can cancel
within a single figure as well as across separate calls.
Opaque style gaps are emitted before foreground marks; both passes retain
repeated coverage, with foreground priority where the style retraces itself.

Filled cosmetic paths paint the brush fill first and then the outline; their
coverage can overlap. Wide combined fill/stroke excludes outline coverage from
the brush fill. Rectangle retains its existing reserved-outline contract.
Copy-mode combined painting flattens curves before widening; non-copy ROP2
modes preserve their endpoint tangents. See [Pie composition](gdi-pies.md). Overlapping writes may be invisible in
copy mode but significant under XOR.

The Windows reference suite checks all 16 modes with nontrivial RGB source and
destination colours on both wide lines and solid fills. Further fixtures check
XOR joins, repeated drawing, matching and different pen/brush colours,
`SaveDC`/`RestoreDC`, and `SetPixel`. Native WMF playback showed that
`SetPixel` follows the selected ROP2 mode in this profile, including XOR and
NOP; it uses the same compositor here.

ROP2 describes drawing composition on the RGB surface. Bitmap transfers use
[ROP3](gdi-patblt.md).

[wmf-rop2]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/781a06bd-af9b-48b7-8e7d-d922de0f9c26
