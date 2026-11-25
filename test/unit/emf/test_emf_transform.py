"""Native EMF playback transforms. Expected float32 values were observed on Windows."""

import struct

import pytest

from pillow_wmf.emf import Header, fixed
from pillow_wmf.emf.transform import PlaybackTransform, frame_fit, multiply, natural_size
from pillow_wmf.mapping import REFERENCE_DEVICE, ReferenceDevice
from pillow_wmf.playback import PlaybackError

FULL = (0, 0, 128, 128)


def bits(value):
    return struct.pack("<f", value).hex()


def header(frame, device=REFERENCE_DEVICE):
    return Header.create((0, 0, -1, -1), frame, device=device)


@pytest.mark.parametrize(
    ("frame", "rect", "device", "expected"),
    [
        # m11, m22, dx, dy as float32 bit patterns read back from playback DCs.
        ((0, 0, 1000, 1000), FULL, ReferenceDevice(), ("cdcc5840", "89885840", "00000000", "00000000")),
        ((0, 0, 1000, 500), FULL, ReferenceDevice(), ("cdcc5840", "8988d840", "00000000", "00000000")),
        ((0, 0, 3387, 3387), FULL, ReferenceDevice(), ("d704803f", "0eb97f3f", "00000000", "00000000")),
        ((100, -50, 1100, 950), FULL, ReferenceDevice(), ("cdcc5840", "89885840", "cdcc4cc1", "cdcccc40")),
        ((0, 0, 1000, 1000), (10, 20, 74, 52), ReferenceDevice(), ("cdccd83f", "8988583f", "00002041", "0000a041")),
        ((0, 0, 1000, 1000), (128, 128, 0, 0), ReferenceDevice(), ("cdcc58c0", "898858c0", "00000043", "00000043")),
        (
            (0, 0, 1000, 1000),
            FULL,
            ReferenceDevice((800, 600), (200, 150)),
            ("cdcc4c40", "cdcc4c40", "00000000", "00000000"),
        ),
    ],
)
def test_frame_fit_matches_native_float32_results(frame, rect, device, expected):
    m11, _, _, m22, dx, dy = frame_fit(header(frame, device), rect)
    assert (bits(m11), bits(m22), bits(dx), bits(dy)) == expected


@pytest.mark.parametrize("right", [3385, 3386])
def test_near_unit_fits_snap_to_an_exact_scale(right):
    # Both axes within 0.001 of 1:1 use exactly 1.0; 3384 and 3387 do not.
    assert frame_fit(header((0, 0, right, right)), FULL)[:4] == (1.0, 0.0, 0.0, 1.0)
    assert frame_fit(header((0, 0, right - 2, right - 2)), FULL)[0] != 1.0


def test_snapped_fits_keep_the_unsnapped_offset():
    # The origin uses the frame ratio before snapping, on both axes alike.
    m11, _, _, m22, dx, dy = frame_fit(header((37, 37, 37 + 3386, 37 + 3386)), FULL)
    assert (m11, m22) == (1.0, 1.0)
    assert bits(dx) == bits(dy) == bits(-1.3987005949020386)


def test_degenerate_and_reversed_frames():
    # An empty frame axis fits a target one pixel wider over one frame unit.
    assert bits(frame_fit(header((0, 0, 0, 1000)), FULL)[0]) == "705f5545"
    with pytest.raises(PlaybackError, match="reversed"):
        frame_fit(header((1000, 1000, 0, 0)), FULL)
    with pytest.raises(PlaybackError, match="device size"):
        natural_size(Header((0, 0, -1, -1), (0, 0, 10, 10), device=(0, 768)))


def test_natural_size_is_the_frame_in_header_device_pixels():
    assert natural_size(header((0, 0, 3388, 3383))) == (128, 128)
    assert natural_size(header((0, 0, 0, 0))) == (1, 1)


def matrix_bits(transform):
    return tuple(bits(value) for value in transform.matrix())


def played(records, frame=(0, 0, 1000, 1000), device=REFERENCE_DEVICE):
    transform = PlaybackTransform(header(frame, device), FULL)
    for record in records:
        transform.apply(record)
    return transform


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        # Physical extents come from the header millimetres, independent of a DPI.
        (2, ("0ad7a33f", "0bd7a3bf")),
        (3, ("6f12033e", "6f1203be")),
        (4, ("20105040", "d62150c0")),
        (6, ("7131673e", "8e3067be")),
    ],
)
def test_physical_modes_use_header_millimetres(mode, expected):
    m11, _, _, m22, _, _ = played([fixed.SetMapMode(mode)]).matrix()
    assert (bits(m11), bits(m22)) == expected


def test_page_records_compose_with_the_frame_fit():
    records = [
        fixed.SetMapMode(8),
        fixed.SetWindowOrgEx(-10, 5),
        fixed.SetWindowExtEx(300, 200),
        fixed.SetViewportOrgEx(2, 3),
        fixed.SetViewportExtEx(37, 37),
    ]
    assert matrix_bits(played(records)) == ("cae8d53e", "00000000", "00000000", "143c203f", "263f2f41", "42a7e040")


def test_rejected_records_leave_the_transform_unchanged():
    isotropic = [fixed.SetMapMode(7), fixed.SetWindowExtEx(200, 100), fixed.SetViewportExtEx(3, -6)]
    before = played(isotropic).matrix()
    # The adjusted viewport would collapse to zero: native playback ignores it.
    assert played([*isotropic, fixed.SetWindowExtEx(27476, -18)]).matrix() == before
    world = [fixed.SetWorldTransform(2.0, 0.0, 0.0, 2.0, 0.0, 0.0)]
    before = played(world).matrix()
    singular = fixed.SetWorldTransform(0.001, 0.0, 2.0, 0.0, -0.3, -0.3)
    assert played([*world, singular]).matrix() == before
    assert played([*world, fixed.ModifyWorldTransform(2.0, 0.0, 0.0, 2.0, 0.0, 0.0, 9)]).matrix() == before


def test_world_transform_modes():
    double = (2.0, 0.0, 0.0, 2.0, 1.0, 0.0)
    transform = played([fixed.SetWorldTransform(*double)], frame=(0, 0, 3388, 3383))
    assert transform.world == double
    transform.apply(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 3.0, 0.0, 2))
    assert transform.world == multiply((1.0, 0.0, 0.0, 1.0, 3.0, 0.0), double) == (2.0, 0.0, 0.0, 2.0, 7.0, 0.0)
    transform.apply(fixed.ModifyWorldTransform(1.0, 0.0, 0.0, 1.0, 3.0, 0.0, 3))
    assert transform.world == (2.0, 0.0, 0.0, 2.0, 10.0, 0.0)
    transform.apply(fixed.ModifyWorldTransform(5.0, 0.0, 0.0, 5.0, 0.0, 0.0, 1))
    assert transform.world == (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def test_save_and_restore_the_emulated_state():
    transform = played([fixed.SetMapMode(8), fixed.SetWindowExtEx(2, 2)])
    saved = transform.matrix()
    transform.save()
    transform.apply(fixed.SetWindowExtEx(4, 4))
    transform.apply(fixed.SetWorldTransform(3.0, 0.0, 0.0, 3.0, 0.0, 0.0))
    transform.restore(-2)  # Beyond the saved levels: unchanged.
    assert transform.matrix() != saved
    transform.restore(-1)
    assert transform.matrix() == saved
