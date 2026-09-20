"""Compare a downloaded real-text probe and show only mismatches in HTML."""

import argparse
from html import escape
from pathlib import Path

from fontTools.ttLib import TTCollection
from PIL import Image, ImageChops

from pillow_wmf import FontCollection, FontFace, Metafile, RasterContext, UnsupportedOperation, play


def load_faces(path):
    """Expose each named face in a supplied TrueType collection."""
    path = Path(path)
    if path.suffix.lower() == ".ttc":
        with TTCollection(path, lazy=True) as collection:
            count = len(collection.fonts)
        return [FontFace.from_path(path, index=index) for index in range(count)]
    return [FontFace.from_path(path)]


def corpus_pairs(source, references):
    """Match WMFs in parallel extracted source/reference trees."""
    source, references = Path(source), Path(references)
    for wmf in sorted(source.rglob("*")):
        if wmf.suffix.lower() != ".wmf":
            continue
        yield wmf, (references / wmf.relative_to(source)).with_suffix(".png")


def gallery(
    source,
    output,
    *,
    title="Real-font mismatches",
    missing_glyph="error",
    font_paths=(),
    fallbacks=None,
    synthesize_styles=False,
    wingdings_fallback=False,
    pairs=None,
    limit=None,
    text_only=False,
    font_note="Primary fonts use identical files. Extra fallback fonts may differ from Windows.",
):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    paths = [*sorted((source / "fonts").glob("*.ttf")), *font_paths]
    fonts = FontCollection(
        (face for path in paths for face in load_faces(path)),
        missing_glyph=missing_glyph,
        fallbacks=fallbacks,
        synthesize_styles=synthesize_styles,
        wingdings_fallback=wingdings_fallback,
    )
    entries, blocked = [], []
    exact = 0
    omitted = 0
    inputs = pairs if pairs is not None else ((p, p.with_suffix(".png")) for p in sorted(source.glob("*.wmf")))
    for index, (wmf, png) in enumerate(inputs):
        try:
            metafile = Metafile.from_bytes(wmf.read_bytes())
            if text_only and not any(r.operation in ("text_out", "ext_text_out") for r in metafile.records):
                continue
            with Image.open(png) as image:
                native = image.convert("RGB")
            context = RasterContext(*native.size, fonts=fonts)
            play(metafile, context, strict=True)
        except (UnsupportedOperation, ValueError, OSError) as error:
            blocked.append(f"{wmf}: {error}")
            continue
        actual = context.image.convert("RGB")
        difference = ImageChops.difference(native, actual)
        if difference.getbbox() is None:
            exact += 1
            continue
        if limit is not None and len(entries) >= limit:
            omitted += 1
            continue
        count = sum(pixel != (0, 0, 0) for pixel in difference.get_flattened_data())
        mask = difference.convert("RGB").point(lambda value: 255 if value else 0)
        red, green, blue = mask.split()
        mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        highlight = Image.new("RGB", native.size, "white")
        highlight.paste((255, 0, 100), mask=mask)
        cells = []
        for label, image in (("Windows", native), ("Ours", actual), ("Difference", highlight)):
            prefix = f"{index}-" if pairs is not None else ""
            filename = f"{prefix}{wmf.stem}-{label.lower()}.png"
            image.save(output / filename)
            cells.append(
                f"<figure><figcaption>{label}</figcaption>"
                f'<img style="--width:{native.width}px" src="{escape(filename)}"></figure>'
            )
        if context._text_state.font and context._text_state.font.quality == 0:
            note = "Default quality: RGB subpixel coverage; filtering and contrast remain approximate."
        else:
            note = "Monochrome: inspect ink shape and placement; differences are not automatically waived."
        request = context._text_state.font
        if request and request.escapement:
            note += " Rotation: line/background bounds and some placements still need alignment; this is not mask-only."
        if any(scale < 0 for scale in context.mapping.linear_scale):
            note += " Reflected mapping: opaque bounds still need alignment."
        entries.append(
            f"<section><h2>{escape(wmf.stem)} — {count} differing pixels</h2>"
            f"<p>{note}</p><div>{''.join(cells)}</div></section>"
        )
    total = exact + len(entries) + omitted + len(blocked)
    if not total:
        raise ValueError("No WMF/PNG pairs found")
    summary = f"{total} cases: {exact} exact, {len(entries) + omitted} mismatches, {len(blocked)} blocked."
    if omitted:
        summary += f" Showing {len(entries)} mismatches; {omitted} omitted by review limit."
    page = f"""<!doctype html><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font:16px sans-serif;background:#eee;margin:24px}}section div{{display:flex;gap:16px;overflow:auto}}
figure{{margin:0}}img{{image-rendering:pixelated;width:calc(var(--width) * var(--zoom, 1));height:auto}}
figcaption{{padding:8px 0}}section{{margin:32px 0}}pre{{white-space:pre-wrap}}</style>
<h1>{escape(title)}</h1><p>{summary}</p>
<p>Windows left, ours middle, pink mismatches right. Exact cases are omitted.
{escape(font_note)} Unsupported cases are listed separately; their non-font drawing is not validated.</p>
<p>Missing-glyph policy: {escape(missing_glyph)} (notdef uses the supplied face's glyph zero, not font linking).</p>
<p>Explicit fallback chains: {escape(str(fallbacks or {}))}</p>
<p>Wingdings Unicode fallback: {wingdings_fallback}. When enabled and the requested face is unavailable,
Noto Sans Symbols 2 supplies approximate shapes and metrics; missing glyphs remain subject to the stated policy.</p>
<label>Pixel zoom <select onchange="document.body.style.setProperty('--zoom',this.value)">
<option>1</option><option>2</option><option>4</option></select></label>
{"".join(entries)}<h2>Blocked cases</h2><pre>{escape(chr(10).join(blocked) or "None")}</pre>"""
    (output / "index.html").write_text(page, encoding="utf-8")
    print(summary)
    print(output / "index.html")
    return exact, len(entries) + omitted, len(blocked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Real-font mismatches")
    parser.add_argument(
        "--wingdings-fallback", action="store_true", help="Explicitly map missing Wingdings to bundled Noto"
    )
    parser.add_argument("--reference-root", type=Path, help="Parallel release PNG tree; select text-bearing WMFs")
    parser.add_argument("--limit", type=int, help="Maximum mismatches displayed; all inputs are still compared")
    parser.add_argument("--missing-glyph", choices=("error", "notdef"), default="error")
    parser.add_argument(
        "--synthesize-styles", action="store_true", help="Allow bold/italic synthesis from regular faces"
    )
    parser.add_argument("--font", type=Path, action="append", default=[], help="Additional local font file")
    parser.add_argument("--fallback", action="append", default=[], metavar="BASE=FAMILY", help="Append a fallback face")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    fallbacks = {}
    for entry in args.fallback:
        base, separator, family = entry.partition("=")
        if not separator or not base or not family:
            parser.error("Fallback must have the form BASE=FAMILY")
        fallbacks.setdefault(base, []).append(family)
    options = {}
    if args.reference_root:
        options = {
            "pairs": corpus_pairs(args.source, args.reference_root),
            "text_only": True,
            "font_note": "Release font versions and native substitutions are unverified. "
            "These are visual integration comparisons, not controlled-font rasterizer evidence.",
        }
    gallery(
        args.source,
        args.output,
        title=args.title,
        missing_glyph=args.missing_glyph,
        font_paths=args.font,
        fallbacks=fallbacks,
        synthesize_styles=args.synthesize_styles,
        wingdings_fallback=args.wingdings_fallback,
        limit=args.limit,
        **options,
    )


if __name__ == "__main__":
    main()
