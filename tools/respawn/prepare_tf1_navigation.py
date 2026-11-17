#!/usr/bin/env python3
"""Compile an original v29 obstacle/node fixture; this does not certify AI routing.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No retail geometry, models or navigation graphs are included.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid

from compiler_regression import box, entity
from validate_records import validate


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'assets/shaders').mkdir(parents=True)
    (output / 'maps').mkdir()
    name = 'mp_ares_nav_' + uuid.uuid4().hex[:8]
    material = 'world/concrete/concrete_floor_01'
    shader = f'textures/{material}\n{{\n $shadertype LitBumpGeneric\n}}\n'
    (output / 'assets/shaders/probe.shader').write_bytes(shader.encode('utf-8'))
    geometry = (box((-768, -512, -32), (768, 512, 0), material) + '\n' +
                box((-48, -128, 0), (48, 128, 192), material))
    text = '{\n"classname" "worldspawn"\n' + geometry.replace('compat/' + material, material) + '\n}\n'
    for team in (2, 3):
        for cls in ('info_spawnpoint_human_start', 'info_spawnpoint_human'):
            text += entity(classname=cls, origin='-600 -400 16', teamnum=str(team),
                           teamnumber=str(team), ignoreGamemode='1', gamemode_tdm='1')
    nodes = [(-400, 0, 8), (-256, -256, 8), (0, -256, 8), (256, -256, 8),
             (400, 0, 8), (-256, 256, 8), (0, 256, 8), (256, 256, 8)]
    for index, point in enumerate(nodes):
        text += entity(classname='info_node', origin=' '.join(map(str, point)),
                       targetname='ares_nav_' + str(index))
    source = output / 'maps' / (name + '.map')
    source.write_bytes(text.encode('utf-8'))
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath',
               str(output.resolve()), '-bsp', str(source.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    report = validate(source.with_suffix('.bsp'))
    (output / 'static.json').write_bytes(json.dumps(report, indent=2).encode('utf-8'))
    if report['issues']:
        raise ValueError('compiled navigation fixture failed structural validation')
    layout = dict(map=name, nodes=nodes, npc_start=[-400, 0, 1], goal=[400, 0, 0],
                  obstacle_min=[-48, -128, 0], obstacle_max=[48, 128, 192],
                  verification='structural only; native graph build and obstacle routing required')
    (output / 'layout.json').write_bytes(json.dumps(layout, indent=2).encode('utf-8'))
    manifest = dict(command=command, compiler_sha256=hashlib.sha256(remap.read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    bsp_sha256=hashlib.sha256(source.with_suffix('.bsp').read_bytes()).hexdigest())
    (output / 'manifest.json').write_bytes(json.dumps(manifest, indent=2).encode('utf-8'))
    return layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    layout = prepare(args.remap, args.output)
    print(f'Compiled {layout["map"]}; AI navigation remains unverified')


if __name__ == '__main__':
    main()
