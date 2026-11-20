#!/usr/bin/env python3
"""Compile an original v29 fixture with one wall panel per vertex format.

Retail TF1 uses lit-bump almost everywhere, lit-flat only for cheap water
tops and unlit for tool, sign and water-underside materials; no retail TF1
map has an unlit-TS or Blinn-Phong vertex. Each panel names a retail
material under a different $shadertype (a BSP stores the shader name as the
material, so they cannot share one), and one camera view shows whether the
runtime draws each vertex pool. Rays check that every panel also collides.
With --asset-source, the materials' VMT/VTF files are copied to
addon-assets/ for r1_harness.py --asset-files.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box

from tf1_assets import copy_files, material_files

MATERIAL = 'world/concrete/concrete_floor_01'
PANELS = (('LitBumpGeneric', 'world/concrete/colony_concrete_panel_b'),
          ('LitFlatGeneric', 'world/concrete/colony_concrete_panel_c'),
          ('UnlitGeneric', 'world/signs/sign_lit_transit_station'),
          ('UnlitTSGeneric', 'world/concrete/colony_concrete_panel_d'))
FORMATS = tuple(kind for kind, _ in PANELS)


def prepare(remap, output, asset_source=None):
    output.mkdir(parents=True, exist_ok=False)
    shaders = output / 'assets/shaders'
    shaders.mkdir(parents=True)
    (shaders / 'formats.shader').write_text(''.join(
        f'textures/{name}\n{{\n $shadertype {kind}\n}}\n' for kind, name in PANELS) +
        f'textures/{MATERIAL}\n{{\n $shadertype LitBumpGeneric\n}}\n', encoding='utf-8')
    maps = output / 'maps'
    maps.mkdir()
    world = [box((-1024, -1024, -64), (1024, 1024, 0), MATERIAL).replace('compat/' + MATERIAL, MATERIAL)]
    for i, (_, name) in enumerate(PANELS):
        x = -384 + 256 * i
        world.append(box((x, 256, 0), (x + 192, 288, 192), name).replace('compat/' + name, name))
    spawns = ''.join('{\n"classname" "' + kind + '"\n"origin" "0 -200 64"\n' + f'"teamnumber" "{team}"\n'
                     '"ignoreGamemode" "1"\n"gamemode_tdm" "1"\n}\n'
                     for team in (2, 3) for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start'))
    path = maps / 'mp_tf1_vertex_formats.map'
    path.write_text('{\n"classname" "worldspawn"\n' + '\n'.join(world) + '\n}\n' + spawns, encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    if asset_source is not None:
        found = material_files(asset_source, [MATERIAL] + [name for _, name in PANELS])
        if found['missing']:
            raise RuntimeError(f'materials missing from {asset_source}: {found["missing"]}')
        copy_files(found, output / 'addon-assets')
    # Downward rays onto each panel's top (z=192).
    traces = [[-288 + 256 * i, 272, 400, -288 + 256 * i, 272, -32] for i in range(len(FORMATS))]
    checks = {'traces': traces, 'views': [[0, -300, 120, 5, 90]],
              'expect': {'trace_z': [[i, 191.9, 192.1] for i in range(len(FORMATS))]}}
    (output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    manifest = {'command': command, 'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'panels_left_to_right': [list(panel) for panel in PANELS],
                'scope': 'One view of four vertex formats on one retail material, plus a ray per panel.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--asset-source', type=Path, help="Loose asset tree, e.g. Titanfall Online's assets_dump")
    args = parser.parse_args()
    prepare(args.remap, args.output, args.asset_source)


if __name__ == '__main__':
    main()
