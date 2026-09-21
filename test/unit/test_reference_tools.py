import ctypes
import importlib
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from pillow_wmf import Font, Recorder

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def test_reference_comparison_preserves_dc_state_and_surface_clipping(tmp_path):
    # Hand-specified tool regression, not a generated Windows oracle.
    recorder = Recorder()
    recorder.set_window_extent(1, 1)
    recorder.set_viewport_extent(2, 2)
    recorder.set_viewport_origin(-1, -1)
    recorder.intersect_clip_rect(1, 1, 2, 2)
    recorder.select_object(recorder.create_brush(0, 0x332211, 0))
    recorder.pat_blt(-10, -10, 20, 20, 0xF00021)
    path = tmp_path / "state.wmf"
    png = tmp_path / "reference.png"
    path.write_bytes(recorder.to_bytes())
    expected = Image.new("RGB", (4, 4), "white")
    expected.paste((17, 34, 51), (1, 1, 3, 3))
    expected.save(png)
    compare = runpy.run_path(str(SCRIPTS / "reference_compare.py"))["compare_reference"]
    assert compare(path, png).differing_pixels == 0
    # A single channel differing by one must still fail exact comparison.
    expected.putpixel((1, 1), (18, 34, 51))
    expected.save(png)
    result = compare(path, png)
    assert result.pixels == 16
    assert result.differing_pixels == result.differing_channels == result.largest_error == 1
    assert result.first == (1, 1, (17, 34, 51), (18, 34, 51))


def test_diagnostics_fail_on_differences_without_writing_references(monkeypatch, tmp_path, capsys):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    main = runpy.run_path(str(SCRIPTS / "reference_compare.py"))["main"]
    path = tmp_path / "empty.wmf"
    path.write_bytes(Recorder().to_bytes())
    profile = tmp_path / "2x2"
    profile.mkdir()
    png = profile / "empty.png"
    expected = Image.new("RGB", (2, 2), "white")
    expected.save(png)
    assert main([str(tmp_path)]) == 0
    expected.putpixel((0, 0), (254, 255, 255))
    expected.save(png)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert main([str(tmp_path)]) == 1
    assert "1/4 pixels differ" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_full_generator_check_validates_round_trips_and_normalization(monkeypatch, load_script):
    check = load_script("generate-wmf-fixtures.py")["check_cases"]

    def cases():
        recorder = Recorder()
        recorder.select_object(recorder.create_font(Font(charset=254)))
        recorder.set_pixel(1, 2, 255)
        yield "small", recorder

    monkeypatch.setitem(check.__globals__, "all_cases", cases)
    monkeypatch.setitem(check.__globals__, "LOCAL_CASES", {"small"})
    assert check() == 1


def test_full_generator_check_rejects_nondeterminism(monkeypatch, load_script):
    check = load_script("generate-wmf-fixtures.py")["check_cases"]
    counter = iter(range(2))

    def cases():
        recorder = Recorder()
        recorder.set_pixel(0, 0, next(counter))
        yield "unstable", recorder

    monkeypatch.setitem(check.__globals__, "all_cases", cases)
    monkeypatch.setitem(check.__globals__, "LOCAL_CASES", set())
    with pytest.raises(ValueError, match="Non-reproducible fixture: unstable"):
        check()


def test_updater_only_renders_missing_pngs(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    calls = []
    installed = []

    @contextmanager
    def private_fonts(paths):
        installed.extend(paths)
        try:
            yield
        finally:
            installed.clear()

    class Output:
        def save(self, path, *, format):
            assert format == "PNG"
            path.write_bytes(b"new-reference")

    def render(source, width, height):
        assert [path.name for path in installed] == [
            "cp932.ttf",
            "dbcs.ttf",
            "encoding.ttf",
            "environment.ttf",
            "layout.ttf",
            "symbols.ttf",
            "utf8.ttf",
        ]
        calls.append((source, width, height))
        return Output()

    monkeypatch.setitem(
        sys.modules, "windows_wmf_render", SimpleNamespace(render_wmf=render, private_fonts=private_fonts)
    )
    script = runpy.run_path(str(SCRIPTS / "update-goldens.py"))
    main = script["main"]
    monkeypatch.setitem(main.__globals__, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(main.__globals__, "FIXTURES", tmp_path)
    (tmp_path / "existing.wmf").write_bytes(b"changed-input")
    profile = tmp_path / "128x128"
    profile.mkdir()
    (profile / "existing.png").write_bytes(b"leave-this-alone")
    (tmp_path / "missing.wmf").write_bytes(b"new-input")
    assert main([]) == 0
    assert calls == [(b"new-input", 128, 128)]
    assert (profile / "existing.png").read_bytes() == b"leave-this-alone"
    assert (profile / "missing.png").read_bytes() == b"new-reference"
    assert main([]) == 0
    assert len(calls) == 1
    assert sorted(path.suffix for path in tmp_path.rglob("*") if path.is_file()) == [".png", ".png", ".wmf", ".wmf"]
    assert main(["--size", "257x193"]) == 0
    assert calls[1:] == [(b"changed-input", 257, 193), (b"new-input", 257, 193)]
    assert (tmp_path / "257x193/existing.png").read_bytes() == b"new-reference"
    assert (profile / "existing.png").read_bytes() == b"leave-this-alone"
    assert main([]) == 0
    assert len(calls) == 3


def test_explicit_pair_uses_png_dimensions_not_directory_label(tmp_path):
    source = tmp_path / "input.wmf"
    recorder = Recorder()
    recorder.select_object(recorder.create_brush(0, 0x332211, 0))
    recorder.pat_blt(0, 0, 20, 20, 0xF00021)
    source.write_bytes(recorder.to_bytes())
    png = tmp_path / "different-name.png"
    Image.new("RGB", (7, 3), (17, 34, 51)).save(png)
    compare = runpy.run_path(str(SCRIPTS / "reference_compare.py"))["compare_reference"]
    result = compare(source, png)
    assert result.pixels == 7 * 3
    assert result.differing_pixels == 0


def test_discovery_requires_each_input_at_each_active_size(tmp_path):
    discover = runpy.run_path(str(SCRIPTS / "reference_cases.py"))["discover_pairs"]
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "one.wmf").touch()
    (corpus / "128x128").mkdir()
    (corpus / "128x128/one.png").touch()
    (corpus / "two.WMF").touch()
    (corpus / "257x193").mkdir()
    (corpus / "257x193/one.png").touch()
    pairs = discover(tmp_path)
    assert {(a.name, b.relative_to(corpus).as_posix()) for a, b in pairs} == {
        ("one.wmf", "128x128/one.png"),
        ("two.WMF", "128x128/two.png"),
        ("one.wmf", "257x193/one.png"),
        ("two.WMF", "257x193/two.png"),
    }
    (corpus / "257x193/orphan.png").touch()
    with pytest.raises(ValueError, match="without a matching WMF"):
        discover(tmp_path)


def test_discovery_supports_only_sized_profiles(tmp_path):
    discover = runpy.run_path(str(SCRIPTS / "reference_cases.py"))["discover_pairs"]
    (tmp_path / "one.wmf").touch()
    for size in ("128x128", "257x193"):
        (tmp_path / size).mkdir()
    assert [p.relative_to(tmp_path).as_posix() for _, p in discover(tmp_path)] == [
        "128x128/one.png",
        "257x193/one.png",
    ]


def test_discovery_requires_explicit_initial_profile(tmp_path):
    tools = runpy.run_path(str(SCRIPTS / "reference_cases.py"))
    source = tmp_path / "one.wmf"
    source.touch()
    with pytest.raises(ValueError, match="No size profiles"):
        tools["discover_pairs"](tmp_path)
    assert list(tools["reference_cases"](tmp_path, (17, 23))) == [
        (source, tmp_path / "17x23/one.png", (17, 23)),
    ]


def test_discovery_rejects_adjacent_pngs(tmp_path):
    discover = runpy.run_path(str(SCRIPTS / "reference_cases.py"))["discover_pairs"]
    (tmp_path / "one.wmf").touch()
    (tmp_path / "one.png").touch()
    (tmp_path / "128x128").mkdir()
    with pytest.raises(ValueError, match="without a matching WMF"):
        discover(tmp_path)


def test_discovery_rejects_ambiguous_input_names(tmp_path):
    discover = runpy.run_path(str(SCRIPTS / "reference_cases.py"))["discover_pairs"]
    (tmp_path / "one.wmf").touch()
    (tmp_path / "one.WMF").touch()
    with pytest.raises(ValueError, match="Ambiguous"):
        discover(tmp_path)


def test_comparison_cli_checks_multiple_roots_and_reports_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    main = runpy.run_path(str(SCRIPTS / "reference_compare.py"))["main"]
    roots = [tmp_path / "first", tmp_path / "second"]
    for root in roots:
        root.mkdir()
        (root / "7x3").mkdir()
        (root / "blank.wmf").write_bytes(Recorder().to_bytes())
    Image.new("RGB", (7, 3), "white").save(roots[1] / "7x3/blank.png")
    assert main([str(root) for root in roots]) == 1
    output = capsys.readouterr().out
    assert "FileNotFoundError" in output
    assert "0/21 pixels differ" in output
    Image.new("RGB", (7, 3), "white").save(roots[0] / "7x3/blank.png")
    assert main([str(root) for root in roots]) == 0


def test_size_preflight_is_linux_safe_and_records_missing(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    script = runpy.run_path(str(SCRIPTS / "update-goldens.py"))
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "input.wmf").touch()
    (root / "128x128").mkdir()
    (root / "128x128/input.png").touch()
    output = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    assert script["main"](["--root", str(root), "--size", "257x193", "--check"]) == 0
    assert output.read_text() == "missing=true\n"
    assert not (root / "257x193").exists()
    assert script["main"](["--root", str(root), "--check"]) == 0
    assert output.read_text().endswith("missing=false\n")


@pytest.mark.parametrize("value", ("0x193", "257x0", "-1x2", "257", "../../tmp", "1x2x3"))
def test_invalid_reference_size(value):
    import argparse

    parse = runpy.run_path(str(SCRIPTS / "reference_cases.py"))["image_size"]
    with pytest.raises(argparse.ArgumentTypeError):
        parse(value)


def test_native_profile_rejects_environment_drift(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    probe = runpy.run_path(str(SCRIPTS / "probe-windows-mapping.py"))
    caps = {name: value for name, (_, value) in probe["REFERENCE_DEVICE_CAPS"].items()}
    probe["validate_device_caps"](caps)
    for name, value in caps.items():
        with pytest.raises(RuntimeError, match="Reference device changed"):
            probe["validate_device_caps"]({**caps, name: value + 1})


@pytest.mark.parametrize(
    "failure", [None, "CreateCompatibleDC", "CreateDIBSection", "SetMapMode", "PlayMetaFile", "GdiFlush"]
)
@pytest.mark.parametrize("placeable", (False, True))
def test_native_surface_cleanup(monkeypatch, failure, placeable):
    """Check Python ownership/error paths, not native rendering semantics."""
    monkeypatch.syspath_prepend(str(SCRIPTS))
    renderer = importlib.import_module("windows_wmf_render")
    calls = []
    memory = ctypes.create_string_buffer(2 * 3 * 4)

    class FakeGDI:
        def __getattr__(self, name):
            def function(*args):
                calls.append((name, args))
                if name == failure:
                    return 0
                if name == "CreateDIBSection":
                    args[3]._obj.value = ctypes.addressof(memory)
                    return 2
                if name == "SelectObject":
                    return 3
                return 1

            setattr(self, name, function)
            return function

    monkeypatch.setattr(renderer, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: FakeGDI(), raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", lambda: 123, raising=False)
    source = (bytes.fromhex("d7cdc69a") + bytes(18) if placeable else b"") + b"fake-metafile"
    if failure:
        with pytest.raises(OSError, match=failure):
            renderer.render_wmf(source, 2, 3)
    else:
        image = renderer.render_wmf(source, 2, 3)
        assert image.size == (2, 3)
        assert image.tobytes() == b"\xff" * 18
        for name, args in calls:
            if name in ("SetWindowExtEx", "SetViewportExtEx"):
                assert args[1:3] == (2, 3)
            if name == "SetMetaFileBitsEx":
                assert args[0] == len(b"fake-metafile")
    names = [name for name, _ in calls]
    assert names.count("DeleteDC") == (failure != "CreateCompatibleDC")
    assert names.count("DeleteObject") == (failure not in {"CreateCompatibleDC", "CreateDIBSection"})
    assert names.count("DeleteMetaFile") == (failure in {None, "PlayMetaFile", "GdiFlush"})
    if failure not in {"CreateCompatibleDC", "CreateDIBSection"}:
        assert calls[names.index("DeleteObject") - 1] == ("SelectObject", (1, 3))
