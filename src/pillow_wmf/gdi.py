"""GDI command interface used by recorders, trace sinks and future raster devices.

The interface retains primitive identity and logical coordinates. It does not
claim to implement rasterization or the complete Windows device-context state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ._values import freeze

if TYPE_CHECKING:
    from .wmf.objects import BitmapData, Font, Palette, Region


class UnsupportedOperation(NotImplementedError):
    """A backend does not implement this operation."""


@dataclass(frozen=True)
class Handle:
    serial: int
    kind: str
    owner: object = field(repr=False, compare=False)


@dataclass(frozen=True)
class Call:
    name: str
    arguments: tuple[tuple[str, object], ...] = ()

    @classmethod
    def make(cls, name: str, **arguments):
        return cls(name, tuple(sorted((name, freeze(value)) for name, value in arguments.items())))

    @property
    def kwargs(self) -> dict[str, object]:
        return dict(self.arguments)


class GDI:
    """Override invoke to implement a backend. Arguments are immutable values."""

    def is_null_object(self, handle: Handle) -> bool:
        """Whether a creation produced a native null object rather than a resource.

        Logical handles still identify failed creations for subsequent calls.
        WMF playback uses this result to preserve native file-slot allocation.
        Non-emulating backends may retain the default successful-creation model.
        """
        return False

    def invoke(self, call: Call) -> Handle | int | None:
        raise UnsupportedOperation(call.name)

    def save_dc(self) -> int:
        return self.invoke(Call.make("save_dc"))

    def realize_palette(self) -> None:
        return self.invoke(Call.make("realize_palette"))

    def set_background_mode(self, mode: int) -> None:
        return self.invoke(Call.make("set_background_mode", mode=mode))

    def set_map_mode(self, mode: int) -> None:
        return self.invoke(Call.make("set_map_mode", mode=mode))

    def set_rop2(self, mode: int) -> None:
        return self.invoke(Call.make("set_rop2", mode=mode))

    def set_polygon_fill_mode(self, mode: int) -> None:
        return self.invoke(Call.make("set_polygon_fill_mode", mode=mode))

    def set_stretch_mode(self, mode: int) -> None:
        return self.invoke(Call.make("set_stretch_mode", mode=mode))

    def set_text_character_extra(self, extra: int) -> None:
        return self.invoke(Call.make("set_text_character_extra", extra=extra))

    def restore_dc(self, saved_dc: int) -> None:
        return self.invoke(Call.make("restore_dc", saved_dc=saved_dc))

    def resize_palette(self, count: int) -> None:
        return self.invoke(Call.make("resize_palette", count=count))

    def delete_object(self, handle: Handle) -> None:
        return self.invoke(Call.make("delete_object", handle=handle))

    def select_object(self, handle: Handle | None) -> None:
        return self.invoke(Call.make("select_object", handle=handle))

    def select_palette(self, handle: Handle | None) -> None:
        return self.invoke(Call.make("select_palette", handle=handle))

    def select_clip_region(self, region: Handle | None) -> None:
        return self.invoke(Call.make("select_clip_region", region=region))

    def paint_region(self, region: Handle) -> None:
        return self.invoke(Call.make("paint_region", region=region))

    def invert_region(self, region: Handle) -> None:
        return self.invoke(Call.make("invert_region", region=region))

    def set_text_alignment(self, alignment: int) -> None:
        return self.invoke(Call.make("set_text_alignment", alignment=alignment))

    def set_background_color(self, color: int) -> None:
        return self.invoke(Call.make("set_background_color", color=color))

    def set_text_color(self, color: int) -> None:
        return self.invoke(Call.make("set_text_color", color=color))

    def set_mapper_flags(self, flags: int) -> None:
        return self.invoke(Call.make("set_mapper_flags", flags=flags))

    def line_to(self, x: int, y: int) -> None:
        return self.invoke(Call.make("line_to", x=x, y=y))

    def move_to(self, x: int, y: int) -> None:
        return self.invoke(Call.make("move_to", x=x, y=y))

    def set_window_origin(self, x: int, y: int) -> None:
        return self.invoke(Call.make("set_window_origin", x=x, y=y))

    def set_window_extent(self, x: int, y: int) -> None:
        return self.invoke(Call.make("set_window_extent", x=x, y=y))

    def set_viewport_origin(self, x: int, y: int) -> None:
        return self.invoke(Call.make("set_viewport_origin", x=x, y=y))

    def set_viewport_extent(self, x: int, y: int) -> None:
        return self.invoke(Call.make("set_viewport_extent", x=x, y=y))

    def offset_window_origin(self, x: int, y: int) -> None:
        return self.invoke(Call.make("offset_window_origin", x=x, y=y))

    def offset_viewport_origin(self, x: int, y: int) -> None:
        return self.invoke(Call.make("offset_viewport_origin", x=x, y=y))

    def offset_clip_region(self, x: int, y: int) -> None:
        return self.invoke(Call.make("offset_clip_region", x=x, y=y))

    def scale_window_extent(self, x_numerator: int, x_denominator: int, y_numerator: int, y_denominator: int) -> None:
        return self.invoke(
            Call.make(
                "scale_window_extent",
                y_denominator=y_denominator,
                y_numerator=y_numerator,
                x_denominator=x_denominator,
                x_numerator=x_numerator,
            )
        )

    def scale_viewport_extent(self, x_numerator: int, x_denominator: int, y_numerator: int, y_denominator: int) -> None:
        return self.invoke(
            Call.make(
                "scale_viewport_extent",
                y_denominator=y_denominator,
                y_numerator=y_numerator,
                x_denominator=x_denominator,
                x_numerator=x_numerator,
            )
        )

    def exclude_clip_rect(self, left: int, top: int, right: int, bottom: int) -> None:
        return self.invoke(Call.make("exclude_clip_rect", left=left, top=top, right=right, bottom=bottom))

    def intersect_clip_rect(self, left: int, top: int, right: int, bottom: int) -> None:
        return self.invoke(Call.make("intersect_clip_rect", left=left, top=top, right=right, bottom=bottom))

    def rectangle(self, left: int, top: int, right: int, bottom: int) -> None:
        return self.invoke(Call.make("rectangle", left=left, top=top, right=right, bottom=bottom))

    def ellipse(self, left: int, top: int, right: int, bottom: int) -> None:
        return self.invoke(Call.make("ellipse", left=left, top=top, right=right, bottom=bottom))

    def arc(
        self, left: int, top: int, right: int, bottom: int, start_x: int, start_y: int, end_x: int, end_y: int
    ) -> None:
        return self.invoke(
            Call.make(
                "arc",
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                end_y=end_y,
                end_x=end_x,
                start_y=start_y,
                start_x=start_x,
            )
        )

    def chord(
        self, left: int, top: int, right: int, bottom: int, start_x: int, start_y: int, end_x: int, end_y: int
    ) -> None:
        return self.invoke(
            Call.make(
                "chord",
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                end_y=end_y,
                end_x=end_x,
                start_y=start_y,
                start_x=start_x,
            )
        )

    def pie(
        self, left: int, top: int, right: int, bottom: int, start_x: int, start_y: int, end_x: int, end_y: int
    ) -> None:
        return self.invoke(
            Call.make(
                "pie",
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                end_y=end_y,
                end_x=end_x,
                start_y=start_y,
                start_x=start_x,
            )
        )

    def round_rect(self, left: int, top: int, right: int, bottom: int, ellipse_width: int, ellipse_height: int) -> None:
        return self.invoke(
            Call.make(
                "round_rect",
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                ellipse_height=ellipse_height,
                ellipse_width=ellipse_width,
            )
        )

    def set_pixel(self, x: int, y: int, color: int) -> None:
        return self.invoke(Call.make("set_pixel", x=x, y=y, color=color))

    def flood_fill(self, x: int, y: int, color: int) -> None:
        return self.invoke(Call.make("flood_fill", x=x, y=y, color=color))

    def ext_flood_fill(self, x: int, y: int, color: int, mode: int) -> None:
        return self.invoke(Call.make("ext_flood_fill", x=x, y=y, mode=mode, color=color))

    def pat_blt(self, x: int, y: int, width: int, height: int, rop: int) -> None:
        return self.invoke(Call.make("pat_blt", x=x, y=y, rop=rop, height=height, width=width))

    def fill_region(self, region: Handle, brush: Handle) -> None:
        return self.invoke(Call.make("fill_region", region=region, brush=brush))

    def frame_region(self, region: Handle, brush: Handle, width: int, height: int) -> None:
        return self.invoke(Call.make("frame_region", region=region, brush=brush, height=height, width=width))

    def set_text_justification(self, break_count: int, break_extra: int) -> None:
        return self.invoke(Call.make("set_text_justification", break_count=break_count, break_extra=break_extra))

    def set_layout(self, layout: int) -> None:
        return self.invoke(Call.make("set_layout", layout=layout))

    def create_pen(self, style: int, width: int, color: int) -> Handle:
        return self.invoke(Call.make("create_pen", style=style, width=width, color=color))

    def create_brush(self, style: int, color: int, hatch: int) -> Handle:
        return self.invoke(Call.make("create_brush", style=style, color=color, hatch=hatch))

    def polyline(self, points: tuple[tuple[int, int], ...]) -> None:
        return self.invoke(Call.make("polyline", points=points))

    def polygon(self, points: tuple[tuple[int, int], ...]) -> None:
        return self.invoke(Call.make("polygon", points=points))

    def poly_polygon(self, polygons: tuple[tuple[tuple[int, int], ...], ...]) -> None:
        return self.invoke(Call.make("poly_polygon", polygons=polygons))

    def text_out(self, x: int, y: int, text: bytes) -> None:
        return self.invoke(Call.make("text_out", x=x, y=y, text=text))

    def ext_text_out(
        self,
        x: int,
        y: int,
        text: bytes,
        options: int = 0,
        rectangle: tuple[int, int, int, int] | None = None,
        advances: tuple[int, ...] = (),
    ) -> None:
        return self.invoke(
            Call.make("ext_text_out", x=x, y=y, text=text, options=options, rectangle=rectangle, advances=advances)
        )

    def create_font(self, font: Font) -> Handle:
        return self.invoke(Call.make("create_font", font=font))

    def create_palette(self, palette: Palette) -> Handle:
        return self.invoke(Call.make("create_palette", palette=palette))

    def animate_palette(self, palette: Palette) -> None:
        return self.invoke(Call.make("animate_palette", palette=palette))

    def set_palette_entries(self, palette: Palette) -> None:
        return self.invoke(Call.make("set_palette_entries", palette=palette))

    def create_region(self, region: Region) -> Handle:
        return self.invoke(Call.make("create_region", region=region))

    def create_pattern_brush(self, bitmap: BitmapData) -> Handle:
        return self.invoke(Call.make("create_pattern_brush", bitmap=bitmap))

    def create_dib_pattern_brush(self, style: int, color_usage: int, bitmap: BitmapData) -> Handle:
        return self.invoke(Call.make("create_dib_pattern_brush", style=style, color_usage=color_usage, bitmap=bitmap))

    def escape(self, escape_function: int, data: bytes = b"") -> None:
        return self.invoke(Call.make("escape", escape_function=escape_function, data=data))

    def bit_blt(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        rop: int,
        source: BitmapData | None = None,
    ) -> None:
        return self.invoke(
            Call.make("bit_blt", x=x, y=y, width=width, height=height, src_x=src_x, src_y=src_y, rop=rop, source=source)
        )

    def dib_bit_blt(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        rop: int,
        source: BitmapData | None = None,
    ) -> None:
        return self.invoke(
            Call.make(
                "dib_bit_blt", x=x, y=y, width=width, height=height, src_x=src_x, src_y=src_y, rop=rop, source=source
            )
        )

    def stretch_blt(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        src_width: int,
        src_height: int,
        rop: int,
        source: BitmapData | None = None,
    ) -> None:
        return self.invoke(
            Call.make(
                "stretch_blt",
                x=x,
                y=y,
                width=width,
                height=height,
                src_x=src_x,
                src_y=src_y,
                src_width=src_width,
                src_height=src_height,
                rop=rop,
                source=source,
            )
        )

    def dib_stretch_blt(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        src_width: int,
        src_height: int,
        rop: int,
        source: BitmapData | None = None,
    ) -> None:
        return self.invoke(
            Call.make(
                "dib_stretch_blt",
                x=x,
                y=y,
                width=width,
                height=height,
                src_x=src_x,
                src_y=src_y,
                src_width=src_width,
                src_height=src_height,
                rop=rop,
                source=source,
            )
        )

    def set_dib_to_device(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        start_scan: int,
        scan_count: int,
        color_usage: int,
        source: BitmapData,
    ) -> None:
        """Transfer a band from a complete packed DIB (the WMF buffer contract)."""
        return self.invoke(
            Call.make(
                "set_dib_to_device",
                x=x,
                y=y,
                width=width,
                height=height,
                src_x=src_x,
                src_y=src_y,
                start_scan=start_scan,
                scan_count=scan_count,
                color_usage=color_usage,
                source=source,
            )
        )

    def stretch_dib(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        src_x: int,
        src_y: int,
        src_width: int,
        src_height: int,
        rop: int,
        color_usage: int,
        source: BitmapData,
    ) -> None:
        return self.invoke(
            Call.make(
                "stretch_dib",
                x=x,
                y=y,
                width=width,
                height=height,
                src_x=src_x,
                src_y=src_y,
                src_width=src_width,
                src_height=src_height,
                rop=rop,
                color_usage=color_usage,
                source=source,
            )
        )


OPERATION_NAMES = frozenset(
    {
        "save_dc",
        "realize_palette",
        "set_background_mode",
        "set_map_mode",
        "set_rop2",
        "set_polygon_fill_mode",
        "set_stretch_mode",
        "set_text_character_extra",
        "restore_dc",
        "resize_palette",
        "delete_object",
        "select_object",
        "select_palette",
        "select_clip_region",
        "paint_region",
        "invert_region",
        "set_text_alignment",
        "set_background_color",
        "set_text_color",
        "set_mapper_flags",
        "line_to",
        "move_to",
        "set_window_origin",
        "set_window_extent",
        "set_viewport_origin",
        "set_viewport_extent",
        "offset_window_origin",
        "offset_viewport_origin",
        "offset_clip_region",
        "scale_window_extent",
        "scale_viewport_extent",
        "exclude_clip_rect",
        "intersect_clip_rect",
        "rectangle",
        "ellipse",
        "arc",
        "chord",
        "pie",
        "round_rect",
        "set_pixel",
        "flood_fill",
        "ext_flood_fill",
        "pat_blt",
        "fill_region",
        "frame_region",
        "set_text_justification",
        "set_layout",
        "create_pen",
        "create_brush",
        "polyline",
        "polygon",
        "poly_polygon",
        "text_out",
        "ext_text_out",
        "create_font",
        "create_palette",
        "animate_palette",
        "set_palette_entries",
        "create_region",
        "create_pattern_brush",
        "create_dib_pattern_brush",
        "escape",
        "bit_blt",
        "dib_bit_blt",
        "stretch_blt",
        "dib_stretch_blt",
        "set_dib_to_device",
        "stretch_dib",
    }
)
