# ROP2 painting

`SetROP2` selects one of the 16 Boolean functions of a source colour and the
existing destination colour. The [WMF enumeration][wmf-rop2] numbers those
functions from 1 to 16. Subtracting one gives a four-bit truth table for
`(source, destination) = 00, 01, 10, 11`. `paint.rop2` applies that same table
to every bit of each RGB channel. The default is `R2_COPYPEN` (13); the
selected mode is part of saved DC state.

The compositor runs after path coverage and application clipping. A stroke
first unions the pixels of all its segment bodies, caps and joins, so their
overlap paints once. For a filled outlined shape, the pen owns pixels covered
by the outline; the brush paints the remaining fill pixels. Separate drawing
calls still paint separately, so drawing the same XOR line twice cancels it.
This is one coverage/composition rule across lines, polylines, polygons,
rectangles and ellipses.

The Windows reference suite checks all 16 modes with nontrivial RGB source and
destination colours on both wide lines and solid fills. Further fixtures check
XOR joins, repeated drawing, matching and different pen/brush colours,
`SaveDC`/`RestoreDC`, and `SetPixel`. Native WMF playback showed that
`SetPixel` follows the selected ROP2 mode in this profile, including XOR and
NOP; it uses the same compositor here.

These probes validate the current true-colour memory bitmap profile. They do
not cover palette realization, pattern brushes, monochrome devices, or ROP3
bitmap transfers.

[wmf-rop2]: https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/781a06bd-af9b-48b7-8e7d-d922de0f9c26
