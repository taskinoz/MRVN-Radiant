#!/usr/bin/env python3
"""Compile an original v29 Hardpoint initialization fixture for R1Delta/TFO.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
References base-game terminal assets; no retail files are bundled. This checks
mode/objective initialization, not capture, scoring, respawns or navigation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box, entity
from validate_records import validate


def prepare(remap, output, capture=False):
    output.mkdir(parents=True, exist_ok=False)
    (output/'maps').mkdir()
    (output/'assets/shaders').mkdir(parents=True)
    shader = ('textures/compat/solid\n{\n $shadertype LitBumpGeneric\n}\n'
              'textures/compat/trigger\n{\n $shadertype UnlitGeneric\n surfaceparm nodraw\n surfaceparm nonsolid\n}\n')
    (output/'assets/shaders/probe.shader').write_bytes(shader.encode('utf-8'))
    source = '{\n"classname" "worldspawn"\n' + box((-1024,-512,-32),(1024,512,0),'solid') + '\n}\n'
    for team in (2,3):
        for cls in ('info_spawnpoint_human_start','info_spawnpoint_human'):
            source += entity(classname=cls, origin='-400 -300 16', teamnumber=str(team), teamnum=str(team),
                             ignoreGamemode='1', gamemode_cp='1')
    for team,x in [(2,-850),(3,850)]:
        for cls in ('info_spawnpoint_droppod_start','info_spawnpoint_droppod'):
            source += entity(classname=cls, origin=f'{x} 300 0', teamnumber=str(team), teamnum=str(team),
                             ignoreGamemode='1', gamemode_cp='1')
    for group,x in [('A',-600),('B',0),('C',600)]:
        name = 'ares_cp_' + group.lower()
        source += entity(classname='info_hardpoint', targetname=name, origin=f'{x} 0 0', angles='0 0 0',
                         hardpointGroup=group, hardpointName=group, triggerTarget=name+'_trigger',
                         target=name+'_assault*', nearTarget=name+'_assault*',
                         model='models/communication/terminal_com_station.mdl')
        source += (entity(classname='trigger_multiple', targetname=name+'_trigger', spawnflags='1')[:-2] +
                   box((x-128,-128,0),(x+128,128,192),'trigger') + '\n}\n')
        for index,(dx,dy) in enumerate([(-80,-80),(-80,80),(80,-80),(80,80)]):
            source += entity(classname='assault_assaultpoint', targetname=name+'_assault'+str(index),
                             origin=f'{x+dx} {dy} 0', angles='0 0 0')
    path = output/'maps/mp_tf1_objectives.map'
    path.write_bytes(source.encode('utf-8'))
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output/'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    report = validate(path.with_suffix('.bsp'))
    (output/'static.json').write_bytes(json.dumps(report,indent=2).encode('utf-8'))
    if report['issues']:
        raise ValueError('compiled objective fixture failed structural validation')
    checks = {'mode_check': {'mode':'cp', 'hardpoints':3},
              'spawn_probe': {'origins':[[-400,-300,0]], 'tolerance':2},
              'traces':[[-900,-300,256,-900,-300,-64]], 'expect':{'trace_z':[[0,-.1,.1]]}}
    if capture:
        checks['cp_capture'] = dict(targetname='ares_cp_a', origin=[-600,-90,1])
    (output/'checks.json').write_bytes(json.dumps(checks,indent=2).encode('utf-8'))
    manifest = dict(command=command, compiler_sha256=hashlib.sha256(remap.read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    bsp_sha256=hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                    scope='Hardpoint initialization only; no capture/scoring/navigation acceptance',
                    required_base_game_model='models/communication/terminal_com_station.mdl')
    (output/'manifest.json').write_bytes(json.dumps(manifest,indent=2).encode('utf-8'))
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--capture',action='store_true',help='Include natural capture and team-score acceptance')
    args = parser.parse_args()
    prepare(args.remap,args.output,capture=args.capture)
    print(f'Compiled Hardpoint fixture and shared checks in {args.output}')


if __name__ == '__main__': main()
