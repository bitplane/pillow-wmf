"""Format-neutral playback bookkeeping: omissions and save-level translation."""

import pytest

import pillow_wmf
from pillow_wmf import Omission, PlaybackError, UnsupportedOperation
from pillow_wmf.playback import Omissions, SaveLevels
from pillow_wmf.wmf import player


def test_player_and_package_share_the_neutral_types():
    assert player.PlaybackError is PlaybackError is pillow_wmf.playback.PlaybackError
    assert player.Omission is Omission


def test_omissions_collect_or_raise():
    lenient = Omissions(strict=False)
    lenient.omit(3, 0x0626, "Unknown record")
    assert lenient.result() == (Omission(3, 0x0626, "Unknown record"),)
    with pytest.raises(UnsupportedOperation, match="Record 3: Unknown record"):
        Omissions(strict=True).omit(3, 0x0626, "Unknown record")


def test_restore_addresses_file_levels_absolutely_or_relatively():
    levels = SaveLevels()
    for identifier in (11, 12, 13):
        levels.save()
        assert levels.saved(identifier)
    assert levels.depth == 3
    assert levels.restore(-1) == 13
    assert levels.backend_level(13, -1) == -1
    levels.restored(13)
    assert levels.restore(1) == 11
    assert levels.backend_level(11, 1) == 11
    levels.restored(11)
    assert levels.depth == 0


@pytest.mark.parametrize("level", [0, 3, -3])
def test_unreached_level_leaves_the_stack_untouched(level):
    levels = SaveLevels()
    for identifier in (1, 2):
        levels.save()
        levels.saved(identifier)
    assert levels.restore(level) is SaveLevels.MISSING
    assert levels.restore(-1) == 2


def test_omitted_save_occupies_a_file_level_only():
    levels = SaveLevels()
    levels.save()
    levels.saved(7)
    levels.save()  # The backend rejected this save.
    levels.save()
    levels.saved(8)
    # Relative file level -1 is the backend's newest frame; -2 was never saved there.
    assert levels.restore(-2) is None
    assert levels.restore(-1) == 7
    # The frame left behind by the unrestorable levels still counts against the backend.
    assert levels.backend_level(7, -1) == -2
    levels.restored(7)
    assert levels.depth == 0


@pytest.mark.parametrize("identifier", [0, -1, True, None, "1", 5])
def test_invalid_or_repeated_backend_identifiers_are_refused(identifier):
    levels = SaveLevels()
    levels.save()
    assert levels.saved(5)
    levels.save()
    assert not levels.saved(identifier)
    assert levels.restore(-1) is None
