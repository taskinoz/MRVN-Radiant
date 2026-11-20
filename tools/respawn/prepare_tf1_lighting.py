#!/usr/bin/env python3
"""Compile an original v29 lighting and shadow fixture with camera views.

A grey yard under a skybox, lit by a sun, with stations for each kind of
light remap writes: a pillar for sun (CSM) shadows; a roofed bay with a baked
point light on one side and a realtime point light on the other; and a
"realtime_shadows" "1" spotlight over a block. Every material is in
englishclient_mp_common (world/dev/dev_gray_512, tools/toolsskybox), so the
map renders in R1Delta without staged assets. Rays check the floor and roof.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box

GREY = 'world/dev/dev_gray_512'
SKY = 'tools/toolsskybox'


def brush(lo, hi, material=GREY):
    return box(lo, hi, material).replace('compat/' + material, material)


def entity(**keys):
    return '{\n' + ''.join(f'"{k}" "{v}"\n' for k, v in keys.items()) + '}\n'


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    shaders = output / 'assets/shaders'
    shaders.mkdir(parents=True)
    (shaders / 'lighting.shader').write_text(
        f'textures/{GREY}\n{{\n $shadertype LitBumpGeneric\n}}\n'
        f'textures/{SKY}\n{{\n $shadertype UnlitGeneric\n $compileflag sky\n $surfaceflag sky\n}}\n',
        encoding='utf-8')
    maps = output / 'maps'
    maps.mkdir()
    world = [brush((-1536, -1536, -32), (1536, 1536, 0))]
    # Sky shell.
    world += [brush(lo, hi, SKY) for lo, hi in (
        ((-1600, -1600, -32), (-1536, 1600, 1024)), ((1536, -1600, -32), (1600, 1600, 1024)),
        ((-1536, -1600, -32), (1536, -1536, 1024)), ((-1536, 1536, -32), (1536, 1600, 1024)),
        ((-1600, -1600, 1024), (1600, 1600, 1088)))]
    world.append(brush((-32, -32, 0), (32, 32, 256)))  # sun-shadow pillar
    # Roofed bay with a dividing wall: baked light at y<0, realtime at y>0.
    world += [brush((512, -320, 192), (1024, 320, 208)),
              brush((512, -320, 0), (528, 320, 192)), brush((1008, -320, 0), (1024, 320, 192)),
              brush((528, -320, 0), (1008, -304, 192)), brush((528, -8, 0), (1008, 8, 192))]
    world.append(brush((-800, -32, 0), (-736, 32, 64)))  # block under the spotlight
    # Roofed, three-walled stall around the spotlight so the sun cannot wash out its pool.
    world += [brush((-1100, -300, 400), (-436, 300, 416)),
              brush((-1100, -300, 0), (-1084, 300, 400)), brush((-452, -300, 0), (-436, 300, 400)),
              brush((-1084, 284, 0), (-452, 300, 400))]
    lights = (entity(classname='light_environment', origin='0 0 900', pitch='-50', angles='50 40 0',
                     _light='255 240 220 400', _ambient='150 170 200 40') +
              entity(classname='light', origin='768 -160 120', _light='255 180 120 300', _distance='320',
                     realtime='0') +
              entity(classname='light', origin='768 160 120', _light='120 180 255 300', _distance='320') +
              entity(classname='light_spot', origin='-768 0 320', pitch='-90', angles='90 0 0',
                     _light='255 255 255 600', _distance='500', _cone='40', _inner_cone='20',
                     realtime_shadows='1'))
    spawns = ''.join(entity(classname=kind, origin='-200 -900 32', teamnumber=team, ignoreGamemode=1,
                            gamemode_tdm=1, angles='0 90 0')
                     for team in (2, 3) for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start'))
    path = maps / 'mp_tf1_lighting.map'
    path.write_text('{\n"classname" "worldspawn"\n' + '\n'.join(world) + '\n}\n' + lights + spawns,
                    encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    checks = {'traces': [[300, 300, 500, 300, 300, -32], [768, -160, 500, 768, -160, -32]],
              'expect': {'trace_z': [[0, -0.1, 0.1], [1, 207.9, 208.1]]},
              'views': [[-300, -1100, 360, 18, 75],   # yard overview: pillar shadow
                        [768, -280, 80, 10, 90],      # baked half of the bay
                        [768, 40, 80, 10, 90],        # realtime half of the bay
                        [-768, -420, 180, 25, 90]]}   # shadowed spotlight over the block
    (output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    manifest = {'command': command, 'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'views': ['yard and pillar sun shadow', 'baked point light (realtime 0)',
                          'realtime point light (flag 30)', 'realtime_shadows 1 spotlight (flag 14)'],
                'scope': 'Four reviewed views and two rays; no probe, prop or character lighting check.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.remap, args.output)


if __name__ == '__main__':
    main()
