#!/usr/bin/env python3
"""Build original v29 contents-mask inclusion/exclusion probes for R1/TFO.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No game assets included. Requires an ARES adapter with per-probe trace masks.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box, entity
from validate_records import validate

MASKS = {'playersolid': 33636363, 'solid': 33570827, 'shot': 1178615811, 'water': 48}
CONTENTS = (('solid', 1), ('playerclip', 0x10000), ('bulletclip', 0x400000), ('water', 0x20))


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    shaders = output / 'assets/shaders'
    shaders.mkdir(parents=True)
    maps = output / 'maps'
    maps.mkdir()
    flags = {'solid': '', 'playerclip': '$contentflag playerclip',
             'bulletclip': '$contentflag bulletclip\n$contentflag blocklosclip',
             'water': '$contentflag nonsolid\n$contentflag water'}
    (shaders / 'probe.shader').write_text(''.join(
        f'textures/compat/{name}\n{{\n $shadertype LitBumpGeneric\n {value}\n}}\n'
        for name, value in flags.items()), encoding='utf-8')
    source = '{\n"classname" "worldspawn"\n' + box(
        (-1024, -256, -32), (1024, 256, 0), 'solid') + '\n'
    checks = {'traces': [], 'hulls': [], 'trace_masks': [], 'hull_masks': [],
              'expect': {'trace_z': [], 'hull_z': []}}
    for index, (name, bit) in enumerate(CONTENTS):
        x = -750 + index * 500
        source += box((x - 96, -96, 64), (x + 96, 96, 128), name) + '\n'
        for mask, bits in MASKS.items():
            checks['traces'].append([x, 0, 256, x, 0, -64])
            checks['trace_masks'].append(mask)
            checks['hulls'].append([x, 0, 256, x, 0, -64, -4, -4, -4, 4, 4, 4])
            checks['hull_masks'].append(mask)
            # If the column is excluded, hit the solid floor or miss everything.
            z = 128 if bits & bit else (0 if bits & 1 else -64)
            for key, offset in (('trace_z', 0), ('hull_z', 4 if z != -64 else 0)):
                checks['expect'][key].append([len(checks['traces']) - 1,
                                              z + offset - .1, z + offset + .1])
    source += '}\n'
    for team in (2, 3):
        for classname in ('info_spawnpoint_human_start', 'info_spawnpoint_human'):
            source += entity(classname=classname, origin='0 -180 32', teamnumber=str(team),
                             ignoreGamemode='1', gamemode_tdm='1')
    path = maps / 'mp_tf1_masks.map'
    path.write_text(source, encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath',
               str(output.resolve()), '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = validate(path.with_suffix('.bsp'))
    (output / 'static.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['issues']:
        raise RuntimeError(report['issues'])
    (output / 'checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    (output / 'build.json').write_text(json.dumps({
        'map': path.stem, 'command': command, 'masks': MASKS, 'contents': CONTENTS,
        'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
        'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
        'scope': '16 rays and 16 small hulls across solid/playerclip/bulletclip/water. '
                 'No actual bullets, titans, patch masks or gameplay acceptance.'}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.remap, args.output)
