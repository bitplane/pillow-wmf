# Pie: an Arc closed through its centre

The [GDI Pie contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-pie)
specifies a counterclockwise elliptical wedge outlined with the current pen
and filled with the current brush. It neither uses nor updates the current
position.

Pie uses the same cubics as Arc, followed by a line to the drawn ellipse's centre
and a CLOSEFIGURE flag. That implicitly adds the return line to the first
curve point. The centre is retained in 28.4 device coordinates, including
half-pixel centres; it is not rounded to a whole pixel. A null pen uses the
same adjusted ellipse bounds as Arc and Chord, including the shifted centre.

Equal radial points and distinct points on the same ray retain the full
revolution **and both radial edges**. Substituting an Ellipse would lose that
interior stroke. Starting the figure at its centre would also change dashed
pen phase, so the measured command order matters.

`ellipse.arc_figure` constructs the common Arc/Chord/Pie figure. The only
difference is its closure: open, directly to the first point, or through the
centre. `RasterContext` submits it to the shared stroke-only or combined
fill/stroke operation. Pie introduces no separate scan converter or pixel
correction.

## Shared painting rules

- A round join at a 180-degree reversal walks half the pen contour. A zero
  cross product must not discard that join as if it were straight ahead.
- Cosmetic paths paint fill then stroke, with overlapping coverage. Their
  strokes preserve repeated pixel visits; XOR can cancel on a retraced edge.
  Opaque styled strokes paint gaps before foreground marks, preserving
  multiplicity in both passes, so foreground wins in copy mode.
- Wide combined paths exclude the stroked region from the fill. Copy mode
  flattens curves before widening, while other ROP2 modes retain the original
  cubic endpoint tangents. Stroke-only paths also retain those tangents.

These rules apply across primitives and ROP2 modes; Rectangle retains its
reserved-outline behaviour.

## Verification

WMF/PNG comparisons cover sweep atlases,
equal/same-ray/tiny sweeps, narrow and flat bounds, reversed bounds, reflections,
anisotropic mapping and current-position preservation. Pen/brush combinations
include wide outlines, dashed outlines, fill-only, outline-only and transparent
hatches. Chord and Pie share the fixture generator to exercise both closure
forms with the same inputs; their Windows expectations remain independent.

Unit regressions retain exact path coordinates, including null-pen centres and
full-revolution radial closure. Pixel comparisons run locally or on Linux
against Windows-generated references.
