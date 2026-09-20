"""Record-local failure boundaries with a visible continuation marker."""

from dataclasses import replace

from pillow_wmf import Metafile
from pillow_wmf.wmf import fixed, variable


def cases():
    for name, records in (
        ("delete-unallocated", [fixed.DeleteObject(3)]),
        ("delete-twice", [fixed.DeleteObject(0), fixed.DeleteObject(0)]),
        ("select-deleted", [fixed.DeleteObject(0), fixed.SelectObject(0)]),
        ("wrong-region-kind", [fixed.InvertRegion(0)]),
    ):
        program = Metafile.build([fixed.CreatePenIndirect(0, 3, 0, 0), *records, fixed.SetPixel(255, 120, 120)])
        yield name, replace(program, header=replace(program.header, object_count=4))
    for width in (0, 3):
        for count in (0, 1, 2):
            yield (
                f"polygon-{count}-pen-{width}",
                Metafile.build(
                    [
                        fixed.CreatePenIndirect(0, width, 0, 0),
                        fixed.SelectObject(0),
                        variable.Polygon(((30, 30), (60, 50))[:count]),
                        fixed.SetPixel(255, 120, 120),
                    ]
                ),
            )
