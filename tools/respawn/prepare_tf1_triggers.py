#!/usr/bin/env python3
"""Compile original v29 trigger brushes with checks for R1Delta and TFO.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No game assets. Controlled repositioning verifies trigger outputs, not walking.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box, entity
from validate_records import validate


def prepare(remap, output, titans=False):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'assets/shaders').mkdir(parents=True)
    (output / 'maps').mkdir()
    shader = ('textures/compat/solid\n{\n $shadertype LitBumpGeneric\n}\n'
              'textures/compat/trigger\n{\n $shadertype UnlitGeneric\n surfaceparm nodraw\n surfaceparm nonsolid\n}\n')
    (output / 'assets/shaders/probe.shader').write_bytes(shader.encode('utf-8'))
    text = '{\n"classname" "worldspawn"\n' + box((-1024,-512,-32),(1024,768,0),'solid') + '\n}\n'
    for team in (2,3):
        for cls in ('info_spawnpoint_human_start','info_spawnpoint_human'):
            text += entity(classname=cls, origin='-400 0 16', teamnumber=str(team),
                           ignoreGamemode='1', gamemode_tdm='1')
    # An entity origin translates already-local brush geometry; this does not
    # use a common/origin brush to recenter world-authored coordinates.
    fixtures = [
        ('ares_trigger', (-96,-96,0),(96,96,160), None, None,
         [[-300,0,1],[0,0,1],[300,0,1]]),
        ('ares_rotated_trigger', (-160,-32,0),(160,32,160), '400 200 0', '0 45 0',
         [[400,400,1],[490,290,1],[490,110,1]]),
    ]
    checks = {'spawn_probe': {'origins': [[-400,0,0]], 'tolerance': 2}, 'triggers': []}
    if titans:
        checks['titans'] = [dict(origin=[0,500,256], team=2, floor_z=0)]
    for name, low, high, origin, angles, points in fixtures:
        keys = dict(classname='trigger_multiple',targetname=name,spawnflags='1',wait='0.1')
        if origin: keys.update(origin=origin, angles=angles)
        text += entity(**keys)[:-2] + box(low,high,'trigger') + '\n}\n'
        checks['triggers'].append(dict(targetname=name,points=points,counts=[[0,0],[1,0],[1,1]]))
    source = output / 'maps/mp_tf1_triggers.map'
    source.write_bytes(text.encode('utf-8'))
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath',str(output.resolve()), '-bsp',str(source.resolve())]
    with (output/'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    report = validate(source.with_suffix('.bsp'))
    (output/'static.json').write_bytes(json.dumps(report,indent=2).encode('utf-8'))
    if report['issues']: raise ValueError('compiled trigger fixture failed structural validation')
    (output/'checks.json').write_bytes(json.dumps(checks,indent=2).encode('utf-8'))
    manifest = dict(command=command, compiler_sha256=hashlib.sha256(remap.read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                    bsp_sha256=hashlib.sha256(source.with_suffix('.bsp').read_bytes()).hexdigest())
    (output/'manifest.json').write_bytes(json.dumps(manifest,indent=2).encode('utf-8'))
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--titans',action='store_true',help='Include a native atlas NPC support probe')
    args=parser.parse_args()
    prepare(args.remap,args.output,titans=args.titans)
    print(f'Compiled trigger fixture and checks in {args.output}')


if __name__ == '__main__': main()
