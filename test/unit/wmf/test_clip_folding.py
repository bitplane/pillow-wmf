"""Folded clip rectangles keep the conjunctive constraint semantics."""

import random

import pytest

from pillow_wmf import Recorder, render
from pillow_wmf.clip import ClipRegion, RegionMask


class ConstraintClip:
    """Reference: test every applied rectangle at each pixel."""

    def __init__(self, mask=None, constraints=()):
        self.mask = mask
        self.constraints = constraints

    def contains(self, x, y):
        return (self.mask is None or self.mask.contains(x, y)) and all(
            (left <= x < right and top <= y < bottom) == include
            for include, (left, top, right, bottom) in self.constraints
        )

    def intersect(self, rectangle):
        return ConstraintClip(self.mask, (*self.constraints, (True, rectangle)))

    def exclude(self, rectangle):
        return ConstraintClip(self.mask, (*self.constraints, (False, rectangle)))

    def offset(self, dx, dy):
        return ConstraintClip(
            self.mask.offset(dx, dy) if self.mask is not None else None,
            tuple((i, (x0 + dx, y0 + dy, x1 + dx, y1 + dy)) for i, (x0, y0, x1, y1) in self.constraints),
        )


def _rectangle(generator, ordered=True):
    x0, x1 = sorted(generator.randint(-12, 24) for _ in range(2))
    y0, y1 = sorted(generator.randint(-12, 24) for _ in range(2))
    if not ordered and generator.random() < 0.5:
        x0, x1 = x1, x0
    return x0, y0, x1, y1


@pytest.mark.parametrize("seed", range(60))
def test_folded_clip_matches_per_pixel_constraints(seed):
    generator = random.Random(seed)
    mask = None
    if generator.random() < 0.4:
        mask = RegionMask.from_rectangles(_rectangle(generator) for _ in range(generator.randint(0, 4)))
    folded, reference = ClipRegion(mask), ConstraintClip(mask)
    history = [(folded, reference)]
    for _ in range(generator.randint(1, 14)):
        choice = generator.random()
        if choice < 0.45:
            rectangle = _rectangle(generator, ordered=False)
            folded, reference = folded.exclude(rectangle), reference.exclude(rectangle)
        elif choice < 0.8:
            rectangle = _rectangle(generator, ordered=False)
            folded, reference = folded.intersect(rectangle), reference.intersect(rectangle)
        elif choice < 0.9:
            dx, dy = generator.randint(-8, 8), generator.randint(-8, 8)
            folded, reference = folded.offset(dx, dy), reference.offset(dx, dy)
        else:
            # Restoring a saved DC returns an earlier immutable clip.
            folded, reference = generator.choice(history)
        history.append((folded, reference))
    bounds = (-4, -2, 20, 18)
    bounded = folded.within(bounds)
    for y in range(-16, 30):
        for x in range(-16, 30):
            expected = reference.contains(x, y)
            assert folded.contains(x, y) == expected, (x, y)
            inside = bounds[0] <= x < bounds[2] and bounds[1] <= y < bounds[3]
            assert bounded.contains(x, y) == (inside and expected), (x, y)


def test_applied_rectangles_do_not_accumulate():
    # Pixel tests used to rescan every rectangle applied since selection.
    clip = ClipRegion()
    for index in range(2000):
        clip = clip.exclude((1000 + index, 1000, 1001 + index, 1001))
    assert clip.excluded.bands == ((1000, 1001, (1000, 3000)),)
    clip = clip.intersect((0, 0, 4000, 4000))
    assert clip.mask.bands == ((0, 1000, (0, 4000)), (1000, 1001, (0, 1000, 3000, 4000)), (1001, 4000, (0, 4000)))
    assert not clip.excluded.bands
    for index in range(2000):
        clip = clip.exclude((index, 0, index + 1, 1))
    assert len(clip.mask.bands) == 4


def test_exclusions_survive_offset_and_save_restore():
    source = Recorder(trace_calls=False)
    source.save_dc()
    for index in range(4):
        source.exclude_clip_rect(-10 + index, -10, -9 + index, -9)
    source.offset_clip_region(12, 12)
    source.pat_blt(0, 0, 8, 8, 0x00FF0062)  # WHITENESS onto a black canvas
    source.restore_dc(-1)
    source.pat_blt(0, 4, 8, 8, 0x00FF0062)
    image = render(source.to_bytes(), (8, 8), background=(0, 0, 0))
    assert [image.getpixel((x, 2)) for x in range(8)] == [(255, 255, 255)] * 2 + [(0, 0, 0)] * 4 + [(255, 255, 255)] * 2
    assert image.getpixel((3, 5)) == (255, 255, 255)


@pytest.mark.parametrize("seed", range(80))
def test_single_rectangle_edits_match_band_algebra(seed):
    generator = random.Random(seed)
    mask = RegionMask.from_rectangles(_rectangle(generator) for _ in range(generator.randint(0, 8)))
    for _ in range(12):
        rectangle = _rectangle(generator)
        if rectangle[0] == rectangle[2] or rectangle[1] == rectangle[3]:
            continue
        other = RegionMask.from_rectangles((rectangle,))
        # Bands are canonical, so equal regions have equal bands.
        assert mask.with_rectangle(rectangle) == RegionMask.from_rectangles((*mask.rectangles(), rectangle))
        assert mask.without_rectangle(rectangle) == mask.difference(other)
        assert mask.clipped(rectangle) == mask.intersection(other)
        mask = generator.choice(
            (mask.with_rectangle(rectangle), mask.without_rectangle(rectangle), mask.clipped(rectangle))
        )
