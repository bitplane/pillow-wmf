"""GradientFill. Expected pixels were read back from native fills on a 32-bit DIB."""

from pillow_wmf.binary import Limits
from pillow_wmf.emf import variable
from pillow_wmf.emf.file import Metafile
from pillow_wmf.emf.records import decode_record
from pillow_wmf.raster import RasterContext

COLOURS = ((0xF000, 0x1000, 0x2000), (0x0800, 0xE000, 0x4000), (0x3000, 0x2400, 0xF0F0))


def filled(mode, points, meshes):
    context = RasterContext(64, 64, background=(255, 255, 255), trace_calls=False)
    context.gradient_fill(mode, [(x, y, *COLOURS[i], 0) for i, (x, y) in enumerate(points)], meshes)
    return context.image.convert("RGB")


def test_rectangles_step_from_the_left_corner_whichever_comes_first():
    image = filled(0, ((50, 30), (5, 7)), ((0, 1),))
    assert [image.getpixel((x, 7)) for x in (5, 6, 27, 49)] == [
        (8, 224, 64),
        (13, 219, 63),
        (121, 122, 48),
        (234, 20, 32),
    ]
    assert image.getpixel((50, 7)) == image.getpixel((5, 30)) == (255, 255, 255)


def test_triangle_rows_span_ceiling_edges_and_colours_round_to_16_bits():
    image = filled(2, ((10, 5), (40, 20), (10, 50)), ((0, 1, 2),))

    def run(y):
        xs = [x for x in range(64) if image.getpixel((x, y)) != (255, 255, 255)]
        return (xs[0], xs[-1] + 1) if xs else None

    # The top row is empty here, the bottom row is never drawn, and an edge
    # crossing a whole column at row 20 includes it on the left only.
    assert [run(y) for y in (5, 6, 19, 20, 21, 49, 50)] == [
        None,
        (10, 12),
        (10, 38),
        (10, 40),
        (10, 39),
        (10, 11),
        None,
    ]
    # Blue is 95.999 and 127.997 of 255 exactly: the 16-bit value rounds up.
    assert image.getpixel((33, 25)) == (25, 179, 96)
    assert image.getpixel((26, 30)) == (43, 134, 128)


NATIVE_TWO_RECTANGLES = bytes.fromhex(
    "0100000002000000270000001d000000040000000200000000000000"
    "010000000200000000ff0000000000001e00000014000000000000ff0000000005000000"
    "190000000000000000ff0000280000001e00000000800080008000000000000001000000"
    "02000000030000000000000000000000"
)


def test_rectangle_records_reserve_a_triangle_sized_mesh():
    record = decode_record(118, NATIVE_TWO_RECTANGLES, Limits())
    assert isinstance(record, variable.GradientFill)
    assert record.shapes == ((0, 1), (2, 3)) and record.padding is None
    assert variable.GradientFill(record.bounds, 0, record.vertices, record.shapes).body() == NATIVE_TWO_RECTANGLES


def test_rectangle_records_without_the_reservation_are_omitted():
    from pillow_wmf.emf.player import play

    short = variable.GradientFill((0, 0, 9, 9), 0, ((0, 0, 0, 0, 0, 0), (9, 9, 0, 0, 0, 0)), ((0, 1),), b"")
    metafile = Metafile.build([short], frame=(0, 0, 1000, 1000))
    omissions = play(metafile, RasterContext(10, 10, trace_calls=False), strict=False, rect=(0, 0, 10, 10))
    assert [omission.reason for omission in omissions] == [
        "Rectangle gradients without reserved mesh space stop native playback"
    ]
