"""Read exported frame entry points for fixed-point implementation research."""

import os
import struct
from pathlib import Path


def inspect(path):
    data = path.read_bytes()

    def unpack(layout, offset):
        return struct.unpack_from("<" + layout, data, offset)

    pe = unpack("I", 0x3C)[0]
    count = unpack("H", pe + 6)[0]
    optional_size = unpack("H", pe + 20)[0]
    optional = pe + 24
    sections = [unpack("IIII", optional + optional_size + 40 * i + 8) for i in range(count)]

    def offset(rva):
        for virtual_size, virtual, raw_size, raw in sections:
            if virtual <= rva < virtual + max(virtual_size, raw_size):
                return raw + rva - virtual
        raise ValueError(rva)

    directory = unpack("I", optional + (112 if unpack("H", optional)[0] == 0x20B else 96))[0]
    if not directory:
        return
    export = offset(directory)
    _, names_count, functions, names, ordinals = unpack("IIIII", export + 20)
    entries = []
    for index in range(names_count):
        name_offset = offset(unpack("I", offset(names) + 4 * index)[0])
        name = data[name_offset : data.index(0, name_offset)].decode("ascii")
        if "FrameRgn" in name or "FrameRegion" in name:
            ordinal = unpack("H", offset(ordinals) + 2 * index)[0]
            rva = unpack("I", offset(functions) + 4 * ordinal)[0]
            entries.append((name, rva))
    print(path.name, entries, flush=True)
    for name, rva in entries:
        print(name, hex(rva), data[offset(rva) : offset(rva) + 2048].hex(), flush=True)


for filename in ("gdi32full.dll", "win32kfull.sys", "win32kbase.sys"):
    inspect(Path(os.environ["SystemRoot"]) / "System32" / filename)
