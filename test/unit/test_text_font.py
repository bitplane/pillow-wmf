"""The oracle and local experiments must use the same controlled font."""

from io import BytesIO

from fontTools.ttLib import TTFont
from PIL import ImageFont

from pillow_wmf import Metafile, TraceContext, play


def test_committed_font_is_reproducible_and_loadable(load_script):
    factory = load_script("test_font.py")
    data = factory["font_bytes"]()
    assert data == factory["font_bytes"]() == factory["FONT_PATH"].read_bytes()
    font = ImageFont.truetype(BytesIO(data), 40)
    assert font.getname() == (factory["FAMILY"], "Regular")
    assert font.getlength("A B") == 54


def test_font_metrics_distinguish_layout_from_ink_bounds(load_script):
    factory = load_script("test_font.py")
    with TTFont(BytesIO(factory["font_bytes"]())) as font:
        assert font.getBestCmap() == {32: "space", 65: "A", 66: "B"}
        assert font["head"].unitsPerEm == 1000
        assert (font["OS/2"].usWinAscent, font["OS/2"].usWinDescent) == (900, 300)
        assert font["hmtx"]["B"] == (450, -50)
        assert font["glyf"]["B"].yMin == -200
        assert not font["glyf"]["A"].program.getBytecode()


def test_text_probe_uses_roundtrippable_wmfs_and_the_controlled_font(load_script):
    factory = load_script("text_probe_cases.py")
    probes = list(factory["cases"]())
    assert len(probes) == 5
    for _, recorder in probes:
        source = recorder.to_bytes()
        metafile = Metafile.from_bytes(source)
        assert metafile.to_bytes() == source
        context = TraceContext()
        assert play(metafile, context, strict=True) == ()
        font = next(call.kwargs["font"] for call in context.calls if call.name == "create_font")
        assert font.face_name.rstrip(b"\0") == b"Pillow WMF Test"
        assert font.quality == 3  # NONANTIALIASED_QUALITY
        assert sum(call.name in {"text_out", "ext_text_out"} for call in context.calls) == 4
