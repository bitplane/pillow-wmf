import pytest
from PIL import Image

from pillow_wmf import Metafile, Recorder, TraceContext, play
from pillow_wmf.wmf.objects import Font


def test_real_font_cases_are_small_deterministic_and_lossless(load_script):
    cases = load_script("real_text_cases.py")["cases"]
    first = [(name, family, recorder.to_bytes()) for name, family, recorder in cases()]
    assert first == [(name, family, recorder.to_bytes()) for name, family, recorder in cases()]
    assert len(first) == len({name for name, _, _ in first}) == 12
    for _, _, source in first:
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        assert play(metafile, TraceContext(), strict=True) == ()


def test_cached_font_bytes_are_verified_before_use(tmp_path, load_script):
    fetch = load_script("real_text_cases.py")["fetch_fonts"]
    (tmp_path / "NotoSans-Regular.ttf").write_bytes(b"wrong version")
    with pytest.raises(ValueError, match="checksum mismatch"):
        fetch(tmp_path)


def test_layout_probe_records_signed_spacing_and_round_trips(load_script):
    cases = load_script("text_layout_cases.py")["cases"]
    for _, _, recorder in cases():
        source = recorder.to_bytes()
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        trace = TraceContext()
        assert play(metafile, trace, strict=True) == ()
        assert trace.calls == recorder.calls


def test_encoding_probe_inputs_are_lossless_and_fonts_are_reproducible(load_script):
    factory = load_script("text_encoding_cases.py")
    for symbol, filename in ((False, "encoding.ttf"), (True, "symbols.ttf")):
        assert factory["font_bytes"](symbol=symbol) == (factory["FONT_ROOT"] / filename).read_bytes()
    for _, _, _, _, recorder in factory["cases"]():
        source = recorder.to_bytes()
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        trace = TraceContext()
        assert play(metafile, trace, strict=True) == ()
        assert trace.calls == recorder.calls


def test_gallery_omits_exact_cases_keeps_single_channel_differences_and_reports_blocked(tmp_path, load_script):
    gallery = load_script("text-gallery.py")["gallery"]
    source, output = tmp_path / "source", tmp_path / "gallery"
    source.mkdir()
    for name in ("exact", "different", "blocked"):
        recorder = Recorder()
        if name == "blocked":
            recorder.select_object(
                recorder.create_font(Font(height=-12, quality=3, face_name=b"Missing".ljust(32, b"\0")))
            )
            recorder.text_out(0, 0, b"A")
        (source / f"{name}.wmf").write_bytes(recorder.to_bytes())
        image = Image.new("RGB", (3, 2), "white")
        if name == "different":
            image.putpixel((1, 1), (254, 255, 255))
        image.save(source / f"{name}.png")
    before = {p: p.read_bytes() for p in source.iterdir()}
    assert gallery(source, output) == (1, 1, 1)
    assert before == {p: p.read_bytes() for p in source.iterdir()}
    page = (output / "index.html").read_text()
    assert "1 differing pixels" in page
    assert "blocked.wmf" in page
    assert "exact-windows.png" not in page
    assert len(list(output.glob("*.png"))) == 3
    with Image.open(output / "different-difference.png") as image:
        assert image.getpixel((1, 1)) == (255, 0, 100)
        assert image.getpixel((0, 0)) == (255, 255, 255)
