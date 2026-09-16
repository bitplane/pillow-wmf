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
path geometry matches ours exactly. Counting visible pixels alone missed
style behavior at vertices that touch the edge of a pixel diamond
(Manhattan distance 8 in 28.4 coordinates) while the path switches major
axis. When both adjacent segments lie inside the touched diamond, GDI
advances the style once more. When both lie outside, it advances once less
and does not paint the touched pixel. A crossing from one side to the other
needs no correction. Other diamond touches away from an axis switch do
not alter style phase. A fractional starting point offsets the initial
style phase according to the first visible pixel, without a shape-specific
correction.

Native path probe: [workflow run 35089932802](https://github.com/bitplane/pillow-wmf/actions/runs/35089932802).
