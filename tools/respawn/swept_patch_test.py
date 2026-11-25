#!/usr/bin/env python3
"""Stage TF1/TF2 patch/brush sweep comparisons and geometric diagnostics.

GPL-2.0-or-later. Builds and packages only: never installs or launches a game.
Uses stock material names; game assets are not copied into the package.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

from compiler_regression import box, entity, triangle_prism
from inspect_bsp import inspect
from swept_box import sweep_mesh
from swept_capsule import sweep_capsule_mesh
from validate_records import load_records, validate

LEVEL = 'mp_mrvn_sweptpatch'
MOD = 'MRVN.SweptPatchTest'


def scene():
    patches, triangles = [], []
    for index, kind in enumerate(('flat', 'slope', 'ridge', 'valley', 'dome', 'small')):
        coordinates = (-128, 128, 128) if kind == 'small' else (-128, 0, 128)
        points = []
        for ix, x in enumerate(coordinates):
            row = []
            for iy, y in enumerate(coordinates):
                z = {'flat': 64, 'small': 64, 'slope': 64+x/4,
                     'ridge': 64-abs(x)/4, 'valley': 32+abs(x)/4,
                     'dome': 32+((0,16,0),(16,64,16),(0,16,0))[ix][iy]}[kind]
                row.append((index*512+x, y, z))
            points.append(row)
        faces = []
        for x in range(2):
            for y in range(2):
                corners = (points[x][y], points[x][y+1], points[x+1][y+1], points[x+1][y])
                for a,b,c in ((0,1,2),(0,2,3)):
                    tri = (corners[a],corners[b],corners[c])
                    if len(set(tri)) == 3:
                        faces.append(tri)
        patches.append({'name': kind, 'points': points})
        triangles.append(faces)
    return patches, triangles


def cases_for(patches, triangles):
    cases = []
    counters = {'TRACE':0, 'HULL':0}
    for index, patch in enumerate(patches):
        offset = index*512
        samples = []
        for half in (0,8,16):
            for x,y in ((-96,-96),(-32,32),(0,0),(96,96),(-132,0),(132,0),(-145,0),(145,0)):
                samples.append(((offset+x,y,192),(offset+x,y,-32),(-half,-half,0),(half,half,72 if half else 0)))
        for direction in (-1,1):
            samples.append(((offset-direction*160,32,192),(offset+direction*160,32,-32),(-8,-8,0),(8,8,32)))
        for start,end,mins,maxs in samples:
            contact = sweep_mesh(start,end,mins,maxs,triangles[index])
            fraction = 1.0 if contact is None else contact
            kind = 'TRACE' if mins == maxs else 'HULL'
            cases.append({'patch':patch['name'], 'row':[*start,*end,*mins,*maxs], 'fraction':fraction,
                          'z':start[2]+fraction*(end[2]-start[2]), 'kind':kind,
                          'native_index':counters[kind]})
            counters[kind] += 1
    return cases


def patch_text(points, material):
    rows = ['( ' + ' '.join('( %.6f %.6f %.6f 0 0 )' % point for point in row) + ' )' for row in points]
    return '{\npatchDef2\n{\n'+material+'\n( 3 3 0 0 0 )\n(\n'+'\n'.join(rows)+'\n)\n}\n}'


def native_script(cases):
    rows = ',\n'.join('['+', '.join(f'{v:.6f}' for v in case['row'])+']' for case in cases)
    return ("""global function CodeCallback_MapInit
void function CodeCallback_MapInit()
{
 ClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )
 ClassicMP_ForceDisableEpilogue( true )
 Riff_ForceTitanAvailability( eTitanAvailability.Never )
 thread SweptPatchSmoke()
}
void function SweptPatchSmoke()
{
 wait 0.1
 array< array<float> > rows = [
%ROWS%
 ]
 foreach ( int i, array<float> t in rows )
 {
  TraceResults r
  if ( t[6] == t[9] && t[7] == t[10] && t[8] == t[11] )
   r = TraceLine( <t[0],t[1],t[2]>, <t[3],t[4],t[5]>, null, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
  else
   r = TraceHull( <t[0],t[1],t[2]>, <t[3],t[4],t[5]>, <t[6],t[7],t[8]>, <t[9],t[10],t[11]>, null, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
  printl( "[MRVN.Swept] CASE " + i + " fraction=" + r.fraction + " end=" + r.endPos.z + " solid=" + r.startSolid )
 }
 printl( "[MRVN.Swept] DONE" )
}
""").replace('%ROWS%',rows)


def build(remap, output, game, surface_mode="patches"):
    output.mkdir(parents=True, exist_ok=False)
    material = 'WORLD/DEV/DEV_GRAY_512' if game == 'titanfall2' else 'WORLD/CONCRETE/CONCRETE_INTERIORWALL_01'
    shaders = output/'assets/shaders'
    shaders.mkdir(parents=True)
    (shaders/'test.shader').write_text('textures/'+material+'\n{\n $shadertype LitBumpGeneric\n}\n')
    patches, triangles = scene()
    source = '{\n"classname" "worldspawn"\n'+box((-256,-256,-112),(2944,256,-96),material)+'\n'
    # box() prepends compat/; patch materials already use full native names.
    source = source.replace('compat/'+material,material)
    surfaces = ([patch_text(patch['points'],material) for patch in patches] if surface_mode == 'patches' else
                [triangle_prism(tri,-80,material) for faces in triangles for tri in faces])
    source += '\n'.join(surfaces)+'\n}\n'
    for team,x in ((2,-192),(3,2816)):
        for cls in ('info_spawnpoint_human_start','info_spawnpoint_human'):
            source += entity(classname=cls,origin=f'{x} 192 -88',angles='0 0 0',teamnum=str(team))
    path = output/(LEVEL+'.map')
    path.write_text(source)
    with (output/'build.log').open('wb') as log:
        subprocess.run([str(remap.resolve()),'-game',game,'-fs_basepath',str(output.resolve()),'-bsp',str(path)],
                       stdout=log,stderr=subprocess.STDOUT,check=True)
    report = validate(path.with_suffix('.bsp'))
    if report['issues']:
        raise ValueError(report['issues'])
    records = load_records(path.with_suffix('.bsp'),inspect(path.with_suffix('.bsp')))
    emitted = sorted(tuple(records[3][h[6]+v] for v in _indices(word))
                     for h in records[69] for word, in records[66][h[7]:h[7]+h[4]])
    expected = sorted(tuple(tri) for faces in triangles for tri in faces) if surface_mode == 'patches' else []
    if emitted != expected:
        raise ValueError('Authored and emitted collision triangles differ')
    cases = cases_for(patches,triangles)
    (output/'cases.json').write_text(json.dumps(cases,indent=2)+'\n')
    checks = {'traces':[], 'hulls':[], 'expect':{'trace_z':[], 'hull_z':[]}}
    for case in cases:
        key = 'traces' if case['kind'] == 'TRACE' else 'hulls'
        checks[key].append(case['row'][:6] if key == 'traces' else case['row'])
        checks['expect']['trace_z' if key == 'traces' else 'hull_z'].append([case['native_index'],case['z']-0.12,case['z']+0.12])
    (output/'box-checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    # Script hulls use native rounded-capsule semantics. Box expectations are a
    # separate diagnostic; use the native brush comparison to judge parity.
    del checks['expect']['hull_z']
    (output/'checks.json').write_text(json.dumps(checks,indent=2)+'\n')
    (output/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
    if game == 'titanfall2':
        mod = output/MOD
        maps = mod/'mod/maps';maps.mkdir(parents=True)
        for file in output.glob(LEVEL+'*'):
            if file.suffix in ('.bsp','.ent'): shutil.copyfile(file,maps/file.name)
        scripts = mod/'mod/scripts/vscripts/mp/levels';scripts.mkdir(parents=True)
        script = native_script(cases)
        if surface_mode == 'brushes': script = script.replace('[MRVN.Swept]', '[MRVN.SweptBrush]')
        (scripts/(LEVEL+'.nut')).write_text(script)
        (mod/'paks').mkdir()
        (mod/'paks/rpak.json').write_text(json.dumps({'Aliases':{LEVEL+'.rpak':'mp_coliseum.rpak',LEVEL+'_loadscreen.rpak':'mp_coliseum_loadscreen.rpak'}}))
        (mod/'mod.json').write_text(json.dumps({'Name':MOD,'Version':'0.1.0','LoadPriority':200,
            'Scripts':[{'Path':f'mp/levels/{LEVEL}.nut','RunOn':f'SERVER && MP && MAP_{LEVEL}'}]},indent=2))
        repo = Path(__file__).resolve().parents[2]
        shutil.copyfile(repo/'GPL',mod/'COPYING')
        shutil.copyfile(repo/'docs/respawn/RESPAWN_TRICOLL_PORTALS.md',mod/'SOURCES.md')
        shutil.copyfile(path,mod/path.name)
    return {'cases':len(cases),'headers':len(records[69]),'triangles':len(records[66])}


def _indices(word):
    # Kept outside the oracle. The comparison only ensures the compiler encoded
    # the authored geometry; sweep expectations are calculated from the source.
    from tricoll import triangle_indices
    return triangle_indices(word)


def verify(cases, text, game, tolerance=0.12):
    errors, results = [], []
    for i,case in enumerate(cases):
        prefix = rf'\[MRVN.Swept\] CASE {i}' if game == 'titanfall2' else rf'\[MRVN\] {case["kind"]} {case["native_index"]}'
        matches = re.findall(prefix+r' fraction=(\S+) end=(\S+) solid=(\S+)',text)
        valid = len(matches) == 1
        observed = None
        if valid:
            try:
                f,z = map(float,matches[0][:2])
                observed = {'fraction':f,'z':z,'start_solid':matches[0][2]}
                distance = math.dist(case['row'][:3],case['row'][3:6])
                observed['distance_error'] = abs(f-case['fraction'])*distance
                valid = (all(math.isfinite(v) for v in (f,z)) and 0 <= f <= 1 and
                         matches[0][2] == 'false' and abs(z-case['z']) <= tolerance and
                         observed['distance_error'] <= tolerance)
            except ValueError:
                valid = False
        result = {'case':i,'patch':case['patch'],'kind':case['kind'],'expected_z':case['z'], 'observed':observed,'passed':valid}
        results.append(result)
        if not valid: errors.append(result)
    done = '[MRVN.Swept] DONE' if game == 'titanfall2' else '[MRVN] DONE'
    if done not in text: errors.append({'message':'Run did not finish'})
    return {'cases':len(cases),'passed':len(results)-sum(not r['passed'] for r in results),'errors':errors,'results':results}


def compare_native(cases, baseline, reference, game, tolerance=0.12):
    # Compare two native representations of the same authored roof: triangle
    # collision and closed convex brush prisms. All sweeps approach from above.
    results, errors = [], []
    for i,case in enumerate(cases):
        observed = []
        for text,tag in ((baseline,'MRVN.Swept'),(reference,'MRVN.SweptBrush')):
            prefix = rf'\[{tag}\] CASE {i}' if game == 'titanfall2' else rf'\[MRVN\] {case["kind"]} {case["native_index"]}'
            matches = re.findall(prefix+r' fraction=(\S+) end=(\S+) solid=(\S+)',text)
            value = None
            if len(matches) == 1:
                try:
                    f,z = map(float,matches[0][:2])
                    if all(math.isfinite(v) for v in (f,z)) and 0 <= f <= 1 and matches[0][2] == 'false':
                        value = {'fraction':f,'z':z}
                except ValueError:
                    pass
            observed.append(value)
        a,b = observed
        valid = a is not None and b is not None
        if valid:
            distance = math.dist(case['row'][:3],case['row'][3:6])
            valid = abs(a['z']-b['z']) <= tolerance and abs(a['fraction']-b['fraction'])*distance <= tolerance
            if case['kind'] == 'TRACE':
                # Independent authored point-sweep anchors prevent two equally
                # missing or incorrectly placed collision surfaces from passing.
                valid = valid and all(abs(v['z']-case['z']) <= tolerance and
                                      abs(v['fraction']-case['fraction'])*distance <= tolerance for v in (a,b))
        result = {'case':i,'patch':case['patch'],'kind':case['kind'],'triangle':a,'brush':b,'passed':valid}
        results.append(result)
        if not valid: errors.append(result)
    for text,tag in ((baseline,'MRVN.Swept'),(reference,'MRVN.SweptBrush')):
        done = f'[{tag}] DONE' if game == 'titanfall2' else '[MRVN] DONE'
        if done not in text: errors.append({'message':'Native run did not finish','tag':tag})
    return {'cases':len(cases),'passed':sum(r['passed'] for r in results),'errors':errors,'results':results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    build_parser = sub.add_parser('build')
    build_parser.add_argument('--remap',type=Path,required=True)
    build_parser.add_argument('--output',type=Path,required=True)
    build_parser.add_argument('--game',choices=('titanfallonline','titanfall2'),required=True)
    build_parser.add_argument('--surface-mode',choices=('patches','brushes'),default='patches')
    check_parser = sub.add_parser('verify')
    check_parser.add_argument('--cases',type=Path,required=True)
    check_parser.add_argument('--log',type=Path,required=True)
    check_parser.add_argument('--output',type=Path,required=True)
    check_parser.add_argument('--game',choices=('titanfallonline','titanfall2'),required=True)
    check_parser.add_argument('--shape',choices=('box','capsule'),required=True,help='Ideal geometric reference; native finite-edge approximations can differ')
    compare_parser = sub.add_parser('compare')
    for name in ('cases','baseline','reference','output'):
        compare_parser.add_argument('--'+name,type=Path,required=True)
    compare_parser.add_argument('--game',choices=('titanfallonline','titanfall2'),required=True)
    args = parser.parse_args()
    if args.command == 'build':
        print(json.dumps(build(args.remap,args.output.resolve(),args.game,args.surface_mode),indent=2))
        return 0
    cases = json.loads(args.cases.read_text())
    if args.command == 'compare':
        report = compare_native(cases,args.baseline.read_text(errors='replace'),args.reference.read_text(errors='replace'),args.game)
    else:
        if args.shape == 'capsule':
            patches,triangles = scene()
            by_name = {patch['name']:faces for patch,faces in zip(patches,triangles)}
            for case in cases:
                row = case['row']
                hit = sweep_capsule_mesh(row[:3],row[3:6],row[6:9],row[9:],by_name[case['patch']])
                case['fraction'] = 1.0 if hit is None else hit
                case['z'] = row[2]+case['fraction']*(row[5]-row[2])
        report = verify(cases,args.log.read_text(errors='replace'),args.game)
        report['reference_shape'] = args.shape
        report['scope'] = 'Ideal geometry diagnostic; differences are not automatically compiler defects.'
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ('cases','passed','errors')},indent=2))
    return bool(report['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
