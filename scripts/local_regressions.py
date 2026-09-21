"""Native integration boundaries kept in the default compatibility suite.

Arithmetic and decoding matrices belong in unit tests. Broader combinations
are exported to the pillow-wmf-synthetic release corpus. These names select
generator outputs, never exclude files from compatibility test discovery.
"""

# Driver rounding, mode transitions, extent ordering and pen algorithm limits.
MAPPING = """
dib-extended-png-stretch
dib-extended-linked-brush
text-em-height
text-layout-and-clip
text-cell-height
escape-rgb-device
text-glyph-explicit
text-pdy-overlap
text-pdy-quarter-decorated
text-pdy-quarter-opaque
text-pdy-reverse-angle-background
text-pdy-obtuse-background
text-rtl-opaque
text-rtl-pdy-center
text-rtl-fractional
text-scaled-spacing
text-codepages
text-symbols
cp932-natural
cp932-split
cp932-pdy
text-blank-controls
mapping-translation-precision-0
mapping-translation-precision-1
coords-mode-switch
coords-mode-twips
coords-fixed-ignores-extents-6
coords-isotropic-order-viewport-first
coords-isotropic-order-window-first
coords-half-ties-translated
coords-scale-extents
pen-table-rounding-boundaries
pen-thin-size-limit-511-0
pen-thin-size-limit-511-1
pen-thin-size-limit-512-0
pen-thin-size-limit-512-1
pen-thin-size-limit-513-0
pen-thin-size-limit-513-1
stroke-octants-1-identity
stroke-octants-6-identity
stroke-octants-7-fractional
"""

# Arc construction, support ties, collapsed figures and independent fill/stroke.
CURVES = """
ellipse-fractional-rims-x-wide
ellipse-fractional-rims-y-wide
ellipse-fractional-rims-y-wider
ellipse-fractional-rims-uniform
ellipse-anisotropic-unfilled-wide
ellipse-anisotropic-unfilled-narrow
pen-subpixel-minor-axis-paths
pen-collapsed-shallow-polygons
arc-radials-and-position
arc-edge-far-coincident-angles-width-1
arc-edge-short-controls-width-1
arc-edge-short-controls-width-7
arc-shallow-width-3
arc-shallow-width-7
chord-sweeps-solid
chord-edge-same-ray
insideframe-ellipse-collapse
insideframe-ellipse-fractional
insideframe-unbounded
pen-support-tie-width-7-direction--1
pen-support-tie-width-7-direction-1
pen-support-tie-width-8-direction--1
pen-support-tie-width-8-direction-1
pie-wide-collapsed
pie-wide-full
pie-xor-fill-stroke
roundrect-corners-xor-wide
"""

# Winding, closure, dash phase, clipping and object/state lifetime.
STATE = """
polygon-short-contour
polypolygon-count-boundaries-1
polypolygon-count-boundaries-2
stroke-reversal-seams-fractional
stroke-reversal-seams-reflected
stroke-reversal-seams-small-table
stroke-reversal-seams-cubic
brush-background-state
drawing-line-endpoints
pen-style-clipped-phase
pen-styles-offscreen-connected
poly-polygon-nested-winding-opposite
poly-polygon-nested-winding-same
polygon-double-wound-alternate
polygon-double-wound-winding
polyline-explicit-closure
polyline-repeated-vertices
state-clip-offset-from-outside
region-clip-slot-zero-object
region-clip-restore
region-frame-native-fraction-hole-edge
region-frame-native-fraction-islands-large
region-frame-native-small-mirror
state-review-delete-brush-saved1
state-review-delete-palette-saved1
state-review-delete-pen-saved1
state-review-null-frame_region-core-dib
"""

# Layout flags and palette mutations lack adequate real-world corpus coverage.
LAYOUT_PALETTE = """
layout-bitmap-stretch_dib-9
layout-clip-1
layout-mapping-restore
layout-primitives-0
layout-primitives-1
layout-primitives-8
layout-primitives-9
palette-brush-aligned-storage
palette-colorref-mutation
palette-entry-flags-0
palette-entry-flags-1
palette-save-selection-not-contents
palette-state-1-brush
palette-state-1-device
palette-state-1-stretch_dib
"""

# Native selection failures, device palettes, self-copy and brush realization.
BITMAP16 = """
bitmap16-bit_blt-embedded-depth-rop-atlas
bitmap16-stretch_blt-embedded-depth-rop-atlas
bitmap16-native-pattern-device-palette
bitmap16-native-pattern-unrealizable-4
bitmap16-native-pattern-1-stride4
bitmap16-native-pattern-32-stride4
bitmap16-selfcopy-identity-bit_blt-mode3-overlap
bitmap16-selfcopy-rtl-fractional-stretch_blt-mode4-clip
bitmap16-selfcopy-negative-stretch_blt-mode3-signed
"""

# Decoded pixels alone cannot guard transfer dispatch, clipping or scan order.
DIB = """
dib-rle4-clip-phase-dib_bit_blt
dib-rle4-clip-phase-dib_stretch_blt
dib-rle4-clip-phase-set_dib_to_device
dib-rle4-clip-phase-stretch_dib
dib-rle4-transfer-boundaries-dib_bit_blt
dib-rle4-transfer-boundaries-dib_stretch_blt
dib-rle4-transfer-boundaries-set_dib_to_device
dib-rle4-transfer-boundaries-stretch_dib
dib-format-channel-ramp-1
dib-format-channel-ramp-2
dib-format-channel-ramp-3
dib-device-bands-0
dib-device-bands-1
dib-blt-copy-code-bits
dib-stretch-ratios-dib-0-1
dib-stretch-ratios-dib-0-2
dib-stretch-ratios-dib-0-3
dib-stretch-signs-blt-1-96
dib-brush-state-restore
dib-brush-live-colors-3-2
"""

# Classification boundaries and scan history need whole-image native oracles.
HALFTONE = """
halftone-classify-129-noise
halftone-classify-49-palette19
halftone-classify-49-palette20
halftone-classify-49-palette21
halftone-clipped-grid-boundaries
halftone-cross-axis-basis
halftone-enlarge-runs-3
halftone-enlarge-runs-5
halftone-kernel-impulse-x
halftone-kernel-impulse-y
halftone-large-clip-fast-leading
halftone-large-clip-fast-trailing-reflect-11
halftone-large-clip-general-leading
"""

# Fill connectivity and Boolean composition at the drawing API boundary.
FILL = """
flood-topology-0-diagonal
flood-topology-1-clip-wall
patblt-tables-0-0-2
rop2-fill-and-outline
"""

LOCAL_CASES = frozenset((MAPPING + CURVES + STATE + LAYOUT_PALETTE + BITMAP16 + DIB + HALFTONE + FILL).split())
