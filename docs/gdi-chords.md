# Chord: closed Arc paths

The [GDI Chord contract](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-chord)
defines an elliptical arc closed by a straight segment, filled with the selected
brush and outlined with the selected pen. It neither uses nor changes the
current position.

`RasterContext` uses `arc_cubics`, adds the closing line, and submits the closed
`DevicePath` to the existing combined fill/stroke operation. There is no Chord
scan converter. Native `GetPath` marks the final cubic endpoint CLOSEFIGURE;
the explicit closing line is our representation of that implicit edge.

## Geometry

Identical radial endpoints still take the
ordinary angular construction, including its terminal quadrant arithmetic and
degenerate boundary piece. They do not substitute Ellipse's four canonical
cubics.

The default stock BLACK_PEN has width zero. The initial raster pen therefore remains a device hairline under
scaling, instead of widening as a logical-width-one pen would.

In compatible graphics mode, their drawn ellipse center moves by -1/2 device
pixel in each axis and each radius shrinks by 1/4 pixel relative to the usual
exclusive-right/bottom ellipse. Equivalently, the fixed-point left/top edges
move by -4 and right/bottom edges by -12. Radial normalization still uses the
original untrimmed box. This is a shared pre-flattening geometry rule, not a
fill-mask adjustment. The requested null-pen width does not affect it.

## Coverage

Fractional dashed paths start phase zero at the first emitted GIQ pixel, for
both open and closed figures. Their phase advances through the full unclipped
pixel span; closure does not introduce a separate phase rule.

Sweep atlases cover small/large counterclockwise sweeps, solid and
wide pens, null pen/brush, dashed outlines and transparent hatches. Edge
images cover coincident points, identical rays, a tiny angular loop, narrow/flat
bounds and reversed bounds. Mapping cases cover reflections and anisotropic
scaling, with a following LineTo checking current-position preservation.

All expectations come from Windows-rendered WMFs. Unit tests also retain exact
native control points. This is measured coverage, not exhaustive compatibility
for every possible Chord input or DC state. [Pie](gdi-pies.md) shares the
Arc figure construction; [RoundRect](gdi-roundrects.md) reuses the canonical
ellipse quarters.
