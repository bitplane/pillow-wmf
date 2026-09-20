"""Gallery bookkeeping is exact even when visual review is bounded."""

import runpy
from pathlib import Path

from PIL import Image

from pillow_wmf import Font, FontCollection, Recorder

TOOLS = runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/text-gallery.py"))


def test_gallery_limit_does_not_limit_comparison_or_merge_basenames(tmp_path):
    pairs = []
    for index in range(3):
        directory = tmp_path / str(index)
        directory.mkdir()
        wmf, png = directory / "same.wmf", directory / "same.png"
        wmf.write_bytes(Recorder().to_bytes())
        Image.new("RGB", (7, 5), "black").save(png)
        pairs.append((wmf, png))
    output = tmp_path / "gallery"
    assert TOOLS["gallery"](tmp_path, output, pairs=pairs, limit=2, font_note="Unverified fonts") == (0, 3, 0)
    html = (output / "index.html").read_text()
    assert "1 omitted" in html
    assert "Unverified fonts" in html
    assert "--width:7px" in html
    assert len(list(output.glob("*-ours.png"))) == 2


def test_corpus_text_filter_keeps_blocked_separate(tmp_path):
    source, refs = tmp_path / "source", tmp_path / "refs"
    source.mkdir()
    refs.mkdir()
    for name, text in (("blank", False), ("text", True)):
        recorder = Recorder()
        if text:
            recorder.text_out(0, 0, b"A")
        (source / f"{name}.wmf").write_bytes(recorder.to_bytes())
        Image.new("RGB", (7, 5), "white").save(refs / f"{name}.png")
    output = tmp_path / "gallery"
    pairs = TOOLS["corpus_pairs"](source, refs)
    assert TOOLS["gallery"](source, output, pairs=pairs, text_only=True) == (0, 0, 1)
    assert "Default font resolution" in (output / "index.html").read_text()


def test_gallery_uses_supplied_font_policy(tmp_path):
    recorder = Recorder()
    recorder.select_object(recorder.create_font(Font(face_name=b"Symbol", height=-16, charset=0)))
    recorder.text_out(0, 0, b"A")
    (tmp_path / "symbol.wmf").write_bytes(recorder.to_bytes())
    Image.new("RGB", (32, 32), "white").save(tmp_path / "symbol.png")
    fonts = FontCollection(symbol_fallback=True)
    assert TOOLS["gallery"](tmp_path, tmp_path / "gallery", fonts=fonts) == (0, 1, 0)
