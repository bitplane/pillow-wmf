"""Build one bounded, risk-focused review from an existing release audit."""

import argparse
import json
import runpy
from pathlib import Path

from pillow_wmf import SystemFontCollection
from pillow_wmf.render import _read_metafile
from pillow_wmf.wmf.variable import CreateFontIndirect, ExtTextOut


def select_examples(rows, survey, root, limit):
    different = {r["file"]: r for r in rows if r["status"] == "different" and r["has_text"]}
    selected = {}

    def add(name, reason):
        if len(selected) < limit:
            selected.setdefault(name, reason)

    for name, old in survey["reviews"].items():
        error = old.get("error", "")
        if old["status"] == "blocked" and "wingdings" in error.lower() and "weight=" in error:
            add(name, "Previously blocked symbol fallback weight")
    reviewed = set(survey["reviews"])
    for charset in (128, 134, 161, 162, 186, 204, 238, 255, 178, 160):
        available = {
            f
            for g in survey["groups"]
            if g["charset"] == charset
            for f in g["files"]
            if f in different and f not in selected
        }
        fresh = available - reviewed
        if available:
            name = max(fresh or available, key=lambda f: (different[f]["differing_pixels"], f))
            add(name, f"Charset {charset}: larger pixel discrepancy, preferring an unreviewed example")
    wanted = {"rotated", "paired advances", "explicit advances", "glyph indices"}
    ranked = sorted(different, key=lambda f: (-different[f]["differing_pixels"], f))
    for name in ranked:
        if not wanted or len(selected) >= limit:
            break
        if name in selected:
            continue
        m = _read_metafile((root / name).read_bytes())
        features = set()
        for record in m.records:
            if isinstance(record, CreateFontIndirect) and record.font.escapement % 3600:
                features.add("rotated")
            if isinstance(record, ExtTextOut):
                if record.options & 0x2000:
                    features.add("paired advances")
                if record.options & 0x10:
                    features.add("glyph indices")
                if record.advances:
                    features.add("explicit advances")
        if covered := wanted & features:
            add(name, "Layout risk: " + ", ".join(sorted(covered)))
            wanted -= covered
    for name in ranked:
        if len(selected) >= limit:
            break
        add(name, "Larger remaining text-bearing discrepancy")
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--survey", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    rows = [json.loads(line) for line in args.audit.read_text().splitlines()]
    survey = json.loads(args.survey.read_text())
    selected = select_examples(rows, survey, args.root, args.limit)
    paths = [
        p
        for directory in survey["font_directories"]
        for p in Path(directory).rglob("*")
        if p.suffix.lower() in {".ttf", ".ttc", ".otf"}
    ]
    fonts = SystemFontCollection(paths=paths)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "selection.json").write_text(json.dumps(selected, indent=2), encoding="utf-8")
    gallery = runpy.run_path(str(Path(__file__).with_name("text-gallery.py")))["gallery"]
    gallery(
        args.root,
        args.output,
        title="Remaining corpus text — bounded layout review",
        fonts=fonts,
        case_notes={str(args.root / name): f"{name}: {reason}" for name, reason in selected.items()},
        missing_glyph="notdef",
        pairs=[(args.root / name, (args.root / "128x128" / name).with_suffix(".png")) for name in selected],
        font_note="Same portable font inventory as the release audit. Windows-selected fonts are unverified. "
        "Examples cover charset diversity, unusual spacing/rotation and larger discrepancies, plus the two repaired symbol-weight fallbacks. "
        "Inspect placement, clipping, missing symbols and text size; antialiasing alone is not the focus.",
    )


if __name__ == "__main__":
    main()
