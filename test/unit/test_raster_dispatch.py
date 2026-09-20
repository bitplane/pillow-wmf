"""Operation coverage is owned by handlers, not a second accepted-name list."""

from pillow_wmf import RasterContext
from pillow_wmf.gdi import OPERATION_NAMES


def test_raster_handlers_cover_the_gdi_interface():
    handlers = {name.removeprefix("_apply_") for name in vars(RasterContext) if name.startswith("_apply_")}
    assert handlers == OPERATION_NAMES
