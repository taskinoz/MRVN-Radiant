#!/usr/bin/env python3
"""Stage an original TF2 patch/doorway test mod; never installs or launches it.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Northstar APIs/stock RPAK alias convention: see RESPAWN_TRICOLL_PORTALS.md.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from compiler_regression import PATCH, entity, portal_fixture
from validate_records import validate

LEVEL = 'mp_mrvn_triportal'
SCRIPT = '''// Original MRVN-Radiant native smoke fixture. GPL-2.0-or-later.
global function CodeCallback_MapInit
void function CodeCallback_MapInit()
{
 ClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )
 ClassicMP_ForceDisableEpilogue( true )
 Riff_ForceTitanAvailability( eTitanAvailability.Never )
 thread TriPortalSmoke()
}
void function TriPortalSmoke()
{
 // Run before a disconnected Origin session can shut down the local server.
 wait 0.1
 TraceResults patchRay = TraceLine( < -96,-96,192>, < -96,-96,-8>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 printl( "[MRVN.TriPortal] patchRay " + patchRay.fraction + " " + patchRay.endPos )
 TraceResults patchHull = TraceHull( < -96,-96,192>, < -96,-96,-8>, < -8,-8,0>, <8,8,32>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 printl( "[MRVN.TriPortal] patchHull " + patchHull.fraction + " " + patchHull.endPos )
 TraceResults door = TraceLine( < -128,0,96>, <128,0,96>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 printl( "[MRVN.TriPortal] door " + door.fraction )
 TraceResults wall = TraceLine( < -128,96,96>, <128,96,96>, null, TRACE_MASK_SOLID_BRUSHONLY, TRACE_COLLISION_GROUP_NONE )
 printl( "[MRVN.TriPortal] wall " + wall.fraction )
 printl( "[MRVN.TriPortal] smoke completed" )
}
'''


def build(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets/shaders'
    assets.mkdir(parents=True)
    (assets / 'test.shader').write_text('textures/compat/bump\n{\n $shadertype LitBumpGeneric\n}\n')
    source = portal_fixture()[:-2] + PATCH + '\n}\n'
    for team, x in ((2, -192), (3, 192)):
        for cls in ('info_spawnpoint_human_start', 'info_spawnpoint_human'):
            source += entity(classname=cls, origin=f'{x} 0 80', angles='0 0 0', teamnum=str(team))
    path = output / (LEVEL + '.map')
    path.write_text(source, encoding='utf-8')
    with (output / 'build.log').open('wb') as log:
        subprocess.run([str(remap.resolve()), '-game', 'titanfall2', '-fs_basepath', str(output.resolve()),
                        '-bsp', str(path.resolve())], stdout=log, stderr=subprocess.STDOUT, check=True)
    report = validate(path.with_suffix('.bsp'))
    if report['issues']:
        raise ValueError(f'Compiled fixture failed validation: {report["issues"]}')
    mod = output / 'MRVN.TriPortalTest'
    maps = mod / 'mod/maps'
    maps.mkdir(parents=True)
    for file in output.glob(LEVEL + '*'):
        if file.suffix in ('.bsp', '.ent'):
            shutil.copyfile(file, maps / file.name)
    scripts = mod / 'mod/scripts/vscripts/mp/levels'
    scripts.mkdir(parents=True)
    (scripts / (LEVEL + '.nut')).write_text(SCRIPT)
    (mod / 'paks').mkdir()
    (mod / 'paks/rpak.json').write_text(json.dumps({'Aliases': {
        LEVEL + '.rpak': 'mp_coliseum.rpak', LEVEL + '_loadscreen.rpak': 'mp_coliseum_loadscreen.rpak'}}, indent=2))
    (mod / 'mod.json').write_text(json.dumps({'Name': 'MRVN.TriPortalTest', 'Version': '0.1.0',
        'LoadPriority': 200, 'Description': 'Original patch collision and brush portal smoke fixture.',
        'Scripts': [{'Path': f'mp/levels/{LEVEL}.nut', 'RunOn': f'SERVER && MP && MAP_{LEVEL}'}]}, indent=2))
    shutil.copyfile(path, mod / path.name)
    shutil.copyfile(assets / 'test.shader', mod / 'test.shader')
    repo = Path(__file__).resolve().parents[2]
    shutil.copyfile(repo / 'GPL', mod / 'COPYING')
    shutil.copyfile(repo / 'docs/respawn/RESPAWN_TRICOLL_PORTALS.md', mod / 'SOURCES.md')
    (output / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    return mod


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.remap, args.output.resolve()))


if __name__ == '__main__':
    main()
