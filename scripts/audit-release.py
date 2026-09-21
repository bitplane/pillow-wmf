"""Ad-hoc strict release comparisons and a newly-unblocked text review page."""

import argparse
import json
import multiprocessing
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from html import escape
from pathlib import Path

from PIL import Image, ImageChops

from pillow_wmf import SystemFontCollection, render
from pillow_wmf.render import _read_metafile
from pillow_wmf.wmf.variable import ExtTextOut, TextOut


def initialize(root, output, font_directories, candidates):
    global ROOT, OUTPUT, FONTS, CANDIDATES, FONT_PATHS, TASK_COUNT
    ROOT, OUTPUT, CANDIDATES = Path(root), Path(output), candidates
    paths = [
        p
        for directory in font_directories
        for p in Path(directory).rglob("*")
        if p.suffix.lower() in {".ttf", ".ttc", ".otf"}
    ]
    FONT_PATHS, TASK_COUNT = paths, 0
    FONTS = SystemFontCollection(paths=FONT_PATHS)


def compare(relative):
    global FONTS, TASK_COUNT
    # Drop accumulated face/size caches without recycling executor processes.
    if TASK_COUNT and TASK_COUNT % 100 == 0:
        FONTS = SystemFontCollection(paths=FONT_PATHS)
    TASK_COUNT += 1
    item = {"file": relative, "has_text": None}
    try:
        reference = (ROOT / "128x128" / relative).with_suffix(".png")
        if not reference.is_file():
            return item | {"status": "missing-reference"}
        data = (ROOT / relative).read_bytes()
        metafile = _read_metafile(data)
        item["has_text"] = any(isinstance(r, (TextOut, ExtTextOut)) and r.text for r in metafile.records)
        with Image.open(reference) as image:
            native = image.convert("RGB")
        FONTS.substitutions.clear()
        actual = render(data, native.size, fonts=FONTS)
        difference = ImageChops.difference(native, actual)
        count = sum(pixel != (0, 0, 0) for pixel in difference.get_flattened_data())
        item.update(status="different" if count else "exact", differing_pixels=count, size=native.size)
        if item["has_text"]:
            item["substitutions"] = [asdict(s) for s in FONTS.substitutions]
        if relative in CANDIDATES and count:
            prefix = Path("images") / relative
            target = OUTPUT / prefix
            target.parent.mkdir(parents=True, exist_ok=True)
            actual.save(str(target) + "-ours.png")
            native.save(str(target) + "-windows.png")
            mask = difference.convert("RGB").point(lambda v: 255 if v else 0)
            red, green, blue = mask.split()
            mask = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            highlight = Image.new("RGB", native.size, "white")
            highlight.paste((255, 0, 100), mask=mask)
            highlight.save(str(target) + "-diff.png")
            item["review"] = str(prefix)
    except (ValueError, OSError, RuntimeError) as error:
        item.update(status="blocked", error=str(error), error_type=type(error).__name__)
    except Exception as error:
        item.update(status="error", error=str(error), error_type=type(error).__name__)
    return item


def write_page(output, results, candidates, total):
    counts = Counter(r["status"] for r in results)
    sections = []
    for item in sorted(results, key=lambda r: r["file"]):
        if "review" not in item:
            continue
        cells = "".join(
            f'<figure><figcaption>{label}</figcaption><img loading="lazy" '
            f'src="{escape(item["review"] + suffix, quote=True)}"></figure>'
            for suffix, label in (("-windows.png", "Windows"), ("-ours.png", "Ours"), ("-diff.png", "Difference"))
        )
        sections.append(
            f"<section><h2>{escape(item['file'])}</h2>"
            f"<p>Previous blocker: {escape(candidates[item['file']])}</p>"
            f"<p>{item['differing_pixels']} differing pixels</p><div>{cells}</div>"
            f"<details><summary>Font substitutions</summary><pre>{escape(json.dumps(item.get('substitutions', []), indent=2))}</pre></details></section>"
        )
    remaining = [r for r in results if r["file"] in candidates and r["status"] in ("blocked", "error")]
    summary = {
        "completed": len(results),
        "total": total,
        "statuses": dict(counts),
        "text": dict(Counter(r["status"] for r in results if r["has_text"])),
        "non_text": dict(Counter(r["status"] for r in results if r["has_text"] is False)),
        "review_cases": len(sections),
        "remaining_previous_blockers": remaining,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    page = f"""<!doctype html><meta charset="utf-8"><title>Newly unblocked corpus text</title>
<style>body{{font:16px sans-serif;background:#eee;margin:24px}}section{{margin:32px 0}}
section div{{display:flex;gap:24px;overflow:auto}}figure{{margin:0}}img{{width:calc(128px * var(--zoom,1));image-rendering:pixelated}}
pre{{white-space:pre-wrap}}figcaption{{padding:8px 0}}</style>
<h1>Newly unblocked corpus text</h1><p>Compared {len(results)} of {total} WMFs. {escape(str(dict(counts)))}</p>
<p>Windows left, ours middle, pink differences right. Only previously blocked examples or examples of previously blocked encoding groups are shown.
Exact matches are omitted. Release Windows fonts are not pinned: these are visual integration comparisons, not proof of identical glyph rasterization.
Text-bearing differences do not establish whether their non-text drawing is correct.</p>
<label>Zoom <select onchange="document.body.style.setProperty('--zoom',this.value)"><option>1</option><option>2</option><option>4</option></select></label>
{"".join(sections)}<h2>Still blocked candidates</h2><pre>{escape(json.dumps(remaining, indent=2))}</pre>"""
    (output / "index.html").write_text(page, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--resume", action="store_true", help="Continue this audit using its saved results")
    parser.add_argument("--retry-results", type=Path, help="Only retry earlier blockers and non-text mismatches")
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text())
    directories = baseline["font_directories"]
    if not directories or any(not Path(p).is_dir() for p in directories):
        parser.error("Baseline portable font directories must still exist")
    candidates = {name: r["error"] for name, r in baseline["reviews"].items() if r["status"] == "blocked"}
    for group in baseline["groups"]:
        if group["status"] == "blocked" and "charset" in group.get("error", ""):
            for name in group["files"]:
                candidates.setdefault(name, "Previously blocked encoding group: " + group["error"])
    sources = sorted(str(p.relative_to(args.root)) for p in args.root.rglob("*") if p.suffix.lower() == ".wmf")
    sources.sort(key=lambda name: name not in candidates)
    if args.retry_results:
        previous = [json.loads(line) for line in args.retry_results.read_text().splitlines()]
        retry = {
            r["file"]
            for r in previous
            if r["status"] in ("blocked", "error", "missing-reference")
            or r["has_text"] is False
            and r["status"] == "different"
        }
        sources = [name for name in sources if name in retry]
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "results.jsonl"
    if result_path.exists() and not args.resume:
        parser.error("Use a new output directory to preserve earlier audit results")
    results = [json.loads(line) for line in result_path.read_text().splitlines()] if result_path.exists() else []
    completed = {r["file"] for r in results}
    with (
        result_path.open("a", encoding="utf-8", buffering=1) as stream,
        ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=initialize,
            initargs=(args.root, args.output, directories, candidates),
        ) as pool,
    ):
        pending = {pool.submit(compare, name): name for name in sources if name not in completed}
        for future in as_completed(pending):
            result = future.result()
            results.append(result)
            stream.write(json.dumps(result) + "\n")
            if result["file"] in candidates or len(results) % 100 == 0:
                write_page(args.output, results, candidates, len(sources))
                print(f"{len(results)}/{len(sources)} {dict(Counter(r['status'] for r in results))}", flush=True)
    write_page(args.output, results, candidates, len(sources))
    print(args.output / "index.html", flush=True)


if __name__ == "__main__":
    main()
