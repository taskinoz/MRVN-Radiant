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
from game_lump import inspect_game_lump
from tricoll import check_tricoll_records
from portals import check_portal_records

# Exact versions only. Apex collision and vertex layouts need separate schemas.
SCHEMAS = {
    1: ("4f", 1), 2: ("3f6i", 1), 3: ("3f", 0),
    14: ("6f2I", 0), 30: ("3f", 0),
    66: ("I", 2), 68: ("4I", 1), 69: ("6H4i4f", 1),
    71: ("2I2f4B", 0), 72: ("2I2f4B4f", 1),
    73: ("2I2f4B4f2I", 1), 74: ("2I2f4B2I", 0),
    79: ("H", 0), 80: ("I4H4b2h2BHI", 0),
    81: ("8f", 0), 82: ("4hi", 0), 85: ("f6i", 0),
    86: ("2H", 0), 87: ("2HI", 0), 88: ("8h", 0),
    89: ("I", 0), 90: ("8h", 0), 91: ("I", 0),
    92: ("3fBBH3fI", 0), 93: ("H", 0), 94: ("H", 0),
    95: ("8f", 0),
    96: ("H", 0), 97: ("I", 0),
    106: ("iI", 0), 107: ("3Hh", 0), 108: ("4B2HI", 0),
    109: ("3f", 0), 110: ("2H", 0), 111: ("8h", 0),
    112: ("H", 0), 113: ("H", 0), 114: ("8h", 0), 115: ("8h", 0), 116: ("2I", 0),
    119: ("3fBBH3fHH", 0), 120: ("H", 0), 121: ("3fI3fI", 0),
    123: ("4I3f", 0),
}

# v29 only: v37 world lights and probe references have different strides.
TF1_SCHEMAS = {
    36: ('2fi', 1), 42: ('3iI', 0), 44: ('I', 0), 54: ('12f3i7f3i', 1),
    99: ('3fBBH3fHH', 0), 100: ('H', 0),
    83: ('I2H', 1), 101: ('16h4B4hI', 0), 102: ('H', 0),
    103: ('2I', 0), 104: ('3fI', 0),
    117: ('3f', 0), 118: ('H', 0),
    124: ('3f', 0), 125: ('5f', 0), 126: ('H', 0), 127: ('2I2h', 0),
}


def check_tf2_object_references(records, prop_count):
    """TF2 uses a 64-aligned non-sky mesh block before static-prop objects."""
    issues = []
    def error(lump, index, message):
        issues.append({'severity':'error','lump':lump,'record':index,'message':message})
    if len(records[123]) != 1 or not records[14]:
        error(123,None,'TF2 object references require one LEVEL_INFO and a world model')
        return issues
    level = records[123][0]
    first_sky, world_meshes = level[2], records[14][0][7]
    if not 0 <= level[0] <= level[1] <= first_sky <= world_meshes:
        error(123,0,'invalid world mesh category ranges')
    if level[3] != prop_count:
        error(123,0,'LEVEL_INFO prop count differs from GAME_LUMP')
    base = (first_sky + 63) & ~63
    for i,(ref,) in enumerate(records[120]):
        if ref >= base + prop_count or (world_meshes <= ref < base):
            error(120,i,'object reference outside world mesh/static prop namespace')
    return issues


def load_records(path, inventory):
    result = {}
    with Path(path).open("rb") as stream:
        schemas = SCHEMAS | TF1_SCHEMAS if inventory['version_raw'] == 29 else SCHEMAS
        for index, (fmt, version) in schemas.items():
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
        if kind == 0x40 and index >= len(records[69]):
            error(lump, i, "triangle collision reference outside TRICOLL_HEADERS")

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
        elif any(bool(properties[start+6+j][0] & 0x4000) != (j >= non_discard) for j in range(count)):
            error(92, i, "authored/bevel plane counts disagree with side discard flags")
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
    normal_references = {vertex[1] for pool in (71,72,73,74) for vertex in records[pool]}
    for i, normal in enumerate(records[30]):
        # Retail reserves an unreferenced zero vector at slot zero.
        if i == 0 and normal == (0,0,0) and i not in normal_references:
            continue
        if not all(math.isfinite(v) for v in normal):
            error(30, i, "nonfinite vertex normal")
        elif abs(sum(v*v for v in normal)-1) > 1e-3:
            error(30, i, "vertex normal is not a unit vector")
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


def check_tf1_csm_records(records):
    """Check v29 CSM tree structure, without assigning meanings to shadow IDs."""
    issues = []
    nodes, references = records[99], records[100]
    graph = {}
    def error(index, message):
        issues.append({'severity': 'error', 'lump': 99, 'record': index, 'message': message})
    for index, node in enumerate(nodes):
        mins, maxs = node[:3], node[6:9]
        children, local_count, total_count, first_child, first_ref = node[3:6] + node[9:11]
        if (not all(math.isfinite(v) for v in (*mins, *maxs)) or
                any(lo > hi for lo, hi in zip(mins, maxs))):
            error(index, 'invalid CSM bounds')
        if local_count > total_count or first_ref + total_count > len(references):
            error(index, 'CSM reference range outside CSM_OBJ_REFERENCES')
        if children:
            if first_child + children > len(nodes):
                error(index, 'CSM child range outside CSM_AABB_NODES')
            else:
                graph[index] = range(first_child, first_child + children)
    colors = {}
    for root in graph:
        pending = [(root, False)]
        while pending:
            index, leaving = pending.pop()
            if leaving:
                colors[index] = 2
            elif colors.get(index) == 1:
                error(index, 'CSM tree cycle')
            elif colors.get(index) != 2:
                colors[index] = 1
                pending.append((index, True))
                pending.extend((child, False) for child in graph.get(index, ()))
    return issues


def load_raw_payload(path, inventory, index):
    """Read one bounded, unencoded lump, preferring its default sidecar."""
    entry = inventory['lumps'][index]
    external = next((item for item in entry['external_files'] if item['variant'] == 'default'), None)
    size = external['size'] if external else entry['length']
    if size > 256 * 1024 * 1024 or (size and (entry['version'] != 0 or entry['fourcc'])):
        raise FormatError(f'lump {index}: oversized, encoded or unsupported payload version')
    if external:
        data = Path(external['path']).read_bytes()
    else:
        if size and (entry['offset'] < HEADER_SIZE or entry['offset'] + size > inventory['size']):
            raise FormatError(f'lump {index}: embedded payload outside file')
        with Path(path).open('rb') as stream:
            stream.seek(entry['offset'])
            data = stream.read(size)
    if len(data) != size:
        raise FormatError(f'lump {index}: truncated payload')
    return data


def check_tf1_texture_strings(data, table, textures):
    issues = []
    def error(lump, index, message):
        issues.append({'severity': 'error', 'lump': lump, 'record': index, 'message': message})
    for index, (offset,) in enumerate(table):
        if not 0 <= offset < len(data):
            error(44, index, 'texture string offset outside TEXTURE_DATA_STRING_DATA')
        elif offset and data[offset - 1] != 0:
            error(44, index, 'texture string offset points inside another string')
        elif data.find(b'\0', offset) == -1 or data[offset] == 0:
            error(44, index, 'texture string is empty or unterminated')
    for index, texture in enumerate(textures):
        if not 0 <= texture[3] < len(table):
            error(2, index, 'texture name index outside TEXTURE_DATA_STRING_TABLE')
    return issues


def check_tf1_physics(data, model_count):
    """Bound model/solid framing and keydata; do not decode IVP collision trees."""
    issues = []
    def error(index, message):
        issues.append({'severity': 'error', 'lump': 29, 'record': index, 'message': message})
    cursor, seen = 0, set()
    while cursor < len(data):
        if len(data) - cursor < 16:
            error(None, 'truncated physics model header')
            return issues
        model, size, keysize, count = struct.unpack_from('<4i', data, cursor)
        cursor += 16
        if model == -1:
            if (size, keysize, count) != (-1, 0, 0) or cursor != len(data):
                error(None, 'invalid physics terminal header or trailing bytes')
            return issues
        if model < 0 or model >= model_count or model in seen:
            error(model, 'physics model index outside MODELS or duplicated')
        seen.add(model)
        if size < 0 or keysize < 0 or count < 0 or size + keysize > len(data) - cursor:
            error(model, 'physics model payload range outside PHYSICS_COLLIDE')
            return issues
        end = cursor + size
        if count > size // 4:
            error(model, 'physics solid count exceeds model payload')
            return issues
        for _ in range(count):
            if end - cursor < 4:
                error(model, 'truncated physics solid length')
                return issues
            length, = struct.unpack_from('<i', data, cursor)
            cursor += 4
            if length < 4 or length > end - cursor:
                error(model, 'physics solid range outside model payload')
                return issues
            if data[cursor:cursor + 4] != b'VPHY':
                error(model, 'unsupported physics solid signature')
            cursor += length
        if cursor != end:
            error(model, 'physics solids do not consume model payload')
        keys = data[end:end + keysize]
        if keysize and (keys[-1:] != b'\0' or b'\0' in keys[:-1]):
            error(model, 'physics keydata is not one terminated string')
        cursor = end + keysize
    if data:
        error(None, 'missing physics terminal header')
    return issues


def check_tf1_shadow_records(records):
    """Check v29 occlusion/shadow streams; shadow-object IDs remain opaque."""
    issues = []
    def error(lump, index, message):
        issues.append({'severity': 'error', 'lump': lump, 'record': index, 'message': message})
    for lump in (117, 124, 125):
        for index, vertex in enumerate(records[lump]):
            if not all(math.isfinite(value) for value in vertex):
                error(lump, index, 'nonfinite occlusion/shadow vertex')
    if len(records[118]) % 3:
        error(118, None, 'occlusion index count is not a triangle list')
    for index, (vertex,) in enumerate(records[118]):
        if vertex >= len(records[117]):
            error(118, index, 'occlusion index outside OCCLUSION_MESH_VERTICES')
    first = 0
    indices = records[126]
    for index, (base, triangles, opaque, material) in enumerate(records[127]):
        end = first + triangles * 3
        if opaque not in (0, 1):
            error(127, index, 'invalid shadow opaque selector')
        else:
            pool = records[124 if opaque else 125]
            if base > len(pool):
                error(127, index, 'shadow vertex base outside selected pool')
            if any(base + vertex >= len(pool) for (vertex,) in indices[first:end]):
                error(127, index, 'shadow mesh-local index outside selected vertex pool')
        if material < -1 or material >= len(records[82]) or (not opaque and material == -1):
            error(127, index, 'shadow material outside MATERIAL_SORT')
        if end > len(indices):
            error(127, index, 'shadow triangle range outside SHADOW_MESH_INDICES')
        first = end
    if first != len(indices):
        error(126, None, 'shadow mesh triangle counts do not consume index stream')
    return issues


def check_tf1_records(records, inventory):
    """Known v29 auxiliary layouts; no claim about RTL channel meanings."""
    issues = check_tf1_csm_records(records) + check_tf1_shadow_records(records)
    def error(lump, index, message):
        issues.append({'severity': 'error', 'lump': lump, 'record': index, 'message': message})
    for i, (surface, bottom, texture) in enumerate(records[36]):
        if not math.isfinite(surface) or not math.isfinite(bottom) or bottom > surface:
            error(36, i, 'invalid water height range')
        if not 0 <= texture < len(records[2]):
            error(36, i, 'water texture outside TEXTURE_DATA')
    for i, (_, _, _, water) in enumerate(records[107]):
        if water < -1 or water >= len(records[36]):
            error(107, i, 'cell water reference outside LEAF_WATER_DATA')
    for i, light in enumerate(records[54]):
        if not all(math.isfinite(v) for v in (*light[:12], *light[15:22])):
            error(54, i, 'nonfinite world light')
    for i, (x, y, z, probe) in enumerate(records[104]):
        if not all(math.isfinite(v) for v in (x, y, z)):
            error(104, i, 'nonfinite lightprobe reference')
        if probe >= len(records[101]):
            error(104, i, 'lightprobe reference outside LIGHTPROBES')
    for i, (probe,) in enumerate(records[102]):
        if probe != 0xffff and probe >= len(records[101]):
            error(102, i, 'static-prop probe outside LIGHTPROBES')
    graph = {}
    for i, (word, value) in enumerate(records[103]):
        first, axis = word >> 2, word & 3
        if axis == 3:
            if first + value > len(records[104]):
                error(103, i, 'lightprobe leaf range outside LIGHTPROBE_REFERENCES')
        elif first + 1 >= len(records[103]):
            error(103, i, 'lightprobe child outside LIGHTPROBE_TREE')
        else:
            cut = struct.unpack('<f', struct.pack('<I', value))[0]
            if not math.isfinite(cut):
                error(103, i, 'nonfinite lightprobe tree split')
            graph[i] = (first, first + 1)
    # Iterative traversal: malformed files must not exhaust Python's stack.
    colors = {}
    for root in graph:
        pending = [(root, False)]
        while pending:
            node, leaving = pending.pop()
            if leaving:
                colors[node] = 2
            elif colors.get(node) == 1:
                error(103, node, 'cycle in lightprobe tree')
            elif not colors.get(node):
                colors[node] = 1
                pending.append((node, True))
                pending.extend((child, False) for child in graph.get(node, ()))
    texels = 0
    for i, (_, width, height) in enumerate(records[83]):
        if not width or not height or width > 16384 or height > 16384:
            error(83, i, 'invalid lightmap dimensions')
        texels += width * height
    for lump, stride in ((98, 8), (105, 4)):
        entry = inventory['lumps'][lump]
        external = next((e for e in entry['external_files'] if e['variant'] == 'default'), None)
        size = external['size'] if external else entry['length']
        if size != texels * stride:
            error(lump, None, f'lightmap plane bytes {size}, expected {texels * stride}')
    for i, sort in enumerate(records[82]):
        if sort[1] < -1 or sort[1] >= len(records[83]):
            error(82, i, 'material lightmap outside LIGHTMAP_HEADERS')
    return issues


def validate(path):
    inventory = inspect(path)
    if inventory["version_raw"] not in (29, 37) or inventory["byte_order"] != "little":
        raise FormatError("record validation currently supports little-endian BSP v29/v37 only")
    structural = [i for i in inventory["issues"] if i["severity"] == "error"]
    if structural:
        raise FormatError("structural inventory failed; run inspect_bsp.py for details")
    records = load_records(path, inventory)
    report = {"path": str(Path(path).resolve()), "version": inventory["version_raw"],
            "counts": {str(i): len(v) for i, v in records.items()},
            "issues": check_records(records)}
    report["issues"].extend(check_tricoll_records(records, inventory["version_raw"]))
    if inventory['version_raw'] == 29:
        report['issues'].extend(check_tf1_records(records, inventory))
        report['issues'].extend(check_tf1_texture_strings(
            load_raw_payload(path, inventory, 43), records[44], records[2]))
        report['issues'].extend(check_tf1_physics(
            load_raw_payload(path, inventory, 29), len(records[14])))
    if inventory["version_raw"] == 37:
        report["game_lump"] = inspect_game_lump(path, inventory=inventory)
        # Minimal synthetic fixtures may have no visibility data at all.
        if records[123] or records[120]:
            prop_count = sum(e.get('placement_count',0) for e in report['game_lump']['entries'])
            report['issues'].extend(check_tf2_object_references(records,prop_count))
    report["issues"].extend(check_portal_records(records, inventory["version_raw"]))
    return report


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
