"""Playback bookkeeping shared by metafile players, independent of record formats."""

from dataclasses import dataclass

from .gdi import UnsupportedOperation


class PlaybackError(ValueError):
    """A stream's handle references or backend results are invalid."""


@dataclass(frozen=True)
class Omission:
    """A record the backend did not draw; ``function`` is its format's record type."""

    record_index: int
    function: int
    reason: str


class Omissions:
    """Collect unsupported records, or raise on the first one when strict."""

    def __init__(self, *, strict: bool):
        self.strict = strict
        self._omissions: list[Omission] = []

    def omit(self, index: int, function: int, reason: str) -> None:
        if self.strict:
            raise UnsupportedOperation(f"Record {index}: {reason}")
        self._omissions.append(Omission(index, function, reason))

    def result(self) -> tuple[Omission, ...]:
        return tuple(self._omissions)


class SaveLevels:
    """A file's save levels beside the backend's own identifiers.

    File levels count every save record, including those the backend omitted.
    Backend levels do not, and can also retain frames left by a restore the
    backend rejected. Restores are addressed by file level and translated.
    """

    MISSING = object()

    def __init__(self):
        self._file: list[int | None] = []
        self._backend: list[int] = []

    @property
    def depth(self) -> int:
        return max(len(self._file), len(self._backend))

    def save(self) -> None:
        """Open a file level; it stays unsupported until ``saved`` records a result."""
        self._file.append(None)

    def saved(self, identifier) -> bool:
        """Record the backend's identifier for the newest level, if it is valid."""
        if (
            not isinstance(identifier, int)
            or isinstance(identifier, bool)
            or identifier <= 0
            or identifier in self._backend
        ):
            return False
        self._file[-1] = identifier
        self._backend.append(identifier)
        return True

    def restore(self, level: int):
        """Pop file levels down to ``level``: absolute if positive, else relative.

        Returns ``MISSING`` for a level the file never reached, leaving the
        levels untouched; otherwise the backend identifier, or ``None`` when
        that save was unsupported.
        """
        target = level if level > 0 else len(self._file) + level + 1
        if level == 0 or target < 1 or target > len(self._file):
            return self.MISSING
        identifier = self._file[target - 1]
        del self._file[target - 1 :]
        return identifier

    def backend_level(self, identifier: int, level: int) -> int:
        """The backend's reference for a restore the file addressed as ``level``."""
        return identifier if level > 0 else self._backend.index(identifier) - len(self._backend)

    def restored(self, identifier: int) -> None:
        """Drop the backend levels a successful restore released."""
        del self._backend[self._backend.index(identifier) :]
