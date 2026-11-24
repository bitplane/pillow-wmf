"""Device pixels, separate from the drawing state of the contexts that paint them."""

from PIL import Image

from .bitmap import RGBBitmap


class Surface:
    """One RGB canvas, shared by every context that draws on it.

    Clipping, mapping and raster operations are drawing state and stay with
    the painting context; the surface only knows its own bounds. ``image`` is
    the live canvas rather than a copy.
    """

    def __init__(self, width: int, height: int, background=(255, 255, 255)):
        if width <= 0 or height <= 0:
            raise ValueError("Image dimensions must be positive")
        self.image = Image.new("RGB", (width, height), background)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def pixels(self):
        """Per-pixel access for one operation; callers keep within bounds."""
        return self.image.load()

    def fill_span(self, y: int, start: int, end: int, color: tuple[int, int, int]) -> None:
        """Set the half-open row run ``[start, end)`` to one colour, within bounds."""
        self.image.paste(color, (start, y, end, y + 1))

    def snapshot(self) -> RGBBitmap:
        """Immutable copy, for transfers that read the canvas they paint."""
        return RGBBitmap(self.width, self.height, self.image.tobytes())
