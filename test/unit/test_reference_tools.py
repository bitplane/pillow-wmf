import ctypes
import importlib
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pillow_wmf import Metafile, TraceContext, play

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def test_foundation_inputs_are_unique_reproducible_and_lossless():
    cases = runpy.run_path(str(SCRIPTS / "generate-wmf-fixtures.py"))["cases"]
    first = list(cases())
    second = list(cases())
    names = [name for name, _ in first]
    assert len(names) == len(set(names))
    assert {"coords-inherited", "pen-width-0-scale-x", "drawing-ellipse-odd", "state-clip-offset-vector"} <= set(names)
    for (name, recorder), (again, repeated) in zip(first, second, strict=True):
        source = recorder.to_bytes()
        assert name == again
        assert source == repeated.to_bytes() == (ROOT / "test/compatibility/wmf" / f"{name}.wmf").read_bytes()
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        trace = TraceContext()
        assert play(metafile, trace, strict=True) == ()
        assert trace.calls == recorder.calls


def test_updater_only_renders_missing_pngs(monkeypatch, tmp_path):
    calls = []

    class Output:
        def save(self, path, *, format):
            assert format == "PNG"
            path.write_bytes(b"new-reference")

    def render(source, width, height):
        calls.append((source, width, height))
        return Output()

    monkeypatch.setitem(sys.modules, "windows_wmf_render", SimpleNamespace(render_wmf=render))
    script = runpy.run_path(str(SCRIPTS / "update-goldens.py"))
    main = script["main"]
    monkeypatch.setitem(main.__globals__, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(main.__globals__, "FIXTURES", tmp_path)
    (tmp_path / "existing.wmf").write_bytes(b"changed-input")
    (tmp_path / "existing.png").write_bytes(b"leave-this-alone")
    (tmp_path / "missing.wmf").write_bytes(b"new-input")
    assert main() == 0
    assert calls == [(b"new-input", 128, 128)]
    assert (tmp_path / "existing.png").read_bytes() == b"leave-this-alone"
    assert (tmp_path / "missing.png").read_bytes() == b"new-reference"
    assert main() == 0
    assert len(calls) == 1
    assert sorted(path.suffix for path in tmp_path.iterdir()) == [".png", ".png", ".wmf", ".wmf"]


@pytest.mark.parametrize(
    "failure", [None, "CreateCompatibleDC", "CreateDIBSection", "SetMapMode", "PlayMetaFile", "GdiFlush"]
)
def test_native_surface_cleanup(monkeypatch, failure):
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
    if failure:
        with pytest.raises(OSError, match=failure):
            renderer.render_wmf(b"fake-metafile", 2, 3)
    else:
        image = renderer.render_wmf(b"fake-metafile", 2, 3)
        assert image.size == (2, 3)
        assert image.tobytes() == b"\xff" * 18
    names = [name for name, _ in calls]
    assert names.count("DeleteDC") == (failure != "CreateCompatibleDC")
    assert names.count("DeleteObject") == (failure not in {"CreateCompatibleDC", "CreateDIBSection"})
    assert names.count("DeleteMetaFile") == (failure in {None, "PlayMetaFile", "GdiFlush"})
    if failure not in {"CreateCompatibleDC", "CreateDIBSection"}:
        assert calls[names.index("DeleteObject") - 1] == ("SelectObject", (1, 3))
