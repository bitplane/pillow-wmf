# Pie: an Arc closed through its centre

The [GDI Pie contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-pie)
specifies a counterclockwise elliptical wedge outlined with the current pen
and filled with the current brush. It neither uses nor updates the current
position.

Native paths captured before implementation in
[run 35145099841](https://github.com/bitplane/pillow-wmf/actions/runs/35145099841)
show the same cubics as Arc, followed by a line to the drawn ellipse's centre
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

## Shared behavior exposed by holdouts

The initial 16 PNGs passed, but the independent matrix found 42 failures.
Four additional native WMFs retain representative failures locally. Resolving
them required correcting shared behavior, not the measured Pie path:

- A round join at a 180-degree reversal walks half the pen contour. A zero
  cross product must not discard that join as if it were straight ahead.
- Cosmetic paths paint fill then stroke, with overlapping coverage. Their
  strokes preserve repeated pixel visits; XOR can cancel on a retraced edge.
  Opaque styled strokes paint gaps before foreground marks, preserving
  multiplicity in both passes, so foreground wins in copy mode.
- Wide combined paths exclude the stroked region from the fill. Copy mode
  flattens curves before widening, while other ROP2 modes retain the original
  cubic endpoint tangents. Stroke-only paths also retain those tangents.

The last two rules are checked across all 16 ROP2 modes with cosmetic and wide,
solid and styled pens on Pie, Chord, Ellipse and Polygon (256 comparisons). The rectangle's
existing reserved-outline behavior is unchanged. These are observed Windows
execution differences, not coordinate-specific corrections.

## Verification

The initial 16 committed Windows PNGs cover six sweep atlases (96 individual wedges),
equal/same-ray/tiny sweeps, narrow and flat bounds, reversed bounds, reflections,
anisotropic mapping and current-position preservation. Pen/brush combinations
include wide outlines, dashed outlines, fill-only, outline-only and transparent
hatches. Chord and Pie share the fixture generator to exercise both closure
forms with the same inputs; their Windows expectations remain independent.

`scripts/probe-windows-pies.py` asserts 24 native path coordinate/type sequences
and compares 192 independent WMF renders covering additional bounds, sweeps,
pens, brushes, background modes, XOR and clipping. The expensive native probes
run only on manual workflow dispatch; ordinary fixture pushes still generate
only missing PNGs. Unit regressions retain measured path coordinates, including
null-pen centres and full-revolution radial closure.

These are measured compatibility cases, not a claim of exhaustive Pie parity.

[Run 35146563884](https://github.com/bitplane/pillow-wmf/actions/runs/35146563884)
passes all 192 holdouts, 256 composition comparisons, and the existing native
stroke, Arc, Chord and edge-case matrices. All 20 Pie references match locally.
