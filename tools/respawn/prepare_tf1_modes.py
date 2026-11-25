#!/usr/bin/env python3
"""Compile an original v29 multi-mode fixture with retail-style spawn sets.

One floor carries every spawn class retail TF1 maps use, keyed for
Attrition (tdm), Capture the Flag (ctf), Last Titan Standing (lts),
Hardpoint (cp) and exfil as Angel City does: pilot and titan spawns and their
match-start variants, drop pods, dropship starts, frontlines, two team flag
spawns and three hardpoints with triggers and assault points. One checks
file per mode (checks-<mode>.json) asks ARES's r1_harness.py to start that
mode and confirm the game reports it; cp also checks hardpoint setup. This
is mode initialization, not a played match.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
References base-game models by name; no retail files are bundled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box, entity
from validate_records import validate

MODES = ('tdm', 'ctf', 'lts', 'cp', 'exfil')
ALL = {f'gamemode_{mode}': '1' for mode in MODES}
TEAMS = ((2, -1600), (3, 1600))  # team, side x


def spawns():
    text = ''
    for team, x in TEAMS:
        yaw = '0' if x < 0 else '180'
        keys = dict(teamnum=str(team), angles=f'0 {yaw} 0')
        for i, y in enumerate((-300, -100, 100, 300)):
            text += entity(classname='info_spawnpoint_human_start', origin=f'{x} {y} 16', **keys, **ALL)
            text += entity(classname='info_spawnpoint_human', origin=f'{x // 2} {y} 16', **keys,
                           gamemode_tdm='1', gamemode_ctf='1', gamemode_cp='1')
        for i, y in enumerate((-600, 600)):
            text += entity(classname='info_spawnpoint_titan_start', origin=f'{x} {y} 16', **keys,
                           model='models/dev/mp_titan_spawn_start.mdl', **ALL)
            text += entity(classname='info_spawnpoint_titan', origin=f'{x // 2} {y} 16', **keys,
                           gamemode_tdm='1', gamemode_ctf='1', gamemode_cp='1')
        text += entity(classname='info_spawnpoint_droppod_start', origin=f'{x} 0 16', **keys,
                       model='models/dev/mp_droppod_spawn_start.mdl', **ALL)
        text += entity(classname='info_spawnpoint_droppod', origin=f'{x // 2} 0 16', **keys, **ALL)
        text += entity(classname='info_spawnpoint_dropship_start', origin=f'{x} 800 140', **keys,
                       model='models/dev/mp_dropship_spawn_start.mdl', **ALL)
        # CTF flag spawns live in the BSP entity lump in every retail map.
        text += entity(classname='info_spawnpoint_flag', origin=f'{x + (200 if x < 0 else -200)} 0 0',
                       TeamNum=str(team))
    for i, x in enumerate((-800, 0, 800)):
        text += entity(classname='info_frontline', origin=f'{x} 0 16', teamnum='1', group='center',
                       spectrepoint='0', gamemode_tdm='1', gamemode_lts='1', gamemode_ctf='1')
    return text


def hardpoints():
    text = ''
    for group, x in (('A', -600), ('B', 0), ('C', 600)):
        name = 'mrvn_cp_' + group.lower()
        text += entity(classname='info_hardpoint', targetname=name, origin=f'{x} -500 0', angles='0 0 0',
                       hardpointGroup=group, hardpointName=group, triggerTarget=name + '_trigger',
                       target=name + '_assault*', nearTarget=name + '_assault*',
                       model='models/communication/terminal_com_station.mdl')
        text += (entity(classname='trigger_multiple', targetname=name + '_trigger', spawnflags='1')[:-2] +
                 box((x - 128, -628, 0), (x + 128, -372, 192), 'trigger') + '\n}\n')
        for index, (dx, dy) in enumerate(((-80, -80), (-80, 80), (80, -80), (80, 80))):
            text += entity(classname='assault_assaultpoint', targetname=f'{name}_assault{index}',
                           origin=f'{x + dx} {-500 + dy} 0', angles='0 0 0')
    return text


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'maps').mkdir()
    (output / 'assets/shaders').mkdir(parents=True)
    (output / 'assets/shaders/modes.shader').write_text(
        'textures/compat/solid\n{\n $shadertype LitBumpGeneric\n}\n'
        'textures/compat/trigger\n{\n $shadertype UnlitGeneric\n $compileflag nodraw\n'
        ' $contentflag nonsolid\n}\n', encoding='utf-8')
    source = ('{\n"classname" "worldspawn"\n' + box((-2048, -1024, -32), (2048, 1024, 0), 'solid') + '\n}\n' +
              spawns() + hardpoints())
    path = output / 'maps/mp_tf1_modes.map'
    path.write_text(source, encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    report = validate(path.with_suffix('.bsp'))
    (output / 'static.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['issues']:
        raise RuntimeError(f'compiled modes fixture failed validation: {report["issues"][:3]}')
    bsp_text = path.with_suffix('.bsp').read_bytes()
    spawn_text = (output / 'maps/mp_tf1_modes_spawn.ent').read_bytes()
    if b'info_spawnpoint_flag' not in bsp_text or b'info_spawnpoint_flag' in spawn_text:
        raise RuntimeError('flag spawns must be in the BSP entity lump, as in retail')
    for mode in MODES:
        check = {'mode': mode, **({'hardpoints': 3} if mode == 'cp' else {})}
        checks = {'mode_check': check, 'traces': [[0, 0, 256, 0, 0, -64]], 'expect': {'trace_z': [[0, -.1, .1]]}}
        (output / f'checks-{mode}.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    manifest = {'command': command, 'modes': list(MODES),
                'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'scope': 'Mode start and reported mode per mode; cp hardpoint setup. No match play.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.remap, args.output)


if __name__ == '__main__':
    main()
