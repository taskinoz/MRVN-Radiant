#!/usr/bin/env python3
"""Original, uncompressed Titanfall 2 VPK 2.3 writer for small test packages.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Format reference: pg9182/tf2vpk, commit b73c54d8e4245075ea207c7e51a2a86fdb94e4ff
(MIT). No upstream code copied. Not an RPAK or compressed VPK writer.
"""
from collections import defaultdict
from pathlib import Path, PurePosixPath
import struct
import zlib


def pack_files(files, folder, name):
    """Write a new English directory VPK and external block; never overwrite."""
    if not name.startswith("client_") or not name.endswith(".bsp.pak000") or any(
            c in name for c in "/\\:\0"):
        raise ValueError("expected client_NAME.bsp.pak000 archive name")
    groups = defaultdict(lambda: defaultdict(list))
    seen = set()
    for path, payload in sorted(files.items()):
        p = PurePosixPath(path)
        if (not path or p.is_absolute() or any(c in path for c in "\\:\0") or
                any(part in ("", ".", "..") for part in path.split("/")) or
                path.casefold() in seen or not payload or not p.suffix):
            raise ValueError(f"invalid, duplicate or empty VPK member: {path!r}")
        seen.add(path.casefold())
        groups[p.suffix[1:]][str(p.parent) if str(p.parent) != "." else " "].append(
            (p.stem, bytes(payload)))
    if not seen:
        raise ValueError("empty archive")
    tree, block = bytearray(), bytearray()
    for extension, paths in sorted(groups.items()):
        tree.extend(extension.encode("ascii") + b"\0")
        for parent, entries in sorted(paths.items()):
            tree.extend(parent.encode("ascii") + b"\0")
            for basename, payload in entries:
                tree.extend(basename.encode("ascii") + b"\0")
                tree.extend(struct.pack("<IHH", zlib.crc32(payload), 0, 0))
                for start in range(0, len(payload), 0x100000):
                    chunk = payload[start:start + 0x100000]
                    # Retail Coliseum BSP/ENT files use VISIBLE | CACHE (0x101).
                    tree.extend(struct.pack("<IHQQQ", 0x101, 0, len(block), len(chunk), len(chunk)))
                    block.extend(chunk)
                    tree.extend(struct.pack("<H", 0xffff if start + len(chunk) == len(payload) else 0))
            tree.extend(b"\0")
        tree.extend(b"\0")
    tree.extend(b"\0")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    directory = folder / f"english{name}_dir.vpk"
    archive = folder / f"{name}_000.vpk"
    if directory.exists() or archive.exists():
        raise FileExistsError("VPK output already exists")
    with archive.open("xb") as out:
        out.write(block)
    with directory.open("xb") as out:
        out.write(struct.pack("<IHHII", 0x55aa1234, 2, 3, len(tree), 0))
        out.write(tree)
    return directory, archive
