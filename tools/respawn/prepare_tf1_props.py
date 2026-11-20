#!/usr/bin/env python3
"""Compile an original v29 static-prop fixture and emit R1Delta checks.

Three prop_static barrels (upright, yawed and tipped over) stand on a floor.
remap needs a mesh it can read at compile time but the BSP must name the
engine's .mdl, so the fixture places a small OBJ stand-in at the model's path
under its own asset root (assimp falls back to detecting OBJ by content).
Rays dropped onto each barrel must stop on the prop, not the floor, and a
camera view records how they draw.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from prepare_tf1_physics import MATERIAL, brush

MODEL = 'models/containers/barrel.mdl'
# Upright barrel: 48 units tall, about 16 in radius (measured in R1Delta).
STAND_IN = ''.join(f'v {x} {y} {z}\n' for z in (0, 48) for x, y in ((-16, -16), (16, -16), (16, 16), (-16, 16))) + \
    'f 1 2 3 4\nf 8 7 6 5\nf 1 5 6 2\nf 2 6 7 3\nf 3 7 8 4\nf 4 8 5 1\n'
PROPS = (((0, 0, 0), (0, 0, 0)), ((160, 0, 0), (0, 45, 0)), ((320, 0, 16), (0, 0, 90)))


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets'
    (assets / 'shaders').mkdir(parents=True)
    (assets / 'shaders/props.shader').write_text(f'textures/{MATERIAL}\n{{\n $shadertype LitBumpGeneric\n}}\n',
                                                 encoding='utf-8')
    model = assets / MODEL
    model.parent.mkdir(parents=True)
    model.write_text(STAND_IN, encoding='utf-8')
    maps = output / 'maps'
    maps.mkdir()
    props = ''.join('{\n"classname" "prop_static"\n' + f'"model" "{MODEL}"\n"origin" "{x} {y} {z}"\n'
                    f'"angles" "{p} {yaw} {r}"\n}}\n' for (x, y, z), (p, yaw, r) in PROPS)
    spawns = ''.join('{\n"classname" "' + kind + f'"\n"origin" "160 -300 64"\n"teamnumber" "{team}"\n'
                     '"ignoreGamemode" "1"\n"gamemode_tdm" "1"\n}\n'
                     for team in (2, 3) for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start'))
    path = maps / 'mp_tf1_props.map'
    path.write_text('{\n"classname" "worldspawn"\n' + brush((-1024, -1024, -64), (1024, 1024, 0)) + '\n}\n' +
                    props + spawns, encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    if b'Emitting static prop' not in (output / 'compile.log').read_bytes():
        raise RuntimeError('remap did not emit the static props; see compile.log')
    # Upright and yawed barrels: top at 48. Tipped barrel lies along x at z=16
    # with its radius about 16, so its top is near 32. The floor answers 0.
    traces = [[0, 0, 200, 0, 0, -32], [160, 0, 200, 160, 0, -32], [320, 0, 200, 320, 0, -32], [0, 200, 200, 0, 200, -32]]
    checks = {'traces': traces, 'views': [[160, -260, 80, 10, 90]],
              'drops': [[0, 300, 40]], 'drop_models': ['models/containers/barrel.mdl'], 'drop_wait': 3,
              'expect': {'trace_z': [[0, 40, 50], [1, 40, 50], [2, 20, 40], [3, -0.1, 0.1]]}}
    (output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    manifest = {'command': command, 'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'scope': 'Three static barrels: placement, prop collision rays and one view. The drop only '
                         'stages the barrel model files for R1Delta.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.remap, args.output)


if __name__ == '__main__':
    main()
