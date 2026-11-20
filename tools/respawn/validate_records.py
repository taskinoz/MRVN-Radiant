#!/usr/bin/env python3
"""Selected R1/R2 cross-lump checks, not an engine compatibility certificate.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Binary format research credited in docs/respawn/RESPAWN_SOURCES.md; original code.
"""
import argparse
import json
import math
import re
from pathlib import Path
import struct
import sys
import zlib

from inspect_bsp import FormatError, HEADER_SIZE, inspect
from game_lump import decode_sprp_v12, inspect_game_lump, parse_directory
from entity_text import parse_entities, parse_partition
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
    # Retail VERTEX_BLINN_PHONG is always empty; this is the writer's layout.
    75: ('2I2f4B2f4f', 0),
    # One u32 per static prop: every retail upper half is zero.
    83: ('I2H', 1), 101: ('16h4B4hI', 0), 102: ('I', 0),
    103: ('2I', 0), 104: ('3fI', 0),
    117: ('3f', 0), 118: ('H', 0),
    124: ('3f', 0), 125: ('5f', 0), 126: ('H', 0), 127: ('2I2h', 0),
}

# v29 lumps checked from their raw bytes rather than fixed-size records.
TF1_RAW_CHECKS = {0: 'entity text', 24: 'partition declaration', 29: 'physics framing',
                  35: 'sprp v12', 40: 'stored zip', 43: 'texture strings',
                  98: 'texel size', 105: 'texel size and light slots'}


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
    """Check the v29 CSM tree and its aligned static-prop references."""
    issues = []
    nodes, references = records[99], records[100]
    graph = {}
    def error(index, message):
        issues.append({'severity': 'error', 'lump': 99, 'record': index, 'message': message})
    level = records.get(123, [])
    if len(level) == 1:
        first_sky, prop_count = level[0][2:4]
        prop_base = (first_sky + 63) & ~63
        for index, (reference,) in enumerate(references):
            if not prop_base <= reference < prop_base + prop_count:
                issues.append({'severity': 'error', 'lump': 100, 'record': index,
                               'message': 'CSM reference outside aligned v29 static-prop range'})
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


def check_tf1_entities(path, inventory):
    """Validate embedded text and required 01* partition syntax, not gameplay."""
    issues, counts = [], {}
    def error(message):
        issues.append({'severity': 'error', 'lump': 24, 'record': None, 'message': message})
    def entity_issue(message, severity='error'):
        issues.append({'severity': severity, 'lump': 0, 'record': None, 'message': message})
    text = load_raw_payload(path, inventory, 0)
    try:
        entities = parse_entities(text.decode('utf-8', errors='surrogateescape'))
        counts['embedded'] = len(entities)
        classnames = [[value for key, value in pairs if key == 'classname'] for pairs in entities]
        # Every retail map embeds worldspawn first, then brush entities.
        if not entities or classnames[0] != ['worldspawn']:
            entity_issue('embedded entities must start with one worldspawn')
        if sum(names == ['worldspawn'] for names in classnames) > 1:
            entity_issue('embedded entities contain more than one worldspawn')
        if any(len(names) != 1 or not names[0] for names in classnames):
            entity_issue('embedded entity lacks exactly one nonempty classname')
        # Retail ends with one NUL; remap omits it and still loads, so warn only.
        if not text.endswith(b'\0'):
            entity_issue('embedded entity text is not NUL-terminated like retail', 'warning')
    except FormatError as exc:
        entity_issue(str(exc))
    declaration = load_raw_payload(path, inventory, 24)
    if not declaration:
        return issues, counts
    if len(declaration) > 65536:
        error('oversized entity partition declaration')
        return issues, counts
    if not declaration.endswith(b'\0'):
        error('entity partition declaration is not NUL-terminated')
    try:
        tokens = declaration.rstrip(b'\0').decode('ascii').split()
        if ' '.join(tokens).encode() != declaration.rstrip(b'\0'):
            issues.append({'severity': 'warning', 'lump': 24, 'record': None,
                           'message': 'entity partition names are not single-space separated like retail'})
        if (not tokens or tokens[0] != '01*' or len({token.casefold() for token in tokens[1:]}) != len(tokens[1:]) or
                any(not re.fullmatch(r'[A-Za-z0-9_]+', token) for token in tokens[1:])):
            raise ValueError('unsupported or duplicate entity partition declaration')
        for name in tokens[1:]:
            sidecar = Path(path).with_name(Path(path).stem + '_' + name + '.ent')
            if (sidecar.is_symlink() or getattr(sidecar, 'is_junction', lambda: False)() or
                    not sidecar.is_file() or not 0 < sidecar.stat().st_size <= 64 * 1024 * 1024):
                error(f'missing, empty, linked or oversized entity partition: {sidecar.name}')
                continue
            try:
                counts[name] = len(parse_partition(sidecar.read_bytes()))
            except FormatError as exc:
                error(f'{sidecar.name}: {exc}')
    except (UnicodeError, ValueError) as exc:
        error(str(exc))
    return issues, counts


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


IVP_NODE = struct.Struct('<2i')
IVP_LEDGE = struct.Struct('<iIIh')


def check_ivp_solid(data, start, length, cm_brush_count):
    """Return the first structural error in one VPHY compact surface, or None.

    Checks framing, the ledge tree, ledges, triangle indices, edge twins, point
    ranges and finite coordinates. Ledge client data is the CM brush index in
    retail. Retail also stores some -0.0 coordinates and padding, so neither is
    checked here; remap's own output is held to +0.0 by compiler_regression.py.
    """
    if length < 76:
        return 'physics solid is shorter than its VPHY and compact-surface headers'
    version, model_type, surface_size = struct.unpack_from('<hhi', data, start + 4)
    if (version, model_type) != (0x100, 0) or surface_size != length - 28:
        return 'unsupported VPHY version/model type or surface size'
    surface = start + 28
    end = surface + surface_size
    word, root = struct.unpack_from('<Ii', data, surface + 28)
    if word >> 8 != surface_size or data[surface + 44:surface + 48] != b'IVPS':
        return 'compact surface byte size or IVPS marker is invalid'
    if not all(math.isfinite(v) for v in struct.unpack_from('<7f', data, surface)):
        return 'nonfinite compact-surface mass/inertia/radius'
    pending, nodes = [surface + root], 0
    while pending:
        node = pending.pop()
        nodes += 1
        if not surface + 48 <= node <= end - 28 or nodes > surface_size // 28:
            return 'ledge tree node outside surface or cyclic'
        right, offset = IVP_NODE.unpack_from(data, node)
        if right:
            if right < 56:
                return 'ledge tree right child does not follow its left subtree'
            pending += [node + 28, node + right]
            continue
        ledge = node + offset
        if not surface + 48 <= ledge <= end - 16:
            return 'ledge outside surface'
        points, client, flags, triangles = IVP_LEDGE.unpack_from(data, ledge)
        if flags & 0xf != 4 or triangles <= 0 or ledge + 16 + 16 * triangles > end:
            return 'ledge flags or triangle range invalid'
        if cm_brush_count and client >= cm_brush_count:
            return 'ledge client data outside CM_BRUSHES'
        words = struct.unpack_from(f'<{4 * triangles}I', data, ledge + 16)
        used = set()
        for t in range(triangles):
            if words[4 * t] & 0xfff != t:
                return 'ledge triangle index disagrees with its position'
            for k in range(3):
                edge = words[4 * t + 1 + k]
                opposite = (edge >> 16) & 0x7fff
                opposite -= 0x8000 if opposite & 0x4000 else 0
                other = 4 * t + 1 + k + opposite
                if not 0 <= other < len(words) or other % 4 == 0:
                    return 'ledge edge twin outside its triangles'
                following = words[4 * t + 1 + (k + 1) % 3] & 0xffff
                if words[other] & 0xffff != following:
                    return 'ledge edge is not twinned with its reverse'
                used.add(edge & 0xffff)
        first = ledge + points
        if not surface + 48 <= first or first + 16 * (max(used) + 1) > end:
            return 'ledge points outside surface'
        for index in used:
            if not all(math.isfinite(v) for v in struct.unpack_from('<3f', data, first + 16 * index)):
                return 'nonfinite ledge point'
    return None


def check_tf1_physics(data, model_count, cm_brush_count=0):
    """Bound model/solid framing and keydata, then each IVP compact surface."""
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
            else:
                problem = check_ivp_solid(data, cursor, length, cm_brush_count)
                if problem:
                    error(model, problem)
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


def check_tf1_game_lump(data, base, records):
    """Check the v29 sprp v12 framing, dictionary and placements.

    Returns (issues, prop_count). Fields retail fills with stale bytes (the two
    u16 after the model index, lighting origin, the word before scale) are not
    checked, and the always-empty leaf table gives no leaf ranges to check.
    """
    issues = []
    def error(lump, index, message):
        issues.append({'severity': 'error', 'lump': lump, 'record': index, 'message': message})
    if not data:
        return issues, 0
    try:
        entries = parse_directory(data, base)
    except FormatError as exc:
        error(35, None, str(exc))
        return issues, None
    sprp = [entry for entry in entries if entry['name'] == 'sprp']
    if len(sprp) != 1:
        error(35, None, 'GAME_LUMP must hold exactly one sprp entry')
        return issues, None
    entry = sprp[0]
    if (entry['flags'], entry['version']) != (0, 12):
        error(35, None, f"unsupported v29 sprp flags {entry['flags']} version {entry['version']}")
        return issues, None
    start = entry['relative_offset'] or 0
    try:
        sprp = decode_sprp_v12(data[start:start + entry['length']])
    except FormatError as exc:
        error(35, None, str(exc))
        return issues, None
    names, count = sprp['model_names'], sprp['placement_count']
    for index, raw in enumerate(names):
        if b'\0' not in raw or raw[0] == 0:
            error(35, index, 'sprp model name is empty or unterminated')
    first, second = sprp['unknown_header_counts']
    # Unknown counts; second <= first <= placements in every retail map. A
    # header shifted by one word (placements then one count) breaks this.
    if not second <= first <= count:
        error(35, None, 'sprp v12 header counts are not ordered as in retail')
    for index, prop in enumerate(sprp['placements']):
        if prop[6] >= len(names):
            error(35, index, 'sprp placement model index outside name table')
        if not all(math.isfinite(value) for value in (*prop[:6], prop[13], prop[14], prop[18])):
            error(35, index, 'nonfinite sprp placement origin, angles or fade')
        if not math.isfinite(prop[28]) or prop[28] <= 0:
            error(35, index, 'sprp placement scale is not finite and positive')
    level = records.get(123, [])
    if len(level) == 1 and level[0][3] != count:
        error(123, 0, 'LEVEL_INFO static-prop count differs from sprp placements')
    probes = records.get(102, [])
    if probes and len(probes) != count:
        error(102, None, 'static-prop probe count differs from sprp placements')
    return issues, count


def check_tf1_pakfile(data):
    """Check that a v29 PAKFILE is a self-contained stored zip."""
    issues = []
    def error(index, message):
        issues.append({'severity': 'error', 'lump': 40, 'record': index, 'message': message})
    if not data:
        return issues
    eocd = None
    for position in range(len(data) - 22, max(-1, len(data) - 22 - 65536), -1):
        if (data[position:position + 4] == b'PK\x05\x06' and
                position + 22 + struct.unpack_from('<H', data, position + 20)[0] == len(data)):
            eocd = position
            break
    if eocd is None:
        error(None, 'pakfile lacks an end-of-central-directory record ending the lump')
        return issues
    disk, cd_disk, disk_entries, entries, cd_size, cd_offset = struct.unpack_from('<4H2I', data, eocd + 4)
    if disk or cd_disk or disk_entries != entries or 0xffff in (disk_entries, entries):
        error(None, 'multi-disk or ZIP64 pakfile is unsupported')
        return issues
    if cd_offset + cd_size > eocd:
        error(None, 'pakfile central directory outside lump')
        return issues
    cursor, spans, names = cd_offset, [], set()
    for index in range(entries):
        if cursor + 46 > cd_offset + cd_size or data[cursor:cursor + 4] != b'PK\x01\x02':
            error(index, 'truncated or invalid pakfile central directory entry')
            return issues
        (flags, method, crc, packed, size, name_length, extra_length, comment_length,
         local) = struct.unpack_from('<8x2H4x3I3H8xI', data, cursor)
        name = data[cursor + 46:cursor + 46 + name_length]
        cursor += 46 + name_length + extra_length + comment_length
        if cursor > cd_offset + cd_size:
            error(index, 'pakfile entry name outside central directory')
            return issues
        text = name.decode('utf-8', errors='replace').replace('\\', '/')
        if not name or text.startswith('/') or '..' in text.split('/') or ':' in text:
            error(index, 'unsafe or empty pakfile entry name')
        if text.casefold() in names:
            error(index, 'duplicate pakfile entry name')
        names.add(text.casefold())
        # Every retail entry is stored (method 0) and unencrypted.
        if method != 0 or flags & 1 or packed != size or 0xffffffff in (packed, size, local):
            error(index, 'pakfile entry is compressed, encrypted or ZIP64')
            continue
        if local + 30 > cd_offset or data[local:local + 4] != b'PK\x03\x04':
            error(index, 'pakfile local header outside lump or invalid')
            continue
        local_name, local_extra = struct.unpack_from('<2H', data, local + 26)
        begin = local + 30 + local_name + local_extra
        if begin + size > cd_offset:
            error(index, 'pakfile entry data overlaps its central directory or lump end')
            continue
        if zlib.crc32(data[begin:begin + size]) != crc:
            error(index, 'pakfile entry CRC mismatch')
        spans.append((local, begin + size, index))
    if cursor != cd_offset + cd_size:
        error(None, 'pakfile central directory size disagrees with its entries')
    spans.sort()
    for (_, end, _), (start, _, index) in zip(spans, spans[1:]):
        if start < end:
            error(index, 'overlapping pakfile entries')
    return issues


def check_tf1_rtl(data, lights):
    """Check v29 realtime-light texels: four hardware light bytes, 255 unused.

    In every retail map used slots precede unused ones and each byte names a
    point or spot light by hardware index: its WORLD_LIGHTS index once the
    ambient records (type 5) are skipped. Retail record 0 is the sky ambient,
    so there it is index byte + 1; a map without an ambient starts at 0.
    """
    issues = []
    def error(index, message):
        issues.append({'severity': 'error', 'lump': 105, 'record': index, 'message': message})
    if len(data) % 4:
        return issues  # The texel-count check reports the size.
    used = data.translate(RTL_USED)
    filled = RTL_ORDER.match(used).end()
    if filled != len(used):
        error(filled // 4, 'realtime-light slot used after an unused slot')
    hardware = [light for light in lights if light[13] != 5]
    for value in sorted(set(data) - {255}):
        if value >= len(hardware):
            error(None, f'realtime-light byte {value} names no WORLD_LIGHTS record')
        elif hardware[value][13] not in (1, 2):
            error(None, f'realtime-light byte {value} names a light that is not point or spot')
    return issues


RTL_USED = bytes(48 + (value != 255) for value in range(256))
RTL_ORDER = re.compile(rb'(?:1111|1110|1100|1000|0000)*')


def check_tf1_vertex_references(records):
    """v29 tangent words are plain normal indices; Blinn-Phong is index-checked."""
    issues = []
    normals = len(records.get(30, []))
    for lump in (73, 74):
        for index, vertex in enumerate(records.get(lump, [])):
            if vertex[-1] >= normals or vertex[-2] >= normals:
                issues.append({'severity': 'error', 'lump': lump, 'record': index,
                               'message': 'v29 tangent/bitangent index outside VERTEX_NORMALS'})
    for index, vertex in enumerate(records.get(75, [])):
        if vertex[0] >= len(records.get(3, [])) or vertex[1] >= normals:
            issues.append({'severity': 'error', 'lump': 75, 'record': index,
                           'message': 'position or normal reference outside lump'})
        if not all(math.isfinite(value) for value in (*vertex[2:4], *vertex[8:])):
            issues.append({'severity': 'error', 'lump': 75, 'record': index,
                           'message': 'nonfinite Blinn-Phong UV or tangent quaternion'})
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


def check_tf1_mesh_metadata(records):
    issues = []
    spans = {}
    sorts = records[82]
    vertex_types = {0: 1, 0x200: 2, 0x400: 0, 0x600: 3}
    for index, mesh in enumerate(records[80]):
        material, flags = mesh[-2:]
        if mesh[4] & 0xff != vertex_types[flags & 0x600]:
            issues.append({'severity': 'error', 'lump': 80, 'record': index,
                           'message': 'v29 mesh vertex type disagrees with its vertex pool flags'})
        if not 0 <= material < len(sorts):
            continue
        first = mesh[2]
        last = first + mesh[3]
        low, high = spans.get(material, (first, last))
        spans[material] = min(low, first), max(high, last)
    for material, (first, last) in spans.items():
        if sorts[material][3] & 0xffff != last - first:
            issues.append({'severity': 'error', 'lump': 82, 'record': material,
                           'message': 'v29 material sort span disagrees with its mesh vertex ranges'})
    return issues


def check_tf1_records(records, inventory):
    """Known v29 auxiliary layouts; no claim about RTL channel meanings."""
    issues = (check_tf1_csm_records(records) + check_tf1_shadow_records(records)
              + check_tf1_mesh_metadata(records) + check_tf1_vertex_references(records))
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
        if probe != 0xffffffff and probe >= len(records[101]):
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
        entity_issues, report['entity_counts'] = check_tf1_entities(path, inventory)
        report['issues'].extend(entity_issues)
        report['issues'].extend(check_tf1_texture_strings(
            load_raw_payload(path, inventory, 43), records[44], records[2]))
        report['issues'].extend(check_tf1_physics(
            load_raw_payload(path, inventory, 29), len(records[14]), len(records[92])))
        game_issues, report['static_prop_count'] = check_tf1_game_lump(
            load_raw_payload(path, inventory, 35), inventory['lumps'][35]['offset'], records)
        report['issues'].extend(game_issues)
        report['issues'].extend(check_tf1_pakfile(load_raw_payload(path, inventory, 40)))
        report['issues'].extend(check_tf1_rtl(load_raw_payload(path, inventory, 105), records[54]))
    if inventory["version_raw"] == 37:
        report["game_lump"] = inspect_game_lump(path, inventory=inventory)
        # Minimal synthetic fixtures may have no visibility data at all.
        if records[123] or records[120]:
            prop_count = sum(e.get('placement_count',0) for e in report['game_lump']['entries'])
            report['issues'].extend(check_tf2_object_references(records,prop_count))
    report["issues"].extend(check_portal_records(records, inventory["version_raw"]))
    # Warnings note retail differences the engine tolerates; callers gate on issues.
    report["warnings"] = [i for i in report["issues"] if i["severity"] == "warning"]
    report["issues"] = [i for i in report["issues"] if i["severity"] != "warning"]
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
