# Styled cosmetic pens: measured behavior

Windows references under `test/compatibility/wmf/pen-style*` cover PS_DASH,
PS_DOT, PS_DASHDOT, and PS_DASHDOTDOT. The strict pixel tests include
near-circular ellipses and additional paths with major-axis switches.

Microsoft documents the [CreatePen style and width rules](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-createpen), the effect of [SetBkMode on styled gaps](https://learn.microsoft.com/en-us/windows/win32/api/wingdi/nf-wingdi-setbkmode), and the device's [fractional style-step state](https://learn.microsoft.com/en-us/windows/win32/api/winddi/ns-winddi-gdiinfo). That last property is why dash phase must not be assumed to equal the count of visible pixels in all cases.

The Windows PNGs establish these device-pixel foreground/gap sequences on the
CI memory bitmap: dash 18/6, dot 3/3, dash-dot 9/6/3/6, and dash-dot-dot
9/3/3/3/3/3. A path carries phase across connected segments. A new drawing
call starts at the beginning of the style. Transparent gaps leave destination
pixels alone; opaque gaps use the selected background color. A logical pen
width that realizes wider than one device pixel is solid even if its style
field requests dashes or dots. Clipping must not reset phase.

Direct native `Ellipse`, `StrokePath`, and `FlattenPath` produce identical
styled pixels; this is not a separate ellipse painter. The flattened 28.4
path geometry matches ours exactly. The former major-axis-switch correction
compensated for incorrect diamond-edge membership in the shared rasterizer.
Using the [legacy GIQ membership rules](gdi-strokes.md#cosmetic-lines) produces
the right segment coverage and style steps directly. A path may exit and
re-enter the same diamond, consuming two steps, or merely graze an excluded
edge and consume none. No ellipse-specific or adjacent-segment phase patch is
needed. A fractional starting point offsets the initial style phase according
to the first pixel of the **unclipped** segment. Clipped segments still advance
the style by their complete GIQ span, including pixels clipped on the minor
axis. Visibility never participates in phase accounting.

[Run 35103238445](https://github.com/bitplane/pillow-wmf/actions/runs/35103238445)
checks 32 native crop pairs across all four styles, both background modes,
transposed axes, and reversed traversal. Both the small surface and the crop
of the larger native surface match our renderer exactly. The corresponding
WMF PNGs are Windows-generated; the unit crop checks express this measured
relationship, not an assumed clipping invariant.

Native path probe: [workflow run 35089932802](https://github.com/bitplane/pillow-wmf/actions/runs/35089932802).
