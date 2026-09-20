"""Survey fonts selected by real text calls and build a Windows comparison page.

Input is an extracted release: CORPUS/path.wmf and SIZE/CORPUS/path.png.
Outputs are ad-hoc reports, never compatibility fixtures or new references.
"""

import argparse
import json
from collections import Counter
from dataclasses import asdict, replace
from html import escape
from pathlib import Path

from PIL import Image, ImageChops

from pillow_wmf import Font, Metafile, SystemFontCollection, TraceContext, play, render
from pillow_wmf.constants import ETO_GLYPH_INDEX
from pillow_wmf.text import _blank_control, decode_single_byte
from pillow_wmf.wmf.variable import ExtTextOut, TextOut


class TextSurvey(TraceContext):
    """Track font selection and SaveDC/RestoreDC without rasterizing drawings."""

    def __init__(self):
        super().__init__()
        self.font = None
        self.font_objects = {}
        self.saved_fonts = []
        self.runs = []

    def invoke(self, call):
        result = super().invoke(call)
        args = call.kwargs
        if call.name == "create_font":
            self.font_objects[result] = args["font"]
        elif call.name == "select_object" and args["handle"] in self.font_objects:
            self.font = self.font_objects[args["handle"]]
        elif call.name == "delete_object":
            self.font_objects.pop(args["handle"], None)
        elif call.name == "save_dc":
            self.saved_fonts.append(self.font)
        elif call.name == "restore_dc":
            level = args["saved_dc"]
            index = level - 1 if level > 0 else len(self.saved_fonts) + level
            self.font = self.saved_fonts[index]
            del self.saved_fonts[index:]
        elif call.name in {"text_out", "ext_text_out"} and args["text"]:
            self.runs.append((self.font, args["text"], args.get("options", 0)))
        return result


def family(font):
    return decode_single_byte(font.face_name.split(b"\0", 1)[0], 1252) if font else "<default>"


def scan(root):
    groups, failures, text_files = {}, [], set()
    sources = sorted(p for p in root.rglob("*") if p.suffix.lower() == ".wmf")
    for index, path in enumerate(sources):
        relative = str(path.relative_to(root))
        try:
            metafile = Metafile.from_bytes(path.read_bytes())
            if not any(isinstance(r, (TextOut, ExtTextOut)) for r in metafile.records):
                continue
            survey = TextSurvey()
            omissions = play(metafile, survey)
            if omissions:
                failures.append({"file": relative, "error": f"Trace omissions: {omissions}"})
            for font, data, options in survey.runs:
                text_files.add(relative)
                logical = font or Font(height=-16, face_name=b"Arial")
                key = (
                    family(font),
                    logical.weight or 400,
                    bool(logical.italic),
                    logical.charset,
                    logical.pitch_and_family,
                    bool(options & ETO_GLYPH_INDEX),
                )
                group = groups.setdefault(key, {"font": font, "runs": 0, "files": set(), "samples": set()})
                group["runs"] += 1
                group["files"].add(relative)
                group["samples"].add(data)
        except (ValueError, OSError, RuntimeError) as error:
            failures.append({"file": relative, "error": str(error)})
        if index % 1000 == 0:
            print(f"Scanned {index}/{len(sources)}", flush=True)
    return groups, failures, len(sources), text_files


def check_group(key, group, fonts):
    name, weight, italic, charset, pitch, indices = key
    result = dict(
        family=name,
        weight=weight,
        italic=italic,
        charset=charset,
        pitch=pitch,
        glyph_indices=indices,
        runs=group["runs"],
        files=sorted(group["files"]),
    )
    result["used_bytes"] = " ".join(f"{b:02X}" for b in sorted(set(b"".join(group["samples"]))))
    fonts.substitutions.clear()
    try:
        request = group["font"] or fonts.default_font
        face = fonts.resolve(request)
        result["selected"] = face.family
        result["selected_path"] = next((str(e.path) for e, f in fonts._loaded.items() if f is face), "bundled")
        # Coverage checks use the original byte payloads but a bounded em size.
        # Actual layout, spacing and masks are reviewed on whole-file images.
        request = replace(request, height=-20, width=0, escapement=0, orientation=0)
        text = "".join(fonts.decode(request, face, data) for data in sorted(group["samples"])) if not indices else None
        run = fonts.layout_font(request, face, (1, 1), characters=text)
        if text is not None:
            missing = {
                ord(c)
                for c in text
                if not _blank_control(c) and not any(f.cmap.get(ord(c)) for f in (run.primary, *run.fallbacks))
            }
            result["missing_codepoints"] = [f"U+{c:04X}" for c in sorted(missing)]
            result["sample"] = text[:200]
        result["status"] = "missing glyphs" if result.get("missing_codepoints") else "resolved; visual review required"
    except (ValueError, OSError, RuntimeError) as error:
        result.update(status="blocked", error=str(error))
    result["substitutions"] = [asdict(s) for s in fonts.substitutions]
    return result


def review_images(root, output, groups, fonts, size):
    # One whole-file example for every family/style/charset combination; shared
    # examples are rendered once. No claim that one example exhausts all glyphs.
    paths = sorted({group["files"][0] for group in groups})
    results = {}
    for index, relative in enumerate(paths):
        source = root / relative
        reference = (root / size / relative).with_suffix(".png")
        item = {"reference": str(reference)}
        try:
            with Image.open(reference) as image:
                native = image.convert("RGB")
            native.save(output / f"{index}-windows.png")
            fonts.substitutions.clear()
            actual = render(source.read_bytes(), native.size, fonts=fonts)
            actual.save(output / f"{index}-ours.png")
            difference = ImageChops.difference(actual, native)
            item["differing_pixels"] = sum(p != (0, 0, 0) for p in difference.get_flattened_data())
            item["substitutions"] = [asdict(s) for s in fonts.substitutions]
            item["status"] = "exact" if difference.getbbox() is None else "different"
        except (ValueError, OSError, RuntimeError) as error:
            item.update(status="blocked", error=str(error))
        results[relative] = item
        print(f"Review {index + 1}/{len(paths)}: {relative}: {item['status']}", flush=True)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--size", default="128x128")
    parser.add_argument("--refresh-page", action="store_true", help="Rebuild HTML from existing report and images")
    parser.add_argument(
        "--font-dir", type=Path, action="append", help="Restrict the inventory; repeat for portable-font tests"
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.refresh_page:
        write_page(json.loads((args.output / "survey.json").read_text()), args.output)
        return
    groups, failures, count, text_files = scan(args.root)
    paths = None
    if args.font_dir:
        paths = [p for root in args.font_dir for p in root.rglob("*") if p.suffix.lower() in {".ttf", ".ttc", ".otf"}]
    fonts = SystemFontCollection(paths=paths)
    checked = [check_group(key, group, fonts) for key, group in sorted(groups.items())]
    report = {
        "inputs": count,
        "text_files": len(text_files),
        "groups": checked,
        "scan_failures": failures,
        "font_directories": [str(p) for p in args.font_dir or ()],
    }
    (args.output / "survey.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(Counter(g["status"] for g in checked), flush=True)
    report["reviews"] = review_images(args.root, args.output, checked, fonts, args.size)
    (args.output / "survey.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    write_page(report, args.output)


def write_page(report, output):
    checked, reviews = report["groups"], report["reviews"]
    sections = []
    for index, (relative, item) in enumerate(sorted(reviews.items())):
        relevant = [g for g in checked if relative in g["files"]]
        names = sorted({g["family"] for g in relevant})
        labels = [
            f"{g['family']} {g['weight']}{' italic' if g['italic'] else ''}, charset {g['charset']}" for g in relevant
        ]
        panels = []
        for suffix, label in (("windows", "Windows"), ("ours", "Automatic fonts")):
            if (output / f"{index}-{suffix}.png").is_file() and (suffix == "windows" or item["status"] != "blocked"):
                panels.append(
                    f'<figure><figcaption>{label}</figcaption><img loading="lazy" src="{index}-{suffix}.png"></figure>'
                )
        sections.append(
            f'<section hidden data-families="{escape(json.dumps(names), quote=True)}" id="case-{index}">'
            f'<h2>{escape(relative)}</h2><p>{escape("; ".join(labels))}</p><div class="panels">{"".join(panels)}</div>'
            f"<details><summary>{escape(item['status'])} — details</summary><pre>{escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></section>"
        )
    example_paths = sorted(reviews)
    rows = "".join(
        f'<tr data-family="{escape(g["family"], quote=True)}"><td><a onclick="showCase(this.hash)" href="#case-{example_paths.index(g["files"][0])}">{escape(g["family"])}</a></td>'
        f"<td>{g['weight']}{' italic' if g['italic'] else ''}</td>"
        f"<td>{g['charset']}</td><td>{len(g['files'])}</td><td>{escape(g.get('selected', '—'))}</td>"
        f"<td>{escape(g['status'])}</td><td>{escape(g.get('error', ', '.join(g.get('missing_codepoints', ()))))}</td></tr>"
        for g in checked
    )
    options = "".join(
        f'<option value="{escape(name, quote=True)}">{escape(name) or "(empty family)"}</option>'
        for name in sorted({g["family"] for g in checked})
    )
    html = f"""<!doctype html><meta charset="utf-8"><title>Corpus font survey</title>
<style>body{{font:16px sans-serif;margin:24px;background:#eee}}td,th{{padding:6px;text-align:left}}
.panels{{display:flex;gap:24px}}figure{{margin:0}}img{{width:calc(128px * var(--zoom,2));image-rendering:pixelated}}
section{{margin:32px 0}}pre{{white-space:pre-wrap}}table{{border-collapse:collapse}}tr{{border-bottom:1px solid #bbb}}</style>
<h1>Corpus font survey</h1><p>{report["inputs"]} WMFs; {report["text_files"]} with nonempty text; {len(checked)} font/style/charset groups.
{len(report["scan_failures"])} scan errors/omissions are recorded separately in survey.json.</p>
<p>These release references do not pin or report the Windows-selected fonts. Review visible substitutions;
successful rendering or complete cmap coverage alone does not prove correct symbols or Windows parity.
Examples cover each group, not every occurrence. No new Windows output was generated.</p>
<p>Font inventory: {escape(", ".join(report.get("font_directories", ())) or "all installed fonts")}</p>
<label>Family <select id="family" onchange="filterFamily(this.value)"><option value="__none__">Choose a family</option>{options}<option value="__all__">Show all</option></select></label>
<label>Zoom <select onchange="document.body.style.setProperty('--zoom',this.value)"><option>2</option><option>1</option><option>4</option></select></label>
<table><tr><th>Requested</th><th>Style</th><th>Charset</th><th>Files</th><th>Selected</th><th>Coverage</th><th>Problem</th></tr>{rows}</table>
{"".join(sections)}
<script>
function filterFamily(name) {{
 for (const section of document.querySelectorAll('section')) section.hidden = name !== '__all__' && !JSON.parse(section.dataset.families).includes(name);
 for (const row of document.querySelectorAll('tr[data-family]')) row.hidden = name !== '__all__' && row.dataset.family !== name;
}}
function showCase(hash) {{ document.querySelector(hash).hidden = false; }}
filterFamily('__none__');
</script>"""
    (output / "index.html").write_text(html, encoding="utf-8")
    print(output / "index.html", flush=True)


if __name__ == "__main__":
    main()
