"""Fixed-field records, declared as a table. Field order follows MS-EMF 2.3."""

from .constants import RecordType
from .records import define

RECT = ("left", "top", "right", "bottom")
POINT = ("x", "y")
EXTENT = ("cx", "cy")
XFORM = ("m11", "m12", "m21", "m22", "dx", "dy")

# (class name, record type, struct layout, field names)
TABLE = (
    ("SetWindowExtEx", RecordType.SETWINDOWEXTEX, "ii", EXTENT),
    ("SetWindowOrgEx", RecordType.SETWINDOWORGEX, "ii", POINT),
    ("SetViewportExtEx", RecordType.SETVIEWPORTEXTEX, "ii", EXTENT),
    ("SetViewportOrgEx", RecordType.SETVIEWPORTORGEX, "ii", POINT),
    ("SetBrushOrgEx", RecordType.SETBRUSHORGEX, "ii", POINT),
    ("SetPixelV", RecordType.SETPIXELV, "iiI", (*POINT, "color")),
    ("SetMapperFlags", RecordType.SETMAPPERFLAGS, "I", ("flags",)),
    ("SetMapMode", RecordType.SETMAPMODE, "I", ("mode",)),
    ("SetBkMode", RecordType.SETBKMODE, "I", ("mode",)),
    ("SetPolyFillMode", RecordType.SETPOLYFILLMODE, "I", ("mode",)),
    ("SetROP2", RecordType.SETROP2, "I", ("mode",)),
    ("SetStretchBltMode", RecordType.SETSTRETCHBLTMODE, "I", ("mode",)),
    ("SetTextAlign", RecordType.SETTEXTALIGN, "I", ("alignment",)),
    (
        "SetColorAdjustment",
        RecordType.SETCOLORADJUSTMENT,
        "8H4h",
        (
            "size",
            "values",
            "illuminant_index",
            "red_gamma",
            "green_gamma",
            "blue_gamma",
            "reference_black",
            "reference_white",
            "contrast",
            "brightness",
            "colorfulness",
            "red_green_tint",
        ),
    ),
    ("SetTextColor", RecordType.SETTEXTCOLOR, "I", ("color",)),
    ("SetBkColor", RecordType.SETBKCOLOR, "I", ("color",)),
    ("OffsetClipRgn", RecordType.OFFSETCLIPRGN, "ii", POINT),
    ("MoveToEx", RecordType.MOVETOEX, "ii", POINT),
    ("SetMetaRgn", RecordType.SETMETARGN, "", ()),
    ("ExcludeClipRect", RecordType.EXCLUDECLIPRECT, "4i", RECT),
    ("IntersectClipRect", RecordType.INTERSECTCLIPRECT, "4i", RECT),
    ("ScaleViewportExtEx", RecordType.SCALEVIEWPORTEXTEX, "4i", ("x_num", "x_denom", "y_num", "y_denom")),
    ("ScaleWindowExtEx", RecordType.SCALEWINDOWEXTEX, "4i", ("x_num", "x_denom", "y_num", "y_denom")),
    ("SaveDC", RecordType.SAVEDC, "", ()),
    ("RestoreDC", RecordType.RESTOREDC, "i", ("saved_dc",)),
    ("SetWorldTransform", RecordType.SETWORLDTRANSFORM, "6f", XFORM),
    ("ModifyWorldTransform", RecordType.MODIFYWORLDTRANSFORM, "6fI", (*XFORM, "mode")),
    ("SelectObject", RecordType.SELECTOBJECT, "I", ("object_index",)),
    ("CreatePen", RecordType.CREATEPEN, "IIiiI", ("object_index", "style", "width", "width_y", "color")),
    ("CreateBrushIndirect", RecordType.CREATEBRUSHINDIRECT, "IIII", ("object_index", "style", "color", "hatch")),
    ("DeleteObject", RecordType.DELETEOBJECT, "I", ("object_index",)),
    ("AngleArc", RecordType.ANGLEARC, "iiIff", (*POINT, "radius", "start_angle", "sweep_angle")),
    ("Ellipse", RecordType.ELLIPSE, "4i", RECT),
    ("Rectangle", RecordType.RECTANGLE, "4i", RECT),
    ("RoundRect", RecordType.ROUNDRECT, "6i", (*RECT, "corner_width", "corner_height")),
    ("Arc", RecordType.ARC, "8i", (*RECT, "start_x", "start_y", "end_x", "end_y")),
    ("Chord", RecordType.CHORD, "8i", (*RECT, "start_x", "start_y", "end_x", "end_y")),
    ("Pie", RecordType.PIE, "8i", (*RECT, "start_x", "start_y", "end_x", "end_y")),
    ("SelectPalette", RecordType.SELECTPALETTE, "I", ("object_index",)),
    ("ResizePalette", RecordType.RESIZEPALETTE, "II", ("object_index", "count")),
    ("RealizePalette", RecordType.REALIZEPALETTE, "", ()),
    ("ExtFloodFill", RecordType.EXTFLOODFILL, "iiII", (*POINT, "color", "mode")),
    ("LineTo", RecordType.LINETO, "ii", POINT),
    ("ArcTo", RecordType.ARCTO, "8i", (*RECT, "start_x", "start_y", "end_x", "end_y")),
    ("SetArcDirection", RecordType.SETARCDIRECTION, "I", ("direction",)),
    ("SetMiterLimit", RecordType.SETMITERLIMIT, "I", ("limit",)),
    ("BeginPath", RecordType.BEGINPATH, "", ()),
    ("EndPath", RecordType.ENDPATH, "", ()),
    ("CloseFigure", RecordType.CLOSEFIGURE, "", ()),
    ("FillPath", RecordType.FILLPATH, "4i", RECT),
    ("StrokeAndFillPath", RecordType.STROKEANDFILLPATH, "4i", RECT),
    ("StrokePath", RecordType.STROKEPATH, "4i", RECT),
    ("FlattenPath", RecordType.FLATTENPATH, "", ()),
    ("WidenPath", RecordType.WIDENPATH, "", ()),
    ("SelectClipPath", RecordType.SELECTCLIPPATH, "I", ("mode",)),
    ("AbortPath", RecordType.ABORTPATH, "", ()),
    ("SetICMMode", RecordType.SETICMMODE, "I", ("mode",)),
    ("SetColorSpace", RecordType.SETCOLORSPACE, "I", ("object_index",)),
    ("DeleteColorSpace", RecordType.DELETECOLORSPACE, "I", ("object_index",)),
    ("ForceUFIMapping", RecordType.FORCEUFIMAPPING, "II", ("checksum", "index")),
    ("ColorCorrectPalette", RecordType.COLORCORRECTPALETTE, "IIII", ("object_index", "first", "count", "reserved")),
    ("SetLayout", RecordType.SETLAYOUT, "I", ("layout",)),
    ("SetTextJustification", RecordType.SETTEXTJUSTIFICATION, "ii", ("break_extra", "break_count")),
)


for _row in TABLE:
    globals()[_row[0]] = define(__name__, *_row)

__all__ = [row[0] for row in TABLE]
