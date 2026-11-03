#!/usr/bin/env python3
"""Repair a matching TF1->TF2 manual port and optionally rebake its existing UVs.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original implementation; provenance and limits: RESPAWN_MP_BOX.md.
Inputs are never edited. Requires the matching, locally installed v29 BSP.
"""
import argparse
import collections
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

from bake_direct import collision_brushes
from game_lump import ENTRY, PROP, decode_sprp_v13, parse_directory
from inspect_bsp import FormatError, inspect
from lighting import WORLD_FORMATS, inspect_lighting
from validate_records import load_records, validate

OLD_PROP = struct.Struct('<6f3H2B2h6f4b4Bif2I')


def lump(data, inv, index):
    e = inv['lumps'][index]
    return data[e['offset']:e['offset'] + e['length']]


def source_props(data, base):
    entries = parse_directory(data, base)
    if len(entries) != 1 or entries[0]['name'] != 'sprp' or entries[0]['version'] != 12:
        raise FormatError('Original must contain one uncompressed sprp v12 entry')
    e = entries[0]
    p = data[e['relative_offset']:e['relative_offset'] + e['length']]
    names, = struct.unpack_from('<I', p)
    cursor = 4 + names * 128
    if cursor + 4 > len(p):
        raise FormatError('Original model table exceeds sprp')
    leaves, = struct.unpack_from('<I', p, cursor)
    cursor += 4 + leaves * 2
    if cursor + 12 > len(p):
        raise FormatError('Original leaf table exceeds sprp')
    count, a, b = struct.unpack_from('<3I', p, cursor)
    cursor += 12
    if cursor + count * OLD_PROP.size != len(p):
        raise FormatError('Unsupported v12 prop size or trailing data')
    return p[:4 + names * 128], (count, a, b), [OLD_PROP.unpack_from(p, cursor + i * OLD_PROP.size) for i in range(count)]


def restore_props(original, original_base, port, port_base):
    names, counts, old = source_props(original, original_base)
    entries = parse_directory(port, port_base)
    if len(entries) != 1 or entries[0]['name'] != 'sprp' or entries[0]['version'] != 13:
        raise FormatError('Port must contain one sprp v13 entry')
    e = entries[0]
    p = port[e['relative_offset']:e['relative_offset'] + e['length']]
    if p[:len(names)] != names or tuple(struct.unpack_from('<3I', p, len(names))) != counts:
        raise FormatError('Original and port prop dictionaries/counts differ')
    cursor = len(names) + 12
    if len(p) not in (cursor + len(old) * PROP.size, cursor + len(old) * PROP.size + 4):
        raise FormatError('Port does not have the expected v13 prop extent')
    output = bytearray(names + struct.pack('<3I', *counts))
    changes = collections.Counter()
    unconverted = []
    for i, o in enumerate(old):
        r = PROP.unpack_from(p, cursor + i * PROP.size)
        if o[:6] != r[:6] or o[6] != r[7]:
            raise FormatError(f'Prop {i}: original and port placement identity differs')
        if not math.isfinite(o[28]) or o[28] <= 0:
            raise FormatError(f'Prop {i}: invalid original scale')
        # TF1 contents masks are 32-bit; TF2's two 16-bit fields need further
        # semantic mapping. Preserve the port's flags rather than truncate them.
        if o[29] or o[30]:
            unconverted.append({'prop': i, 'tf1_add': o[29], 'tf1_remove': o[30], 'retained_tf2': list(r[24:26])})
        # Restore only proven conversion defects. Keep the port's TF2 CPU/GPU
        # sentinels, flags, skin/cubemap and conditional lighting-origin bytes.
        converted = list(r)
        converted[6], converted[12] = o[28], o[18]
        converted[20:24] = o[23:27]
        for label, changed in [('scale', r[6] != converted[6]), ('fade_scale', r[12] != converted[12]),
                               ('diffuse_modulation', r[20:24] != converted[20:24])]:
            changes[label] += int(changed)
        output += PROP.pack(*converted)
    output += struct.pack('<I', 0)  # TF2's unknown-record trailer, absent in TF1
    decoded = decode_sprp_v13(bytes(output), True)
    return bytes(output), decoded, {'restored': dict(changes), 'unmapped_collision_masks': unconverted}


def recover_zip(data, inv):
    entry = inv['lumps'][40]
    start = entry['offset']
    if data[start:start+4] != b'PK\x03\x04':
        if start < 4 or data[start-4:start] != b'PK\x03\x04':
            raise FormatError('Embedded ZIP has no supported recoverable signature')
        start -= 4
    limit = min((e['offset'] for e in inv['lumps'] if e['length'] and e['offset'] > entry['offset']), default=len(data))
    endrec = data.rfind(b'PK\x05\x06', start, limit)
    if endrec < start or endrec + 22 > limit:
        raise FormatError('Embedded ZIP lacks a bounded end directory')
    end = endrec + 22 + struct.unpack_from('<H', data, endrec + 20)[0]
    if end > limit:
        raise FormatError('Embedded ZIP comment exceeds its available region')
    with zipfile.ZipFile(io.BytesIO(data[start:end])) as archive:
        if archive.testzip() is not None:
            raise FormatError('Embedded ZIP member CRC failed')
        members = {e.filename: hashlib.sha256(archive.read(e)).hexdigest() for e in archive.infolist()}
    return start, end-start, members


def texture_names(data, inv):
    strings = lump(data, inv, 43)
    return [strings[o:strings.index(0, o)].decode('ascii').replace('\\', '/').lower()
            for (o,) in struct.iter_unpack('<I', lump(data, inv, 44))]


def bake_input(path, data, inv, records, lights):
    pages = list(struct.iter_unpack('<I2H', lump(data, inv, 83)))
    charts = []
    first, count = records[14][0][6:8]
    for mesh in records[80][first:first+count]:
        sort = records[82][mesh[-2]]
        if sort[1] < 0 or mesh[-1] & 0x600 >= 0x400:
            continue
        pool = records[73 if mesh[-1] & 0x600 == 0x200 else 72]
        vertices, indices, remap = [], [], {}
        for (index,) in records[79][mesh[0]:mesh[0]+mesh[1]*3]:
            key = sort[4] + index
            if key not in remap:
                remap[key] = len(vertices)
                v = pool[key]
                _, w, h = pages[sort[1]]
                vertices.append((*records[3][v[0]], *records[30][v[1]], v[8]*w, v[9]*h))
            indices.append(remap[key])
        charts.append((sort[1], vertices, indices))
    names = texture_names(data, inv)
    brushes = []
    for record, brush in zip(records[92], collision_brushes(records)):
        side = 6 * record[5] + record[9]
        materials = [names[records[94][i][0] & 0x1ff]
                     for i in range(side, side+record[4]+6)]
        # Clip/trigger/sky geometry must not darken the visible map.
        if any('sky' in m for m in materials) or all(m.startswith('tools/') for m in materials):
            continue
        brushes.append(brush)
    old_refs = list(struct.iter_unpack('<3fI', lump(data, inv, 104)))
    points = list(dict.fromkeys(r[:3] for r in old_refs))
    if not points or len(points) > 65535:
        raise FormatError('Missing or oversized original probe position set')
    ambient = next((r[3:6] for r in lights if r[13] == 5), (0, 0, 0))
    with path.open('xb') as stream:
        stream.write(struct.pack('<4s5I3d', b'RBL1', len(pages), len(charts), len(lights), len(brushes), len(points), *ambient))
        for _, w, h in pages:
            stream.write(struct.pack('<2I', w, h))
        hardware = 0
        for l in lights:
            kind = l[13]
            if kind not in (1, 2, 3, 5):
                raise FormatError(f'Unsupported light kind {kind}')
            stream.write(struct.pack('<2i2I15d', kind, hardware if kind != 5 else -1, kind != 5, kind != 5,
                                     *l[:3], *l[6:9], *l[3:6], l[18], *l[19:22], *l[15:17]))
            hardware += kind != 5
        for page, vertices, indices in charts:
            stream.write(struct.pack('<3I', page, len(vertices), len(indices)))
            for v in vertices:
                stream.write(struct.pack('<8d', *v))
            stream.write(struct.pack('<'+'I'*len(indices), *indices))
        for (mins, maxs), planes in brushes:
            stream.write(struct.pack('<I6d', len(planes), *mins, *maxs))
            for plane in planes:
                stream.write(struct.pack('<4d', *plane))
        for p in points:
            stream.write(struct.pack('<3d', *p))
    return points, {'charts': len(charts), 'occluding_brushes': len(brushes), 'probe_positions': len(points)}


def append(data, index, version, payload):
    at = (len(data) + 15) & ~15
    data += bytes(at - len(data)) + payload
    struct.pack_into('<4I', data, 16 + 16 * index, at, len(payload), version, 0)
    return at


def repair_bsp(source, original, output, bridge=None):
    data, old = bytearray(source.read_bytes()), original.read_bytes()
    inv, oi = inspect(source), inspect(original)
    if inv['version_raw'] != 37 or oi['version_raw'] != 29 or inv['byte_order'] != 'little' or oi['issues']:
        raise FormatError('Repair needs a v37 port and structurally valid matching v29 original')
    if any(e['external_files'] or e['fourcc'] for e in inv['lumps']):
        raise FormatError('External/encoded lump inputs are unsupported')
    for index in (1, 2, 3, 14, 30, 43, 44, 79, 80, 82, 85, 92, 99, 124, 126, 127):
        if lump(data, inv, index) != lump(old, oi, index):
            raise FormatError(f'Lump {index}: original and port do not have matching geometry/materials')
    zip_start, zip_length, members = recover_zip(data, inv)
    props, decoded, prop_report = restore_props(lump(old, oi, 35), oi['lumps'][35]['offset'],
                                               lump(data, inv, 35), inv['lumps'][35]['offset'])
    before_hash = hashlib.sha256(data).hexdigest()
    struct.pack_into('<2I', data, 16+40*16, zip_start, zip_length)
    at = (len(data)+15) & ~15
    game = struct.pack('<I', 1) + ENTRY.pack(b'prps', 0, 13, at+20, len(props)) + props
    append(data, 35, 0, game)
    report = {'source_sha256': before_hash, 'original_sha256': hashlib.sha256(old).hexdigest(),
              'props': prop_report, 'prop_count': decoded['placement_count'], 'embedded_zip_members': members,
              'embedded_zip': {'old_offset': inv['lumps'][40]['offset'], 'offset': zip_start, 'length': zip_length},
              'relit': False}
    if bridge:
        r = load_records(source, inv)
        lights = list(struct.iter_unpack('<'+WORLD_FORMATS[inv['lumps'][54]['version']], lump(data, inv, 54)))
        input_path, prefix = output.with_suffix('.rbl'), output.with_suffix('.bake')
        points, details = bake_input(input_path, data, inv, r, lights)
        baked = subprocess.run([str(bridge.resolve()), str(input_path), str(prefix)], capture_output=True, text=True, check=True)
        report['bake'] = {**details, **json.loads(baked.stdout)}
        # Upgrade world-light flags/stride, retaining original light order and
        # every physical parameter. TF2 hardware indices skip the ambient row.
        new_lights = bytearray()
        sun = None
        for light in lights:
            light = list(light[:25])
            light[22] = 24 if light[13] == 3 else (0 if light[13] == 5 else 28)
            new_lights += struct.pack('<'+WORLD_FORMATS[3], *light, 0, 0, int(light[13] == 2))
            if light[13] == 3:
                if sun is not None:
                    raise FormatError('Relighter currently supports one sun environment')
                sun = light[6:9]
        if sun is None:
            raise FormatError('Relighter requires the original sun direction')
        append(data, 54, 3, new_lights)
        suffixes = {98: '.sky', 105: '.rtl', 122: '.pages', 101: '.probes', 103: '.tree', 104: '.refs'}
        for index, suffix in suffixes.items():
            append(data, index, 0, Path(str(prefix)+suffix).read_bytes())
        b = report['bake']
        append(data, 4, 0, struct.pack('<i6I', 0, 0, b['probes'], 0, b['probe_references'], 0, b['probe_nodes']))
        indices = []
        for prop in decoded['placements']:
            indices.append(min(range(len(points)), key=lambda j: sum((points[j][a]-prop['origin'][a])**2 for a in range(3))))
        append(data, 102, 0, struct.pack('<'+'I'*len(indices), *indices))
        # The port's two copied environments cover only 1/31 CSM nodes and
        # 2/13 meshes, and point along a different sun. Bind the full original
        # world shadow tree/meshes to the actual map sun.
        env = struct.pack('<6i3f', 0, 0, 0, inv['lumps'][99]['length']//32,
                          inv['lumps'][100]['length']//2, inv['lumps'][127]['length']//12, *sun)
        append(data, 5, 0, env)
        report['relit'] = True
    with output.open('xb') as stream:
        stream.write(data)
    result = validate(output)
    if result['issues']:
        raise FormatError(f'Repaired BSP failed validation: {result["issues"][:3]}')
    report['validation'] = result
    report['lighting'] = inspect_lighting(output)
    report['output_sha256'] = hashlib.sha256(data).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mod', type=Path, required=True)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--relight-bridge', type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    if root.exists() or root.is_relative_to(args.mod.resolve()):
        raise ValueError('Output must be a new directory outside the original mod')
    if any(p.is_symlink() for p in args.mod.rglob('*')):
        raise ValueError('Mod contains symlinks; refusing recursive copy')
    root.mkdir(parents=True)
    folder = root / args.mod.name
    shutil.copytree(args.mod, folder)
    source = args.mod / 'mod/maps/mp_box.bsp'
    report = repair_bsp(source, args.original, root/'mp_box.bsp', args.relight_bridge)
    shutil.copyfile(root/'mp_box.bsp', folder/'mod/maps/mp_box.bsp')
    metadata_path = folder/'mod.json'
    metadata = json.loads(re.sub(r',\s*([}\]])', r'\1', metadata_path.read_text()))
    metadata['Version'] = '0.1.0-mrvn.1'
    metadata['Description'] += '; MRVN binary/prop repair' + (' and native TF2 relighting' if report['relit'] else '')
    metadata_path.write_text(json.dumps(metadata, indent=2)+'\n')
    report['original_author'] = metadata['Name']
    report['runtime_verified'] = False
    (root/'repair-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'mod': str(folder), 'report': str(root/'repair-report.json'), 'relit': report['relit'], 'props': report['props']}, indent=2))


if __name__ == '__main__':
    main()
