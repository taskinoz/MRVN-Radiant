#!/usr/bin/env python3
"""Compile an original v29 brush/patch baseline and emit shared TFO/R1 checks.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box


def prepare(remap, output, omit_intermission=False):
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets/shaders'
    assets.mkdir(parents=True)
    material = 'world/concrete/concrete_floor_01'
    (assets / 'baseline.shader').write_text(
        f'textures/{material}\n{{\n $shadertype LitBumpGeneric\n}}\n', encoding='utf-8')
    maps = output / 'maps'
    maps.mkdir()
    path = maps / 'mp_tf1_baseline.map'
    patch = '{\npatchDef2\n{\n' + material + '\n( 3 3 0 0 0 )\n(\n' + '\n'.join(
        '( ' + ' '.join(f'( {x} {y} 128 {i / 2} {j / 2} )' for j, y in enumerate((-512, 0, 512))) + ' )'
        for i, x in enumerate((512, 1024, 1536))) + '\n)\n}\n}'
    path.write_text('{\n"classname" "worldspawn"\n' +
                    box((-1024, -1024, -64), (2048, 1024, 0), material).replace('compat/' + material, material) + '\n' + patch + '\n}\n' +
                    ''.join('{\n"classname" "' + kind + '"\n"origin" "-200 0 64"\n' +
                            f'"teamnumber" "{team}"\n"ignoreGamemode" "1"\n"gamemode_tdm" "1"\n}}\n'
                            for team in (2, 3) for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start')) +
                    ('' if omit_intermission else '{\n"classname" "info_intermission"\n"origin" "-200 0 64"\n}\n'), encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    traces, hulls, trace_z, hull_z = [], [], [], []
    for x, floor in ((0, 0), (1024, 128)):
        traces.append([x, 0, 384, x, 0, -32])
        trace_z.append([len(traces) - 1, floor, floor + .04])
        # Pilot and broad titan-sized boxes; extents are explicit test probes,
        # not a claim that these match every native stance/loadout.
        for width, height in ((16, 72), (48, 160)):
            hulls.append([x, 0, 384, x, 0, -32, -width, -width, 0, width, width, height])
            hull_z.append([len(hulls) - 1, floor, floor + .1])
    checks = {'traces': traces, 'hulls': hulls, 'drops': [[0, 0, 64], [1024, 0, 192]],
              'drop_models': ['models/containers/crate.mdl'] * 2,
              'drop_sequential': True, 'drop_samples': True, 'drop_wait': 5,
              'expect': {'trace_z': trace_z, 'hull_z': hull_z,
                         'drop_z': [[0, 0, 3], [1, 128, 131]]}}
    (output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    collision = {'traces': traces, 'hulls': hulls,
                 'expect': {'trace_z': trace_z, 'hull_z': hull_z}}
    (output / 'collision-checks.json').write_text(json.dumps(collision, indent=2) + '\n', encoding='utf-8')
    manifest = {'command': command, 'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'scope': 'Two downward rays, four box hulls, two sequential crate probes. No gameplay, lighting or buoyancy coverage.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--omit-intermission', action='store_true', help='Exercise the compiler camera fallback')
    args = parser.parse_args()
    prepare(args.remap, args.output, args.omit_intermission)
