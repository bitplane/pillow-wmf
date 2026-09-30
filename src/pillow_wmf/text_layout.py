"""GDI text placement, spacing, background cells and decorations."""

from dataclasses import dataclass
from fractions import Fraction
from math import ceil

from .constants import TA_RTLREADING
from .dbcs import collapse_advances
from .font import Glyph
from .gdi import InvalidOperation, UnsupportedOperation
from .mapping import fixed, rounded
from .numeric import float32
from .text_encoding import decode_single_byte
from .text_math import text_rotation


@dataclass(frozen=True)
class TextLayout:
    glyphs: tuple[tuple[int, int, Glyph], ...] = ()
    background: tuple[tuple[int | Fraction, int | Fraction], ...] | None = None
    position: tuple[int | Fraction | float, int | Fraction | float] | None = None
    decorations: tuple[tuple[tuple[int, int], ...], ...] = ()


def _horizontal_script_offsets(characters, glyphs, offsets):
    """Keep terminal Hangul glyphs at their natural width when squeezing.

    For precomposed Hangul, ScriptShape marks the last glyph of the run with
    SCRIPT_JUSTIFY_NONE; preceding glyphs use SCRIPT_JUSTIFY_CHARACTER.
    ScriptApplyLogicalWidth leaves a non-adjustable glyph's natural width
    intact and applies only positive residual width at the run end. This
    affects subsequent ink placement, not the caller's logical advance sum.
    PDY and direct glyph-index output bypass this horizontal shaping step.
    """
    hangul = [0xAC00 <= ord(c) <= 0xD7A3 for c in characters]
    placed = []
    residual = 0
    for i, glyph in enumerate(glyphs):
        placed.append(rounded(offsets[i] + residual))
        if hangul[i] and (i + 1 == len(hangul) or not hangul[i + 1]):
            requested = offsets[i + 1] - offsets[i]
            residual += max(0, glyph.advance - requested)
    placed.append(rounded(offsets[-1] + residual))
    return placed


def layout_text(
    font,
    text,
    x,
    y,
    alignment,
    advances,
    *,
    opaque,
    max_pixels,
    scale=1,
    extra=0,
    justification=(0, 0),
    characters=None,
    escapement=0,
    glyph_indices=None,
    vertical_advances=(),
    vertical_scale=1,
    mirrored_layout=False,
    precise_origin=None,
    byte_lengths=(),
    byte_indexed_advances=True,
):
    """Place independently realized glyphs; explicit advances replace metrics."""
    if characters is None and glyph_indices is None:
        characters = decode_single_byte(text, 1252)
    if glyph_indices is None:
        byte_lengths = byte_lengths or (1,) * len(characters)
        if len(byte_lengths) != len(characters) or sum(byte_lengths) != len(text):
            raise InvalidOperation("Decoded character spans must cover the text bytes")
        advances = collapse_advances(advances, byte_lengths, byte_indexed=byte_indexed_advances)
        vertical_advances = collapse_advances(vertical_advances, byte_lengths, byte_indexed=byte_indexed_advances)
    sine, cosine = text_rotation(escapement)

    def project(px, py, *, snap=True):
        if not escapement % 3600:
            return px, py
        dx, dy = float32(px - x), float32(py - y)
        dx, dy = (
            float32(float32(dx * cosine) + float32(dy * sine)),
            float32(float32(dy * cosine) - float32(dx * sine)),
        )
        return (x + rounded(dx), y + rounded(dy)) if snap else (x + dx, y + dy)

    horizontal, vertical = alignment & 6, alignment & 24
    if alignment & ~(31 | TA_RTLREADING) or horizontal not in (0, 2, 6) or vertical not in (0, 8, 24):
        raise UnsupportedOperation("Text alignment")
    count = len(characters) if glyph_indices is None else len(glyph_indices)
    if advances and len(advances) != count:
        raise InvalidOperation("Text advance count must match the byte count")
    if vertical_advances and len(vertical_advances) != count:
        raise InvalidOperation("Vertical advance count must match the glyph count")
    glyphs = (
        font.shape(characters, max_pixels, raw=bool(vertical_advances))
        if glyph_indices is None
        else tuple(font.glyph_index(index, max_pixels) for index in glyph_indices)
    )
    offsets = [0]
    vertical_offsets = [0]
    mapped_offsets = [0]
    total = 0
    break_count, break_extra = justification
    # Spacing accumulates before pixel placement. Preserve fractional remainders
    # instead of distributing rounded per-character additions.
    break_step = int(Fraction(break_extra * scale * 65536, break_count)) if break_count > 0 else 0
    for index, glyph in enumerate(glyphs):
        vertical_offsets.append(
            vertical_offsets[-1] - (vertical_advances[index] * vertical_scale if vertical_advances else 0)
        )
        if advances:
            total += advances[index] + extra
            mapped_offsets.append(total * scale)
        else:
            total += glyph.advance * 65536 + int(extra * scale * 65536)
            if glyph_indices is None and ord(characters[index]) == font.break_character:
                total += break_step
            # The accumulated device advance uses nearest-even ties before
            # conversion to logical coordinates, whose rounding is distinct.
            device_offset = round(Fraction(total, 65536))
            mapped_offsets.append(rounded(device_offset / scale) * scale)
        offsets.append(rounded(mapped_offsets[-1]))
    if advances and not vertical_advances and glyph_indices is None:
        offsets = _horizontal_script_offsets(characters, glyphs, mapped_offsets)
    run_width = total * scale if advances else rounded((total // 65536) / scale) * scale
    if escapement % 900 and not advances:
        run_width = Fraction(total, 65536)
    width = rounded(run_width)
    # Monochrome GDI places cached glyphs at integer origins. Centering an
    # odd-width run chooses the lower coordinate, not a fractional mask phase.
    center_offset = (width + (not mirrored_layout)) // 2
    origin_x = x - (width if horizontal == 2 else center_offset if horizontal == 6 else 0)
    if horizontal == 2 and precise_origin is not None:
        # Subtract the advance before rounding the aligned reference point.
        origin_x = rounded(precise_origin[0] - run_width)
    baseline = y + (font.ascent if vertical == 0 else -font.descent if vertical == 8 else 0)
    run_height = vertical_offsets[-1]
    if mirrored_layout:
        # Mirroring the run's reference edge translates both components of
        # paired spacing, while glyph order and individual offsets stay LTR.
        baseline -= rounded(run_height) if horizontal == 2 else rounded(run_height) // 2 if horizontal == 6 else 0
    position = (
        (
            x + (run_width if horizontal == 0 else -run_width),
            y + (-run_height if mirrored_layout and horizontal == 2 else run_height),
        )
        if alignment & 1 and horizontal != 6
        else None
    )
    if position is not None:
        position = project(*position, snap=False)
    positioned = []
    for glyph, offset, dy in zip(glyphs, offsets[:-1], vertical_offsets[:-1], strict=True):
        gx, gy = project(origin_x + offset, baseline + rounded(dy))
        positioned.append((gx + glyph.bearing[0], gy + glyph.bearing[1], glyph))
    background_width = ceil(total * scale) if advances else ceil((Fraction(total, 65536) // scale) * scale)
    # An opaque run must also cover protruding ink, even with negative spacing
    # or a final explicit advance smaller than the glyph's black box.
    right = max(
        [origin_x + background_width]
        + [
            ceil(origin_x + offset + glyph.bearing[0] + glyph.size[0])
            for glyph, offset in zip(glyphs, mapped_offsets[:-1], strict=True)
        ]
    )
    left = origin_x
    top, bottom = baseline - font.ascent, baseline + font.descent
    if vertical_advances:
        # PDY uses the positioned glyph bounds rather than one horizontal
        # cell strip. Horizontal bounds include the run origin and final
        # advance, plus protruding ink; GDI includes the rightmost column.
        left = min([left] + [origin_x + dx + glyph.bearing[0] for glyph, dx in zip(glyphs, offsets[:-1], strict=True)])
        right += 1
        top += min(map(rounded, vertical_offsets[:-1]), default=0)
        bottom += max(map(rounded, vertical_offsets[:-1]), default=0)
    background = (
        tuple(
            project(px, py)
            for px, py in (
                (left, top),
                (right, top),
                (right, bottom),
                (left, bottom),
            )
        )
        if opaque
        else None
    )
    if opaque and vertical_advances and escapement % 3600:
        background = paired_background(
            glyphs,
            mapped_offsets[:-1],
            vertical_offsets[:-1],
            origin_x,
            baseline,
            font.background_cell,
            x,
            y,
            escapement,
        )
    decoration_spans = (
        tuple(
            (origin_x + dx + glyph.ink_span[0], baseline + rounded(dy), glyph.ink_span[1] - glyph.ink_span[0])
            for glyph, dx, dy in zip(glyphs, offsets[:-1], vertical_offsets[:-1], strict=True)
        )
        if vertical_advances
        else ((origin_x, baseline, width),)
    )
    decorations = tuple(
        tuple(
            project(px, py)
            for px, py in (
                (span_x, span_y - offset),
                (span_x + span_width, span_y - offset),
                (span_x + span_width, span_y - offset + thickness),
                (span_x, span_y - offset + thickness),
            )
        )
        for offset, thickness in font.decorations
        for span_x, span_y, span_width in decoration_spans
    )
    return TextLayout(tuple(positioned), background, position, decorations)


def paired_background(glyphs, offsets, vertical_offsets, origin_x, baseline, cell, x, y, escapement):
    """Bound positioned glyph cells in font space, then realize their corners."""
    left = min(
        origin_x + dx + glyph.background_ink_span[0] - Fraction(1, 4) for glyph, dx in zip(glyphs, offsets, strict=True)
    )
    right = max(
        origin_x + dx + glyph.background_ink_span[1] + Fraction(1, 4) for glyph, dx in zip(glyphs, offsets, strict=True)
    )
    top = baseline + min(vertical_offsets) - cell[0]
    bottom = baseline + max(vertical_offsets) + cell[1]
    sine, cosine = text_rotation(escapement)

    def contribution(distance, coefficient):
        return fixed(float32(float32(distance) * coefficient))

    corners = tuple(
        (
            Fraction(x * 16 + contribution(px - x, cosine) + contribution(py - y, sine), 16),
            Fraction(y * 16 + contribution(py - y, cosine) - contribution(px - x, sine), 16),
        )
        for px, py in ((left, top), (right, top), (right, bottom), (left, bottom))
    )
    if escapement % 900 == 0:
        left, top = (min(p[i] for p in corners) // 1 for i in range(2))
        right, bottom = (ceil(max(p[i] for p in corners)) for i in range(2))
        if escapement % 1800:
            bottom += 1
        else:
            right += 1
        return ((left, top), (right, top), (right, bottom), (left, bottom))
    return corners
