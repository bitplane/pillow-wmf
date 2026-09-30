"""Explicit font selection, encoding policy and linked glyph runs."""

from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import groupby

from .dbcs import DecodedText
from .environment_codepages import MAC_CODECS, OEM_CODECS, OEM_COVERAGE_BITS
from .font import FontFace as FontFace
from .font import Glyph as Glyph
from .font import RasterFont as RasterFont
from .gdi import UnsupportedOperation
from .mac_dbcs import CODECS as MAC_DBCS_CODECS
from .objects import EncodedFaceName, FontRequest
from .text_encoding import C1_CONTROLS as C1_CONTROLS
from .text_encoding import CODEPAGE_BITS as CODEPAGE_BITS
from .text_encoding import SINGLE_BYTE_CHARSETS as SINGLE_BYTE_CHARSETS
from .text_encoding import TEXT_CHARSETS as TEXT_CHARSETS
from .text_encoding import UNDEFINED_BYTE_MAPPINGS as UNDEFINED_BYTE_MAPPINGS
from .text_encoding import decode_codepage as decode_codepage
from .text_encoding import decode_single_byte as decode_single_byte
from .text_layout import TextLayout as TextLayout
from .text_layout import layout_text as layout_text
from .text_layout import paired_background as paired_background
from .text_math import text_rotation as text_rotation
from .wingdings import decode_wingdings


class FontCollection:
    """Supplied faces and explicit aliases; never discover or silently replace."""

    def __init__(
        self,
        faces=(),
        *,
        ansi_codepage=1252,
        oem_codepage=437,
        mac_codepage=None,
        aliases=None,
        fallbacks=None,
        missing_glyph="error",
        synthesize_styles=False,
        wingdings_fallback=False,
        symbol_fallback=False,
        default_font: FontRequest | None = None,
    ):
        if ansi_codepage not in CODEPAGE_BITS:
            raise ValueError(f"Unsupported ANSI environment: {ansi_codepage}")
        if oem_codepage not in OEM_CODECS and oem_codepage not in {874, 932, 936, 949, 950, 1258}:
            raise ValueError(f"Unsupported OEM environment: {oem_codepage}")
        if mac_codepage is not None and mac_codepage not in MAC_CODECS | MAC_DBCS_CODECS:
            raise ValueError(f"Unsupported Macintosh environment: {mac_codepage}")
        if missing_glyph not in ("error", "notdef"):
            raise ValueError("Missing-glyph policy must be 'error' or 'notdef'")
        self.ansi_codepage = ansi_codepage
        self.oem_codepage = oem_codepage
        self.mac_codepage = mac_codepage
        self.missing_glyph = missing_glyph
        self.synthesize_styles = synthesize_styles
        self.wingdings_fallback = wingdings_fallback
        self.symbol_fallback = symbol_fallback
        self.default_font = default_font.to_gdi("create_font") if hasattr(default_font, "to_gdi") else default_font
        self._wingdings_face = None
        self._symbol_face = None
        self.aliases = {name.casefold(): target.casefold() for name, target in (aliases or {}).items()}
        self.fallbacks = {name.casefold(): tuple(targets) for name, targets in (fallbacks or {}).items()}
        self._faces = {}
        for face in faces:
            key = (face.family.casefold(), face.weight, face.italic)
            if key in self._faces:
                raise ValueError(f"Ambiguous font face: {face.family}")
            self._faces[key] = face
        if default_font is not None:
            try:
                self.resolve(default_font)
            except UnsupportedOperation as error:
                raise ValueError(f"Invalid default font: {error}") from error

    def realize(self, request, face, scale):
        primary = face.realize(request, scale, missing_glyph=self.missing_glyph)
        fallback_faces = []
        for family in self.fallbacks.get(face.family.casefold(), ()):
            key = family.casefold(), request.weight or 400, bool(request.italic)
            fallback = self._select_face(key)
            if fallback is None:
                raise UnsupportedOperation(f"Fallback font unavailable: {family!r}")
            if fallback.symbol:
                raise UnsupportedOperation("A symbol face cannot be a Unicode fallback")
            fallback_faces.append(fallback)
        linked = tuple(f.realize(request, scale, missing_glyph=self.missing_glyph) for f in fallback_faces)
        control_fallback = None
        if fallback_faces:
            # Shaping fallback preserves the realized cell, not the original
            # em request. Its GDI links follow the replacement's realized em.
            cell = Fraction(primary.ascent + primary.descent) / scale[1]
            raw_request = replace(request, height=cell)
            raw = fallback_faces[0].realize(raw_request, scale, missing_glyph=self.missing_glyph)
            raw_links = tuple(
                f.at_size(
                    raw.font.size.y_ppem,
                    width=raw.em_width if request.width else None,
                    quality=request.quality,
                    missing_glyph=self.missing_glyph,
                    escapement=request.escapement,
                    synthetic_bold=request.weight >= 700 and f.weight < 700,
                    synthetic_italic=bool(request.italic) and not f.italic,
                )
                for f in fallback_faces[1:]
            )
            control_fallback = FontRun(raw, raw_links)
        return FontRun(primary, linked, control_fallback)

    def layout_font(self, request, face, scale, *, characters=None):
        """Prepare a run; controlled fonts never depend on host discovery."""
        return self.realize(request, face, scale)

    def resolve(self, request):
        request = self.default_font if request is None else request
        if request is None:
            raise UnsupportedOperation("Default font resolution")
        family = self.face_name(request).casefold()
        family = self.aliases.get(family, family)
        key = family, request.weight or 400, bool(request.italic)
        face = self._select_face(key)
        if (
            face is None
            and self.wingdings_fallback
            and family == "wingdings"
            and (key[1:] == (400, False) or self.synthesize_styles and key[1] in (400, 700))
        ):
            if self._wingdings_face is None:
                self._wingdings_face = FontFace.bundled_wingdings()
            face = self._wingdings_face
        if (
            face is None
            and self.symbol_fallback
            and family == "symbol"
            and (key[1:] == (400, False) or self.synthesize_styles and key[1] in (400, 700))
        ):
            if self._symbol_face is None:
                self._symbol_face = FontFace.bundled_symbol()
            face = self._symbol_face
        if face is None:
            raise UnsupportedOperation(f"Font face unavailable: {family!r}, weight={key[1]}, italic={key[2]}")
        return face

    def _select_face(self, key):
        face = self._faces.get(key)
        if face is None and self.synthesize_styles and key[1] in (400, 700):
            face = self._faces.get((key[0], 400, False))
        return face

    def _charset(self, request):
        # GDI forces SYMBOL_CHARSET for the legacy family named Symbol, not
        # for arbitrary symbol-cmap fonts (including Wingdings).
        family = self.face_name(request)
        return 2 if family.casefold() == "symbol" and request.charset != 254 else request.charset

    def face_name(self, request):
        """Resolve a logical name, or a legacy name in this ANSI environment."""
        name = request.face_name
        if isinstance(name, str):
            return name.split("\0", 1)[0]
        data = name.data if isinstance(name, EncodedFaceName) else name
        return decode_codepage(data.split(b"\0", 1)[0], self.ansi_codepage).text

    def _encoding(self, request):
        charset = self._charset(request)
        if charset == 1:
            return self.ansi_codepage, CODEPAGE_BITS[self.ansi_codepage]
        if charset == 255:
            return self.oem_codepage, 30
        if charset == 77 and self.mac_codepage is not None:
            return self.mac_codepage, 29
        if encoding := TEXT_CHARSETS.get(charset):
            return encoding
        raise UnsupportedOperation(f"Unsupported text charset: {request.charset}")

    def decode(self, request, face, data):
        return self.decode_run(request, face, data).text

    def decode_run(self, request, face, data):
        charset = self._charset(request)
        if face is self._wingdings_face:
            if charset not in (1, 2):
                raise UnsupportedOperation("Unsupported Wingdings fallback charset request")
            return DecodedText.single_byte(decode_wingdings(data))
        if face.symbol:
            if charset not in (1, 2):
                raise UnsupportedOperation("Unsupported symbol font charset request")
            return DecodedText.single_byte("".join(chr(0xF000 | byte) for byte in data))
        codepage, bit = self._encoding(request)
        coverage = 1 << bit
        if charset == 255:
            page_bit = OEM_COVERAGE_BITS.get(codepage, CODEPAGE_BITS.get(codepage))
            if page_bit is not None:
                coverage |= 1 << page_bit
        if not face.codepages & coverage:
            raise UnsupportedOperation("Font does not advertise the requested charset; explicit selection is required")
        return decode_codepage(data, codepage)


@dataclass(frozen=True)
class FontRun:
    """Use base line metrics, selecting supplied fallback faces only for holes."""

    primary: RasterFont
    fallbacks: tuple[RasterFont, ...] = ()
    control_fallback: "FontRun | None" = None

    @property
    def ascent(self):
        return self.primary.ascent

    @property
    def descent(self):
        return self.primary.descent

    @property
    def break_character(self):
        return self.primary.break_character

    @property
    def decorations(self):
        return self.primary.decorations

    @property
    def background_cell(self):
        return self.primary.background_cell

    def glyph(self, character, max_pixels):
        return self.shape(character, max_pixels)[0]

    def glyph_index(self, index, max_pixels):
        return self.primary.glyph_index(index, max_pixels)

    def shape(self, characters, max_pixels, *, raw=False):
        """Shape SBCS control runs before choosing masks and advances.

        A control run containing an unshapable character falls back to raw
        character output. Its formerly invisible controls then participate in
        font linking too. Separators terminate runs; they are not tab stops or
        multiline layout commands. Paired advances request raw glyph output,
        bypassing the control-run shaper without disabling font linking.
        """
        if self.primary.symbol:
            return self.primary.shape(characters, max_pixels)
        if raw:
            return tuple(self._linked_glyph(c, max_pixels) for c in characters)
        glyphs = []
        for kind, group in groupby(characters, key=_text_run_kind):
            run = "".join(group)
            if kind == "text":
                glyphs.extend(self._linked_glyph(c, max_pixels) for c in run)
                continue
            missing = [c for c in run if not _blank_control(c) and not self.primary.cmap.get(ord(c))]
            fallback = self
            if missing and self.fallbacks:
                fallback = self.control_fallback or FontRun(self.fallbacks[0], self.fallbacks[1:])
            # Uniscribe accepts DEL's default glyph; it does not make an
            # otherwise shapeable control run switch to raw character output.
            if any(c != "\x7f" for c in missing):
                # GDI suppresses linking for a suffix made entirely of C1
                # controls, not for a C1 character preceding another class.
                link_end = len(run.rstrip(C1_CONTROLS))
                glyphs.extend(
                    fallback._linked_glyph(c, max_pixels, replacement="\u30fb")
                    if i < link_end
                    else fallback.primary.glyph(c, max_pixels)
                    for i, c in enumerate(run)
                )
            else:
                glyphs.extend(
                    Glyph((0, 0), (0, 0), b"", 0) if _blank_control(c) else fallback.primary.glyph(c, max_pixels)
                    for c in run
                )
        return tuple(glyphs)

    def _linked_glyph(self, character, max_pixels, *, replacement=None):
        codepoint = ord(character)
        if self.primary.cmap.get(codepoint):
            return self.primary.glyph(character, max_pixels)
        for fallback in self.fallbacks:
            if fallback.cmap.get(codepoint):
                glyph = fallback.glyph(character, max_pixels)
                # GDI's linked-font lookup rejects zero-advance candidates,
                # even when their cmap contains the requested character.
                if glyph.advance:
                    return glyph
        if replacement is not None:
            # Raw GDI output retries the linking chain with the default link
            # character (Katakana middle dot) before using the base .notdef.
            codepoint = ord(replacement)
            for fallback in (self.primary, *self.fallbacks):
                if fallback.cmap.get(codepoint):
                    glyph = fallback.glyph(replacement, max_pixels)
                    if glyph.advance:
                        return glyph
        return self.primary.glyph(character, max_pixels)


def _text_run_kind(character):
    codepoint = ord(character)
    if character in "\t\n\v\r\x1c\x1d\x1e\x1f\x85":
        return character
    if (codepoint < 32 and character != "\f") or 0x7F <= codepoint <= 0x9F:
        return "control"
    return "text"


def _blank_control(character):
    return character in "\t\n\r\x1c\x1d\x1e\x1f" or 0x80 <= ord(character) <= 0x9F
