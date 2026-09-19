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


def gallery(
    source,
    output,
    *,
    title="Real-font mismatches",
    missing_glyph="error",
    font_paths=(),
    fallbacks=None,
    synthesize_styles=False,
):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    paths = [*sorted((source / "fonts").glob("*.ttf")), *font_paths]
    fonts = FontCollection(
        (face for path in paths for face in load_faces(path)),
        missing_glyph=missing_glyph,
        fallbacks=fallbacks,
        synthesize_styles=synthesize_styles,
    )
    entries, blocked = [], []
    exact = 0
    for wmf in sorted(source.glob("*.wmf")):
        with Image.open(wmf.with_suffix(".png")) as image:
            native = image.convert("RGB")
        context = RasterContext(*native.size, fonts=fonts)
        try:
            play(Metafile.from_bytes(wmf.read_bytes()), context, strict=True)
        except (UnsupportedOperation, ValueError) as error:
            blocked.append(f"{wmf.name}: {error}")
            continue
        actual = context.image.convert("RGB")
        difference = ImageChops.difference(native, actual)
        if difference.getbbox() is None:
            exact += 1
            continue
        count = sum(pixel != (0, 0, 0) for pixel in difference.get_flattened_data())
        mask = difference.convert("RGB").point(lambda value: 255 if value else 0)
        red, green, blue = mask.split()
        mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
        highlight = Image.new("RGB", native.size, "white")
        highlight.paste((255, 0, 100), mask=mask)
        cells = []
        for label, image in (("Windows", native), ("Ours", actual), ("Difference", highlight)):
            filename = f"{wmf.stem}-{label.lower()}.png"
            image.save(output / filename)
            cells.append(f'<figure><figcaption>{label}</figcaption><img src="{escape(filename)}"></figure>')
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
    total = exact + len(entries) + len(blocked)
    if not total:
        raise ValueError("No WMF/PNG pairs found")
    summary = f"{total} cases: {exact} exact, {len(entries)} mismatches, {len(blocked)} blocked."
    page = f"""<!doctype html><meta charset="utf-8"><title>{escape(title)}</title>
<style>body{{font:16px sans-serif;background:#eee;margin:24px}}section div{{display:flex;gap:16px;overflow:auto}}
figure{{margin:0}}img{{image-rendering:pixelated;width:calc(640px * var(--zoom, 1));height:auto}}
figcaption{{padding:8px 0}}section{{margin:32px 0}}pre{{white-space:pre-wrap}}</style>
<h1>{escape(title)}</h1><p>{summary}</p>
<p>Windows left, ours middle, pink mismatches right. Exact cases are omitted.
Primary fonts use identical files. Any extra fallback fonts are supplied locally and may differ
from the Windows version. Unsupported cases are listed separately.</p>
<p>Missing-glyph policy: {escape(missing_glyph)} (notdef uses the supplied face's glyph zero, not font linking).</p>
<p>Explicit fallback chains: {escape(str(fallbacks or {}))}</p>
<label>Pixel zoom <select onchange="document.body.style.setProperty('--zoom',this.value)">
<option>1</option><option>2</option><option>4</option></select></label>
{"".join(entries)}<h2>Blocked cases</h2><pre>{escape(chr(10).join(blocked) or "None")}</pre>"""
    (output / "index.html").write_text(page, encoding="utf-8")
    print(summary)
    print(output / "index.html")
    return exact, len(entries), len(blocked)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--title", default="Real-font mismatches")
    parser.add_argument("--missing-glyph", choices=("error", "notdef"), default="error")
    parser.add_argument(
        "--synthesize-styles", action="store_true", help="Allow bold/italic synthesis from regular faces"
    )
    parser.add_argument("--font", type=Path, action="append", default=[], help="Additional local font file")
    parser.add_argument("--fallback", action="append", default=[], metavar="BASE=FAMILY", help="Append a fallback face")
    args = parser.parse_args()
    fallbacks = {}
    for entry in args.fallback:
        base, separator, family = entry.partition("=")
        if not separator or not base or not family:
            parser.error("Fallback must have the form BASE=FAMILY")
        fallbacks.setdefault(base, []).append(family)
    gallery(
        args.source,
        args.output,
        title=args.title,
        missing_glyph=args.missing_glyph,
        font_paths=args.font,
        fallbacks=fallbacks,
        synthesize_styles=args.synthesize_styles,
    )


if __name__ == "__main__":
    main()
