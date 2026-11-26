from io import BytesIO

import pytest
from PIL import Image

from pillow_wmf import GDI, InvalidOperation, RasterContext, UnsupportedOperation, render
from pillow_wmf.emf import Metafile, fixed, loader, text
from pillow_wmf.plugin import WmfImageFile

UNIT_FRAME = (0, 0, 3388, 3383)  # 128 reference pixels square.


def drawing(frame=UNIT_FRAME):
    return Metafile.build([fixed.Rectangle(10, 10, 40, 30)], frame=frame).to_bytes()


def test_loader_identifies_and_places_emf():
    data = drawing()
    assert loader.accepts(data[:16]) and loader.accepts(data[:44])
    assert not loader.accepts(data[:40] + b"WMF ")
    placement = loader.placement(data[: loader.HEADER_BYTES])
    assert placement.bounds == UNIT_FRAME
    assert placement.units_per_inch == 2540
    assert placement.size == (128, 128)


def test_render_fits_the_frame_to_the_canvas():
    one = render(drawing(), (128, 128))
    # GM_ADVANCED rectangles include their lower-right device edges.
    assert one.getpixel((40, 20)) == (0, 0, 0)
    assert one.getpixel((41, 20)) == (255, 255, 255)
    double = render(drawing(), (256, 256))
    assert double.getpixel((80, 40)) == (0, 0, 0)


def test_pillow_opens_and_sizes_emf():
    with Image.open(BytesIO(drawing())) as image:
        assert isinstance(image, WmfImageFile)
        assert image.size == (128, 128)
        assert image.info["wmf_bbox"] == UNIT_FRAME
        image.load()
        assert image.getpixel((40, 20)) == (0, 0, 0)
    with Image.open(BytesIO(drawing())) as image:
        image.load(dpi=254)  # 3388 x 3383 hundredths of a millimetre.
        assert image.size == (338, 338)


def test_pillow_reports_unrenderable_emf_as_oserror():
    # Text is not yet drawn during EMF playback.
    records = [text.ExtTextOutA((0, 0, 0, 0), 1, 0.0, 0.0, 3, 4, 1, 76, 0, (1, 2, 3, 4), 0, b"a\0\0\0")]
    data = Metafile.build(records, frame=UNIT_FRAME).to_bytes()
    with Image.open(BytesIO(data)) as image, pytest.raises(OSError, match="GM_ADVANCED"):
        image.load()
    with Image.open(BytesIO(drawing(frame=(10, 10, 0, 0)))) as image, pytest.raises(OSError, match="reversed"):
        image.load()


def test_raster_world_transform_contract():
    context = RasterContext(16, 16)
    with pytest.raises(InvalidOperation, match="GM_ADVANCED"):
        context.set_world_transform(2.0, 0.0, 0.0, 2.0, 0.0, 0.0)
    context.set_graphics_mode(2)
    with pytest.raises(InvalidOperation, match="Singular"):
        context.set_world_transform(1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    context.set_world_transform(0.0, 1.0, -1.0, 0.0, 8.0, 0.0)
    assert context.mapping.rotated and context.mapping.device_point(2, 3) == (5, 2)
    # Unmodelled operations are refused under rotation, not drawn unrotated.
    with pytest.raises(UnsupportedOperation, match="GM_ADVANCED|rotating"):
        context.text_out(0, 0, b"x")
    context.set_world_transform(2.0, 0.0, 0.0, 3.0, 1.0, 0.5)
    assert context.mapping.world == (2.0, 0.0, 0.0, 3.0, 1.0, 0.5)
    assert context.mapping.device_point(2, 2) == (5, 7)
    with pytest.raises(InvalidOperation, match="identity"):
        context.set_graphics_mode(1)
    with pytest.raises(UnsupportedOperation, match="not yet verified"):
        context.ext_text_out(0, 0, b"x")
    with pytest.raises(InvalidOperation, match="Graphics mode"):
        context.set_graphics_mode(3)


def test_gdi_vocabulary_names_the_new_calls():
    assert {"set_graphics_mode", "set_world_transform"} <= set(dir(GDI))
