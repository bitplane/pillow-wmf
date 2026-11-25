"""Print symbol-server keys of the native graphics modules on the oracle.

For each module the PE TimeDateStamp and SizeOfImage identify the exact
build, and the CodeView record names its PDB, so the same files can be
fetched from Microsoft's public symbol server for offline analysis. The
module bytes themselves are not copied or uploaded.

    module path stamp=XXXXXXXX image=XXXXX pdb=NAME guid=GUIDAGE
"""

import os
import platform
import struct
from pathlib import Path

from windows_wmf_render import module_versions

SYSTEM = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32"
MODULES = ("gdi32.dll", "gdi32full.dll", "win32u.dll", "win32kfull.sys", "win32kbase.sys", "win32k.sys")


def identity(path):
    data = path.read_bytes()
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    stamp = struct.unpack_from("<I", data, pe + 8)[0]
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    image = struct.unpack_from("<I", data, optional + 56)[0]
    directories = optional + (112 if magic == 0x20B else 96)
    debug_rva, debug_size = struct.unpack_from("<II", data, directories + 6 * 8)
    sections = optional + struct.unpack_from("<H", data, pe + 20)[0]
    count = struct.unpack_from("<H", data, pe + 6)[0]

    def offset(rva):
        for index in range(count):
            size, address, _, raw = struct.unpack_from("<IIII", data, sections + 40 * index + 8)
            if address <= rva < address + max(size, 1):
                return raw + rva - address
        return None

    pdb = ""
    start = offset(debug_rva) if debug_rva else None
    for entry in range(debug_size // 28 if start is not None else 0):
        kind, size, _, pointer = struct.unpack_from("<IIII", data, start + 28 * entry + 12)
        if kind == 2 and data[pointer : pointer + 4] == b"RSDS":
            guid = data[pointer + 4 : pointer + 20]
            age = struct.unpack_from("<I", data, pointer + 20)[0]
            name = data[pointer + 24 : pointer + size].split(b"\0")[0].decode()
            a, b, c = struct.unpack_from("<IHH", guid)
            pdb = f"pdb={name} guid={a:08X}{b:04X}{c:04X}{guid[8:].hex().upper()}{age:X}"
    return f"stamp={stamp:08X} image={image:X} {pdb}"


def main():
    print(f"Windows module ids: {platform.platform()}")
    print(f"Module versions: {module_versions()}")
    for name in MODULES:
        path = SYSTEM / name
        print(f"module {name} {identity(path) if path.is_file() else 'missing'}")


if __name__ == "__main__":
    main()
