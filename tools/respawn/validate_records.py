#!/usr/bin/env python3
"""Selected R1/R2 cross-lump checks, not an engine compatibility certificate.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Binary format research credited in docs/respawn/RESPAWN_SOURCES.md; original code.
"""
import argparse
import json
import math
from pathlib import Path
import struct
import sys

from inspect_bsp import FormatError, HEADER_SIZE, inspect

# Exact versions only. Apex collision and vertex layouts need separate schemas.
SCHEMAS = {
    1: ("4f", 1), 2: ("3f6i", 1), 3: ("3f", 0),
    14: ("6f2I", 0), 30: ("3f", 0),
    71: ("2I2f4B", 0), 72: ("2I2f4B4f", 1),
    73: ("2I2f4B4f2I", 1), 74: ("2I2f4B2I", 0),
    79: ("H", 0), 80: ("I4H4b2h2BHI", 0),
    81: ("8f", 0), 82: ("4hi", 0), 85: ("f6i", 0),
    86: ("2H", 0), 87: ("2HI", 0), 88: ("8h", 0),
    89: ("I", 0), 90: ("8h", 0), 91: ("I", 0),
    92: ("3fBBH3fI", 0), 93: ("H", 0), 94: ("H", 0),
    95: ("8f", 0),
}


def load_records(path, inventory):
    result = {}
    with Path(path).open("rb") as stream:
        for index, (fmt, version) in SCHEMAS.items():
            if index == 80 and inventory["version_raw"] == 37:
                fmt = "I3H6b2h2BHI"
            entry = inventory["lumps"][index]
            external = next((v for v in entry["external_files"]
                             if v["variant"] == "default"), None)
            length = external["size"] if external else entry["length"]
            if length > 256 * 1024 * 1024:
                raise FormatError(f"lump {index}: exceeds 256 MiB read limit")
            if length and entry["version"] != version:
                raise FormatError(f"lump {index}: unsupported record version {entry['version']}")
            if length and entry["fourcc"]:
                raise FormatError(f"lump {index}: compressed/encoded payload is unsupported")
            if external:
                data = Path(external["path"]).read_bytes()
            else:
                if length and (entry["offset"] < HEADER_SIZE or
                               entry["offset"] + length > inventory["size"]):
                    raise FormatError(f"lump {index}: embedded payload outside file")
                stream.seek(entry["offset"])
                data = stream.read(length)
            stride = struct.calcsize("<" + fmt)
            if len(data) != length or length % stride:
                raise FormatError(f"lump {index}: length {length} is not complete {stride}-byte records")
            result[index] = list(struct.iter_unpack("<" + fmt, data))
    return result


def check_records(records):
    issues = []

    def error(lump, index, message):
        issues.append({"severity": "error", "lump": lump,
                       "record": index, "message": message})

    brushes, offsets, properties, vectors = (records[i] for i in (92, 93, 94, 95))
    if len(properties) != len(vectors):
        error(94, None, "side properties and texture vectors have different counts")
    if len(properties) != 6 * len(brushes) + len(offsets):
        error(94, None, "side count does not equal six axial sides per brush plus plane offsets")
    if brushes and len(records[85]) != 1:
        error(85, None, "brush collision requires exactly one grid header")
    base_plane = records[85][0][6] if records[85] else 0
    cells, sets, set_bounds, primitives, primitive_bounds, contents = (records[i] for i in range(86, 92))
    if len(sets) != len(set_bounds) or len(primitives) != len(primitive_bounds):
        error(88, None, "collision records and bounds have different counts")
    if records[85]:
        grid = records[85][0]
        if not math.isfinite(grid[0]) or grid[0] <= 0 or grid[3] <= 0 or grid[4] <= 0:
            error(85, 0, "invalid collision grid scale or dimensions")
        elif len(cells) != grid[3] * grid[4] + len(records[14]):
            error(86, None, "grid-cell count differs from XY grid plus model cells")
    for i, (start, count) in enumerate(cells):
        if start + count > len(sets):
            error(86, i, "geo-set slice outside CM_GEO_SETS")

    def primitive_reference(lump, i, word):
        kind, index, unique = word >> 24, (word >> 8) & 0xffff, word & 0xff
        if unique >= len(contents):
            error(lump, i, "contents reference outside CM_UNIQUE_CONTENTS")
        if kind == 0 and index >= len(brushes):
            error(lump, i, "brush reference outside CM_BRUSHES")
        # Triangle/prop collision payloads are outside this selected validator.

    for i, (_, count, word) in enumerate(sets):
        if count == 1:
            primitive_reference(87, i, word)
        elif count > 1:
            start = (word >> 8) & 0xffff
            if start + count > len(primitives):
                error(87, i, "primitive slice outside CM_PRIMITIVES")
            if (word & 0xff) >= len(contents):
                error(87, i, "contents reference outside CM_UNIQUE_CONTENTS")
    for i, (word,) in enumerate(primitives):
        primitive_reference(89, i, word)
    side_prefix = 0
    for i, brush in enumerate(brushes):
        non_discard, count, brush_index, side_offset = brush[3], brush[4], brush[5], brush[9]
        if side_offset != side_prefix:
            error(92, i, "side offset does not match preceding non-axial side count")
        side_prefix += count
        if non_discard > count:
            error(92, i, "non-discard plane count exceeds plane count")
        if brush_index != i:
            error(92, i, "stored brush index differs from its record index")
        if side_offset + count > len(offsets):
            error(92, i, "plane-offset slice outside lump")
            continue
        start = 6 * brush_index + side_offset
        if start + 6 + count > len(properties):
            error(92, i, "side-property slice outside lump")
        for j in range(count):
            offset_index = side_offset + j
            plane = base_plane + offset_index - offsets[offset_index][0]
            if not 0 <= plane < len(records[1]):
                error(92, i, "cutting plane reference outside PLANES")
    for i, prop in enumerate(properties):
        if (prop[0] & 0x1ff) >= len(records[2]):
            error(94, i, "texture reference outside TEXTURE_DATA")

    meshes, bounds, sorts, indices = (records[i] for i in (80, 81, 82, 79))
    if len(meshes) != len(bounds):
        error(81, None, "mesh bounds and meshes have different counts")
    for i, model in enumerate(records[14]):
        if model[6] + model[7] > len(meshes):
            error(14, i, "mesh slice outside MESHES")
    for i, sort in enumerate(sorts):
        if not 0 <= sort[0] < len(records[2]):
            error(82, i, "texture reference outside TEXTURE_DATA")
        if sort[4] < 0:
            error(82, i, "negative vertex pool offset")
    for i, mesh in enumerate(meshes):
        first, triangles = mesh[:2]
        material, flags = mesh[-2:]
        if first + 3 * triangles > len(indices):
            error(80, i, "triangle slice outside MESH_INDICES")
            continue
        if material >= len(sorts):
            error(80, i, "material sort outside MATERIAL_SORTS")
            continue
        pool = {0: 72, 0x200: 73, 0x400: 71, 0x600: 74}[flags & 0x600]
        base_vertex = sorts[material][4]
        surface_first = mesh[2]
        surface_last = surface_first + mesh[3]
        if not 0 <= base_vertex + surface_first <= base_vertex + surface_last < len(records[pool]):
            error(80, i, "inclusive surface vertex range outside selected vertex pool")
        if any(not surface_first <= v[0] <= surface_last
               for v in indices[first:first + 3 * triangles]):
            error(80, i, "triangle vertex outside inclusive surface vertex range")
        if any(not 0 <= base_vertex + v[0] < len(records[pool])
               for v in indices[first:first + 3 * triangles]):
            error(80, i, "triangle vertex reference outside selected vertex pool")
        # The runtime reads triangles in pairs (crash at engine.dll+0xae8d3 otherwise):
        # retail six-aligns every mesh and pads odd ones with a degenerate triangle.
        if first % 6:
            error(80, i, "triangle slice not aligned to a triangle pair")
        if triangles & 1:
            pad = indices[first + 3 * triangles:first + 3 * triangles + 3]
            if len(pad) != 3 or len({v[0] for v in pad}) != 1:
                error(80, i, "odd triangle count without a degenerate padding triangle")
    for pool in (71, 72, 73, 74):
        for i, vertex in enumerate(records[pool]):
            if vertex[0] >= len(records[3]) or vertex[1] >= len(records[30]):
                error(pool, i, "position or normal reference outside lump")
    for i, bound in enumerate(bounds):
        if not all(math.isfinite(v) for v in bound) or any(v < 0 for v in bound[4:7]) or bound[3] < 0:
            error(81, i, "invalid mesh bounds")
        elif bound[3] == 0 and any(bound[4:7]):
            error(81, i, "nonempty mesh has zero bounding radius")
    return issues


def validate(path):
    inventory = inspect(path)
    if inventory["version_raw"] not in (29, 37) or inventory["byte_order"] != "little":
        raise FormatError("record validation currently supports little-endian BSP v29/v37 only")
    structural = [i for i in inventory["issues"] if i["severity"] == "error"]
    if structural:
        raise FormatError("structural inventory failed; run inspect_bsp.py for details")
    records = load_records(path, inventory)
    return {"path": str(Path(path).resolve()), "version": inventory["version_raw"],
            "counts": {str(i): len(v) for i, v in records.items()},
            "issues": check_records(records)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    reports = []
    for path in args.paths:
        try:
            reports.append(validate(path))
        except (OSError, FormatError) as exc:
            reports.append({"path": str(path), "issues": [{"severity": "error", "message": str(exc)}]})
    result = json.dumps(reports, indent=2)
    if args.output:
        args.output.write_text(result + "\n", encoding="utf-8")
    else:
        print(result)
    return int(any(r["issues"] for r in reports))


if __name__ == "__main__":
    sys.exit(main())
