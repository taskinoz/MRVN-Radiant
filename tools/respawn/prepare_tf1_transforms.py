#!/usr/bin/env python3
"""Compile analytic transformed brush/flat-patch collision probes for R1/TFO.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original geometry; references a retail material but includes no game assets.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

from compiler_regression import box, entity
from validate_records import validate


def surface_normal(angles):
    """Source pitch/yaw/roll applied to the local upward plane normal."""
    pitch, yaw, roll = map(math.radians, angles)
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    sr, cr = math.sin(roll), math.cos(roll)
    return (sp * cy * cr + sy * sr, sp * sy * cr - cy * sr, cp * cr)


def hull_support(normal, mins, maxs):
    """Distance of the hull's lowest support point below its origin along normal."""
    return -sum(min(normal[a] * mins[a], normal[a] * maxs[a]) for a in range(3))


def prepare(remap, output, patches=False):
    output.mkdir(parents=True, exist_ok=False)
    shaders = output / 'assets/shaders'
    shaders.mkdir(parents=True)
    material = 'world/concrete/concrete_floor_01'
    (shaders / 'probe.shader').write_text(
        f'textures/{material}\n{{\n $shadertype LitBumpGeneric\n}}\n', encoding='utf-8')
    source = '{\n"classname" "worldspawn"\n' + box(
        (-2048, -512, -32), (2048, 512, 0), material).replace('compat/' + material, material) + '\n}\n'
    patch = '{\npatchDef2\n{\n' + material + '\n( 3 3 0 0 0 )\n(\n' + '\n'.join(
        '( ' + ' '.join(f'( {x} {y} 16 {i / 2} {j / 2} )'
                        for j, y in enumerate((-192, 0, 192))) + ' )'
        for i, x in enumerate((-192, 0, 192))) + '\n)\n}\n}'
    checks = {'traces': [], 'hulls': [], 'expect': {'trace_z': [], 'hull_z': []}}
    cases = []
    orientations = ((0, 0, 0), (0, 45, 0), (30, 0, 0), (0, 0, 30), (20, 35, 15))
    for index, angles in enumerate(orientations):
        origin = (-1200 + index * 600, 0, 256)
        normal = surface_normal(angles)
        geometry = patch if patches else box((-192, -192, -16), (192, 192, 16), material).replace(
            'compat/' + material, material)
        # These fixtures deliberately author model-local geometry and an explicit
        # entity origin. They do not depend on editor-only common/origin brushes.
        source += '{\n"classname" "func_brush"\n"targetname" "transform_' + str(index) + \
                  '"\n"origin" "' + ' '.join(map(str, origin)) + '"\n"angles" "' + \
                  ' '.join(map(str, angles)) + '"\n"solid" "6"\n' + geometry + '\n}\n'
        start = [origin[a] + normal[a] * 160 for a in range(3)]
        end = [origin[a] - normal[a] * 100 for a in range(3)]
        checks['traces'].append(start + end)
        z = origin[2] + normal[2] * 16
        checks['expect']['trace_z'].append([index, z - .1, z + .1])
        for mins, maxs in (((-4, -4, -4), (4, 4, 4)),
                           ((-16, -16, 0), (16, 16, 72)),
                           ((-48, -48, 0), (48, 48, 160))):
            z = origin[2] + normal[2] * (16 + hull_support(normal, mins, maxs))
            checks['hulls'].append(start + end + list(mins) + list(maxs))
            checks['expect']['hull_z'].append([len(checks['hulls']) - 1, z - .1, z + .1])
        cases.append({'angles': angles, 'origin': origin, 'normal': normal})
    if patches:
        for trace in list(checks['traces']):
            checks['traces'].append(trace[3:] + trace[:3])
            z = trace[2]
            checks['expect']['trace_z'].append([len(checks['traces']) - 1, z - .01, z + .01])
    for team in (2, 3):
        for classname in ('info_spawnpoint_human_start', 'info_spawnpoint_human'):
            source += entity(classname=classname, origin='0 -320 64', teamnumber=str(team),
                             ignoreGamemode='1', gamemode_tdm='1')
    maps = output / 'maps'
    maps.mkdir()
    name = 'mp_tf1_transform_patch' if patches else 'mp_tf1_transform_brush'
    path = maps / (name + '.map')
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
    manifest = {'map': name, 'cases': cases, 'command': command,
                'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'scope': 'Five transformed func_brush models; analytic front rays and three hull sizes. '
                         'Flat patches additionally require backface rays to miss. No curved patches, '
                         'projectiles, gameplay titans, lighting or release acceptance.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--patches', action='store_true')
    args = parser.parse_args()
    prepare(args.remap, args.output, args.patches)
