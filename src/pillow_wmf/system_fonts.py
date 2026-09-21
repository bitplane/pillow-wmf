"""Opt-in host font discovery, separate from controlled-font rendering."""

import os
import subprocess
import sys
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont, TTLibError

from .gdi import UnsupportedOperation
from .text import TEXT_CHARSETS, FontCollection, FontFace, FontRun, decode_codepage
from .wmf.objects import Font


def font_paths():
    """Use Fontconfig's configured inventory, or conventional system directories."""
    try:
        result = subprocess.run(
            ["fc-list", "--format=%{file}\\n"], capture_output=True, text=True, check=True, timeout=10
        )
        paths = {Path(line) for line in result.stdout.splitlines() if line}
        if paths:
            return sorted(paths)
    except (OSError, subprocess.SubprocessError):
        pass
    home = Path.home()
    if sys.platform == "win32":
        roots = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"]
        if local := os.environ.get("LOCALAPPDATA"):
            roots.append(Path(local) / "Microsoft/Windows/Fonts")
    elif sys.platform == "darwin":
        roots = [Path("/System/Library/Fonts"), Path("/Library/Fonts"), home / "Library/Fonts"]
    else:
        roots = [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts"]
        roots.append(Path(os.environ.get("XDG_DATA_HOME", home / ".local/share")) / "fonts")
    return sorted({p for root in roots for p in root.rglob("*") if p.suffix.lower() in {".ttf", ".ttc", ".otf"}})


@dataclass(frozen=True)
class FontSubstitution:
    requested: str
    selected: str
    reason: str


@dataclass(frozen=True)
class InstalledFace:
    path: Path
    index: int
    family: str
    weight: int
    italic: bool
    symbol: bool
    category: str
    coverage: frozenset[int]


def catalogue(paths):
    for path in sorted(set(map(Path, paths))):
        try:
            count = 1
            if path.suffix.lower() == ".ttc":
                with TTCollection(path, lazy=True) as collection:
                    count = len(collection.fonts)
            for index in range(count):
                with TTFont(path, fontNumber=index, lazy=True) as font:
                    if "glyf" not in font or "fvar" in font:
                        continue
                    family = font["name"].getBestFamilyName()
                    if not family:
                        continue
                    os2 = font["OS/2"]
                    category = "sans"
                    if font["post"].isFixedPitch:
                        category = "mono"
                    elif 1 <= os2.sFamilyClass >> 8 <= 7:
                        category = "serif"
                    symbol = any(t.platformID == 3 and t.platEncID == 0 for t in font["cmap"].tables)
                    yield InstalledFace(
                        path,
                        index,
                        family,
                        os2.usWeightClass,
                        bool(os2.fsSelection & 1),
                        symbol,
                        category,
                        frozenset((font.getBestCmap() or {}).keys()),
                    )
        except (OSError, TTLibError, KeyError, ValueError):
            # A stale inventory entry or unsupported installed face must not
            # prevent use of other fonts. No WMF-supplied paths are searched.
            continue


FAMILIES = {
    "arial": ("Liberation Sans", "Arial", "DejaVu Sans"),
    "helvetica": ("Liberation Sans", "Arial", "DejaVu Sans"),
    "times new roman": ("Liberation Serif", "Times New Roman", "DejaVu Serif"),
    "times": ("Liberation Serif", "Times New Roman", "DejaVu Serif"),
    "courier new": ("Liberation Mono", "Courier New", "DejaVu Sans Mono"),
    "courier": ("Liberation Mono", "Courier New", "DejaVu Sans Mono"),
}
GENERICS = {
    "sans": ("Liberation Sans", "Arial", "DejaVu Sans"),
    "serif": ("Liberation Serif", "Times New Roman", "DejaVu Serif"),
    "mono": ("Liberation Mono", "Courier New", "DejaVu Sans Mono"),
}


class SystemFontCollection(FontCollection):
    """Best-effort installed fonts; construct one collection per rendering job.

    Discovery is lazy. Pass paths to use a bounded application font inventory
    instead of the host. Unsupported outline formats are ignored. Missing glyphs
    use .notdef after installed Unicode fallbacks have been exhausted.
    """

    def __init__(self, *, paths=None, ansi_codepage=1252, oem_codepage=437, mac_codepage=None, default_font=None):
        super().__init__(
            ansi_codepage=ansi_codepage,
            oem_codepage=oem_codepage,
            mac_codepage=mac_codepage,
            synthesize_styles=True,
            wingdings_fallback=True,
            symbol_fallback=True,
            missing_glyph="notdef",
        )
        self.default_font = default_font or Font(height=-16, face_name=b"Arial")
        self._paths = None if paths is None else tuple(paths)
        self._loaded = {}
        self.substitutions: list[FontSubstitution] = []

    @cached_property
    def inventory(self):
        return tuple(catalogue(font_paths() if self._paths is None else self._paths))

    def _name(self, request):
        return decode_codepage(request.face_name.split(b"\0", 1)[0], self.ansi_codepage).text

    def _ranked(self, request):
        family = self._name(request).casefold()
        category = "sans"
        if request.pitch_and_family & 3 == 1 or request.pitch_and_family & 0xF0 == 0x30:
            category = "mono"
        elif request.pitch_and_family & 0xF0 == 0x10:
            category = "serif"
        preferred = tuple(n.casefold() for n in FAMILIES.get(family, GENERICS[category]))

        def rank(face):
            name = face.family.casefold()
            preference = -1 if name == family else preferred.index(name) if name in preferred else len(preferred)
            return (
                preference,
                face.category != category,
                face.italic != bool(request.italic),
                abs(face.weight - (request.weight or 400)),
                name,
                str(face.path),
                face.index,
            )

        return sorted(self.inventory, key=rank)

    def _load(self, entry):
        if entry not in self._loaded:
            try:
                self._loaded[entry] = FontFace.from_path(entry.path, index=entry.index)
            except (OSError, TTLibError, KeyError, ValueError, UnsupportedOperation):
                self._loaded[entry] = None
        return self._loaded[entry]

    def _report(self, request, face, reason):
        record = FontSubstitution(self._name(request), face.family, reason)
        if record not in self.substitutions:
            self.substitutions.append(record)

    def resolve(self, request):
        request = request or self.default_font
        effective = self._selection_request(request)
        face = self._resolve(effective)
        if effective != request:
            self._report_charset(request, effective, face)
        return face

    def _report_charset(self, request, effective, face):
        encoding = {2: "Symbol", 255: "OEM"}.get(effective.charset, "ANSI")
        self._report(request, face, f"charset {request.charset} fallback to {encoding}")

    def _selection_request(self, request):
        """Model unsupported-charset font selection before choosing bytes.

        Native GDI discards the requested ordinary family, selecting the default
        from pitch/family hints. An explicitly named symbol face keeps its symbol
        encoding. MAC_CHARSET follows this path unless the caller opts into a
        legacy Macintosh decoding environment. Charset 254 is a UTF-8 extension,
        not an unknown charset that can safely be treated as ANSI.
        """
        charset = self._charset(request)
        if charset == 254:
            raise UnsupportedOperation("Unsupported text charset: 254 (Windows UTF-8 extension)")
        name = self._name(request).casefold()
        unknown = charset not in TEXT_CHARSETS and charset not in (1, 2, 255)
        if charset == 77 and self.mac_codepage is not None:
            unknown = False
        if unknown:
            symbol = name in {"wingdings", "symbol", "webdings"} or any(
                entry.symbol and entry.family.casefold() == name for entry in self.inventory
            )
            return replace(request, charset=2) if symbol else replace(request, face_name=b"", charset=1)
        if charset == 255 and name in {"wingdings", "webdings"}:
            return replace(request, face_name=b"")
        return request

    def _resolve(self, request):
        name = self._name(request).casefold()
        charset = self._charset(request)
        for entry in self._ranked(request):
            # Symbol encodings have font-specific byte meanings, not ordinary
            # Unicode coverage. Only an exact family or a bundled fallback works.
            if entry.symbol and charset not in (1, 2):
                continue
            if (entry.symbol or charset == 2 or name in {"wingdings", "symbol", "webdings"}) and (
                entry.family.casefold() != name
            ):
                continue
            if face := self._load(entry):
                if name and face.family.casefold() != name:
                    self._report(request, face, "family")
                elif (face.weight, face.italic) != (request.weight or 400, bool(request.italic)):
                    self._report(request, face, "style")
                return face
        if name in {"wingdings", "symbol"}:
            face = super().resolve(request)
            self._report(request, face, "bundled symbol font" if name == "symbol" else "symbol mapping")
            return face
        if charset == 2:
            # Native missing-family selection keeps the symbol encoding and
            # uses LOGFONT's pitch/family hints. This is a reported substitute, not an alias
            # asserting that the unavailable font used the same glyphs.
            hint = request.pitch_and_family & 0xF0
            fixed_pitch = request.pitch_and_family & 3 == 1
            if fixed_pitch and hint in (0, 0x10):
                family = b"Webdings"
            else:
                family = b"Symbol" if hint == 0x10 else b"Wingdings"
            if name == family.decode().casefold():
                raise UnsupportedOperation(f"Native symbol fallback {family.decode()!r} is not installed")
            face = self.resolve(replace(request, face_name=family.ljust(32, b"\0")))
            self._report(request, face, "symbol charset fallback")
            return face
        raise UnsupportedOperation(f"No usable installed font for {self._name(request)!r}")

    def decode_run(self, request, face, data):
        effective = self._selection_request(request)
        if effective != request:
            self._report_charset(request, effective, face)
        request = effective
        if face.symbol or face is self._wingdings_face:
            return super().decode_run(request, face, data)
        codepage, _ = self._encoding(request)
        # Decode the requested encoding before testing actual glyph coverage;
        # a substitute's OS/2 charset flags must not reinterpret the input.
        return decode_codepage(data, codepage)

    def layout_font(self, request, face, scale, *, characters=None):
        if characters is None:
            if face is self._symbol_face or (face.family.casefold(), face.weight, face.italic) != (
                self._name(request).casefold(),
                request.weight or 400,
                bool(request.italic),
            ):
                raise UnsupportedOperation("Glyph-index text requires the requested font, not a substitute")
            return self.realize(request, face, scale)
        missing = {ord(c) for c in characters if ord(c) >= 32 and not face.cmap.get(ord(c))}
        linked = []
        if not face.symbol:
            for entry in self._ranked(request):
                if not missing:
                    break
                if entry.symbol or not missing.intersection(entry.coverage):
                    continue
                fallback = self._load(entry)
                if fallback is None or fallback is face:
                    continue
                linked.append(fallback.realize(request, scale, missing_glyph=self.missing_glyph))
                missing.difference_update(c for c, glyph in fallback.cmap.items() if glyph)
                self._report(request, fallback, "glyph coverage")
        if missing:
            self._report(request, face, "missing glyph")
        return FontRun(face.realize(request, scale, missing_glyph=self.missing_glyph), tuple(linked))
