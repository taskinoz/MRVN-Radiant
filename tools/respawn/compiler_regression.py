#!/usr/bin/env python3
"""Compile original regression geometry with an explicitly supplied remap binary.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No game assets required. Outputs and logs remain in a new working directory.
"""
import argparse
import json
import math
import re
from pathlib import Path
import struct
import subprocess

from inspect_bsp import inspect
from validate_records import load_records, validate
from game_lump import inspect_game_lump, relocate_bsp
from portals import locate_cell, connected
from tricoll import triangle_indices
from decompile_bsp import parse_entities


def brush(x, slope, materials):
    lo, hi, bottom, top = x, x + 64, 0, 128
    faces = [
        ((hi, 64, bottom), (lo, 64, bottom), (lo, 0, bottom)),
        ((lo, 0, top), (lo, 64, top), (hi, 64, 64 if slope else top)),
        ((lo, 0, top), (hi, 0, top), (hi, 0, bottom)),
        ((hi, 0, top), (hi, 64, top), (hi, 64, bottom)),
        ((hi, 64, top), (lo, 64, top), (lo, 64, bottom)),
        ((lo, 64, top), (lo, 0, top), (lo, 0, bottom)),
    ]
    lines = ["{"]
    for points, material in zip(faces, materials):
        coords = " ".join("( %.6f %.6f %.6f )" % p for p in points)
        lines.append(f"{coords} compat/{material} 0 0 0 1 1 0 0 0")
    return "\n".join(lines + ["}"])


def box(lo, hi, material):
    (lx, ly, lz), (hx, hy, hz) = lo, hi
    faces = [
        ((hx, hy, lz), (lx, hy, lz), (lx, ly, lz)),
        ((lx, ly, hz), (lx, hy, hz), (hx, hy, hz)),
        ((lx, ly, hz), (hx, ly, hz), (hx, ly, lz)),
        ((hx, ly, hz), (hx, hy, hz), (hx, hy, lz)),
        ((hx, hy, hz), (lx, hy, hz), (lx, hy, lz)),
        ((lx, hy, hz), (lx, ly, hz), (lx, ly, lz)),
    ]
    lines = ["{"]
    for points in faces:
        coords = " ".join("( %.6f %.6f %.6f )" % p for p in points)
        lines.append(f"{coords} compat/{material} 0 0 0 1 1 0 0 0")
    return "\n".join(lines + ["}"])


def triangle_prism(triangle, bottom, material):
    a,b,c = triangle
    low = [(v[0],v[1],bottom) for v in triangle]
    faces = [(a,b,c), (low[2],low[1],low[0])]
    faces += [(triangle[(i+1)%3],triangle[i],low[i]) for i in range(3)]
    return '\n'.join(['{',*(' '.join('( %.6f %.6f %.6f )' % v for v in face)+
                                ' '+material+' 0 0 0 1 1 0 0 0' for face in faces),'}'])


def entity(**keys):
    return "{\n" + "".join(f'"{k}" "{v}"\n' for k, v in keys.items()) + "}\n"


def portal_fixture(closed=False, sky=False):
    walls = [((-272, -144, -16), (272, 144, 0)),
             ((-272, -144, 256), (272, 144, 272)),
             ((-272, -144, 0), (-256, 144, 256)),
             ((256, -144, 0), (272, 144, 256)),
             ((-256, -144, 0), (256, -128, 256)),
             ((-256, 128, 0), (256, 144, 256))]
    divider = [((-8, -128, 0), (8, 128, 256))] if closed else [
        ((-8, -128, 0), (8, -48, 256)), ((-8, 48, 0), (8, 128, 256)),
        ((-8, -48, 128), (8, 48, 256))]
    return ('{\n"classname" "worldspawn"\n"_viewportals" "1"\n' +
            '\n'.join(box(lo, hi, 'sky' if sky and i == 1 else 'bump')
                      for i, (lo, hi) in enumerate(walls + divider)) + '\n}\n')


PATCH = '''{
patchDef2
{
compat/bump
( 3 3 0 0 0 )
(
( ( -128 -128 0 0 0 ) ( -128 0 16 0 0.5 ) ( -128 128 0 0 1 ) )
( ( 0 -128 16 0.5 0 ) ( 0 0 64 0.5 0.5 ) ( 0 128 16 0.5 1 ) )
( ( 128 -128 0 1 0 ) ( 128 0 16 1 0.5 ) ( 128 128 0 1 1 ) )
)
}
}'''


def check_triangle_z_order(records):
    for h in records[69]:
        for word, in records[66][h[7]:h[7] + h[4]]:
            z = [records[3][h[6] + i][2] for i in triangle_indices(word)]
            order = sorted(range(3), key=lambda i: (z[i], i))
            flags = word >> 28
            low = flags & 3
            if low > 2 or low != order[0]:
                raise RuntimeError('triangle collision has the wrong lowest-Z vertex')
            high = (1 & ~low, 2 & ~low)[(flags >> 2) & 1]
            if high != order[-1]:
                raise RuntimeError('triangle collision has the wrong highest-Z vertex or tie order')


def collision_portal_fixtures(folder, command, reports, game):
    for name, source in [('patch', '{\n"classname" "worldspawn"\n' + PATCH + '\n}\n'),
                         ('portal-open', portal_fixture()),
                         ('portal-closed', portal_fixture(True)),
                         ('portal-sky', portal_fixture(sky=True))]:
        path = folder / (name + '.map')
        path.write_text(source, encoding='utf-8')
        with path.with_suffix('.log').open('wb') as log:
            subprocess.run(command[:-1] + [str(path)], stdout=log, stderr=subprocess.STDOUT, check=True)
        bsp = path.with_suffix('.bsp')
        report = validate(bsp)
        if report['issues']:
            raise RuntimeError(f'{name}: {report["issues"]}')
        r = load_records(bsp, inspect(bsp))
        if name == 'patch':
            check_triangle_z_order(r)
            for vertex in r[73]:
                if r[30][vertex[1]][2] < .5:
                    raise RuntimeError('Upward patch render normal has the wrong orientation')
            centers = [r[30][v[1]] for v in r[73] if r[3][v[0]][:2] == (0,0)]
            if not centers or any(abs(n[0])+abs(n[1])+abs(n[2]-1) > 1e-5 for n in centers):
                raise RuntimeError('Symmetric patch center does not have its analytic upward normal')
            # One header for the patch's eight triangles, with 4 * ((8 + 3) // 6) nodes.
            if len(r[69]) != 1 or len(r[66]) != 8 or len(r[68]) != 4 or len(r[96]) != 8:
                raise RuntimeError('patch collision did not use one noded eight-triangle header')
            if not any(word >> 24 == 0x40 for _, count, word in r[87] if count == 1) and                     not any(word >> 24 == 0x40 for (word,) in r[89]):
                raise RuntimeError('patch collision is absent from the collision grid')
            # Independently compare emitted render triangles with collision positions.
            rendered = []
            for mesh in r[80]:
                first, count, sort = mesh[0], mesh[1], mesh[-2]
                base = r[82][sort][4]
                pool = r[73]  # LitBump
                for t in range(count):
                    rendered.append(tuple(r[3][pool[base + r[79][first + t*3 + j][0]][0]] for j in range(3)))
            collision = [tuple(r[3][h[6] + v] for v in triangle_indices(word))
                         for h in r[69] for (word,) in r[66][h[7]:h[7]+h[4]]]
            if sorted(rendered) != sorted(collision):
                raise RuntimeError('patch render and collision triangulations differ')
        else:
            a, b = (locate_cell(r, point) for point in ((-128, 0, 64), (128, 0, 64)))
            if a == b or connected(r, a, b) != (name != 'portal-closed'):
                raise RuntimeError(f'{name}: room separation/connectivity incorrect ({a}, {b})')
            if name == 'portal-sky' and not any(p[1] == 1 for p in r[108]):
                raise RuntimeError('authored sky aperture has no sky portal')
            for cell, (count, first, _, _) in enumerate(r[107]):
                for p in r[108][first:first+count]:
                    if p[1] != 0:
                        continue
                    other = r[107][p[5]]
                    if not any(q[1] == 0 and q[5] == cell and q[0] != p[0] and q[6] == p[6]
                               for q in r[108][other[1]:other[1]+other[0]]):
                        raise RuntimeError('missing reciprocal cell portal')
        reports.append({'game': game, 'fixture': name, 'issues': []})


def collision_brush_merge_fixtures(folder, command, reports, game):
    first = triangle_prism(((0,0,64),(0,64,64),(64,64,64)),0,'compat/bump')
    second = triangle_prism(((0,0,64),(64,64,64),(64,0,64)),0,'compat/bump')
    variants = [('convex',first+'\n'+second,1),
                ('material',first+'\n'+second.replace('compat/bump','compat/unlit'),2),
                ('mapping',first+'\n'+second.replace('compat/bump 0 0','compat/bump 8 0'),2),
                ('concave',box((0,0,0),(32,64,64),'bump')+'\n'+box((32,0,0),(64,32,64),'bump'),2),
                ('gap',box((0,0,0),(32,64,64),'bump')+'\n'+box((32.25,0,0),(64,64,64),'bump'),2)]
    if game == 'titanfall2': variants.append(('recovered',first+'\n'+second,2))
    for name,geometry,count in variants:
        path = folder/('brush-merge-'+name+'.map')
        recovered = '"_remap_contents_0" "1"\n"_remap_contents_1" "2"\n' if name == 'recovered' else ''
        path.write_text('{\n"classname" "worldspawn"\n'+recovered+geometry+'\n}\n')
        with path.with_suffix('.log').open('wb') as log:
            subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
        bsp = path.with_suffix('.bsp');inventory = inspect(bsp);r = load_records(bsp,inventory)
        if validate(bsp)['issues'] or len(r[92]) != count:
            raise RuntimeError(f'{name}: collision merging ignored geometry/material constraints')
        plane_base = r[85][0][-1]
        def inside(point):
            for brush in r[92]:
                if any(abs(point[a]-brush[a]) > brush[6+a]+1e-5 for a in range(3)):
                    continue
                planes = [r[1][plane_base+brush[9]+i-r[93][brush[9]+i][0]] for i in range(brush[4])]
                if all(sum(p[a]*point[a] for a in range(3)) <= p[3]+1e-5 for p in planes):
                    return True
            return False
        for x in (-0.25,0,16,32,32.125,48,64,64.25):
            for y in (-0.25,0,16,32,48,64,64.25):
                for z in (-0.25,0,32,64,64.25):
                    expected = 0<=x<=64 and 0<=y<=64 and 0<=z<=64
                    if name == 'concave': expected &= x<=32 or y<=32
                    if name == 'gap': expected &= x<=32 or x>=32.25
                    if inside((x,y,z)) != expected:
                        raise RuntimeError(f'{name}: merged collision changed its authored union at {(x,y,z)}')
        if name == 'recovered' and not {1,2}.issubset({value for value, in r[91]}):
            raise RuntimeError('Recovered per-brush collision contents changed during merging')
        if game == 'titanfallonline': physics_checks(bsp,inventory,2)
        reports.append({'game':game,'fixture':'brush-merge-'+name,'issues':[]})
    path = folder/'brush-merge-entity.map'
    path.write_text('{\n"classname" "worldspawn"\n'+brush(1024,True,['bump']*6)+'\n}\n'+
                    '{\n"classname" "func_brush"\n'+first+'\n'+second+'\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
    bsp = path.with_suffix('.bsp');inventory = inspect(bsp);r = load_records(bsp,inventory)
    if (validate(bsp)['issues'] or len(r[14]) != 2 or len(r[92]) != 2 or
            r[92][1][4] != (4 if game == 'titanfall2' else 0) or r[92][1][9] != r[92][0][4]):
        raise RuntimeError('Merged brush entity lost its model or cutting-plane prefix')
    if game == 'titanfallonline': physics_checks(bsp,inventory,2,model_index=1)
    reports.append({'game':game,'fixture':'brush-merge-entity','issues':[]})



def collision_brush_bevel_fixture(folder, command, reports, game):
    roof = ((0,0,0),(0,64,64),(64,0,32))
    wedge = triangle_prism(roof,-32,'compat/bump')
    path = folder/'brush-bevels.map'
    path.write_text('{\n"classname" "worldspawn"\n'+wedge+'\n}\n'+
                    '{\n"classname" "func_brush"\n'+box((1024,0,0),(1088,64,64),'bump')+'\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
    bsp = path.with_suffix('.bsp');inventory = inspect(bsp);r = load_records(bsp,inventory)
    if validate(bsp)['issues'] or len(r[92]) != 2:
        raise RuntimeError('Brush bevel fixture failed record validation')
    first,second = r[92]
    if not 0 < first[3] < first[4] or second[4] != (4 if game == 'titanfall2' else 0) or second[9] != first[4]:
        raise RuntimeError('Brush bevel count or subsequent brush plane prefix is incorrect')
    base = r[85][0][-1]
    if game == 'titanfall2':
        corner_planes = [r[1][base+second[9]+i-r[93][second[9]+i][0]] for i in range(second[4])]
        expected_normals = {(-1,1),(-1,-1),(1,-1),(1,1)}
        if second[3] != 0 or {(round(p[0]*math.sqrt(2)),round(p[1]*math.sqrt(2))) for p in corner_planes} != expected_normals:
            raise RuntimeError('TF2 axial box lacks its four distinct discarded corner planes')
        corners = [(x,y,z) for x in (1024,1088) for y in (0,64) for z in (0,64)]
        for i,p in enumerate(corner_planes):
            distances = [sum(p[a]*v[a] for a in range(3))-p[3] for v in corners]
            if abs(p[2]) > 1e-6 or abs(p[0]**2+p[1]**2-1) > 1e-6 or abs(max(distances)) > 1e-3:
                raise RuntimeError('TF2 corner plane does not support the authored box')
            if not r[94][6*second[5]+second[9]+6+i][0] & 0x4000:
                raise RuntimeError('TF2 corner plane lacks the native discard flag')
    vertices = [*roof,*((x,y,-32) for x,y,_ in roof)]
    for i in range(first[3],first[4]):
        plane = r[1][base+first[9]+i-r[93][first[9]+i][0]]
        distances = [sum(plane[a]*v[a] for a in range(3))-plane[3] for v in vertices]
        if max(distances) > 1e-4 or min(abs(d) for d in distances) > 1e-4:
            raise RuntimeError('Generated brush bevel cuts the source volume or does not support its boundary')
        prop = r[94][6*first[5]+first[9]+6+i][0]
        if not prop & 0x4000:
            raise RuntimeError('Generated brush bevel lacks the native discard flag')
    if game == 'titanfallonline': physics_checks(bsp,inventory,1,z_bounds=(-32,64))
    # Compare the native plane representation with independent triangle SAT.
    from swept_box import sweep_mesh, sweep_halfspaces
    low = [(x,y,-32) for x,y,_ in roof]
    faces = [tuple(roof),tuple(reversed(low))]
    for i in range(3):
        j = (i+1)%3
        faces.extend(((roof[i],roof[j],low[j]),(roof[i],low[j],low[i])))
    planes = []
    for axis in range(3):
        for sign in (-1,1):
            normal = [0,0,0];normal[axis] = sign
            planes.append((*normal,sign*first[axis]+first[6+axis]))
    for i in range(first[4]):
        planes.append(r[1][base+first[9]+i-r[93][first[9]+i][0]])
    authored = planes[:6+first[3]]
    missing_bevel_differences = 0
    for mins,maxs in (((-4,-8,0),(8,12,16)),((-16,-16,0),(16,16,32)),((-8,-24,-4),(8,24,20))):
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for dz in (-1,0,1):
                    if (dx,dy,dz)==(0,0,0):continue
                    start = (16+160*dx,16+160*dy,160*dz)
                    end = (16-160*dx,16-160*dy,-160*dz)
                    expected = sweep_mesh(start,end,mins,maxs,faces)
                    actual = sweep_halfspaces(start,end,mins,maxs,planes)
                    old = sweep_halfspaces(start,end,mins,maxs,authored)
                    distance = math.dist(start,end)
                    if expected is None or actual is None or abs(expected-actual)*distance>1e-3:
                        raise RuntimeError('Emitted brush bevel planes disagree with exact authored box-sweep contact')
                    missing_bevel_differences += old is None or abs(expected-old)*distance>1e-3
    if not missing_bevel_differences:
        raise RuntimeError('Brush bevel sweep fixture did not exercise a missing separating plane')
    reports.append({'game':game,'fixture':'native-brush-bevels','box_sweeps':78,
                    'without_bevel_differences':missing_bevel_differences,'issues':[]})

    radius = 1105
    ring = set()
    for x in range(-radius,radius+1):
        remaining = radius*radius-x*x; y = math.isqrt(remaining)
        if y*y==remaining: ring.update(((x,y,0),(x,-y,0)))
    ring = sorted(ring,key=lambda point:math.atan2(point[1],point[0]))
    pieces = []
    for upper in (True,False):
        cone = [((1,1,0),(-1,1,0),(-1,-1,0)) if upper else ((-1,-1,0),(-1,1,0),(1,1,0))]
        apex = (0,0,64 if upper else -64)
        for i,point in enumerate(ring):
            nxt = ring[(i+1)%len(ring)]
            cone.append((apex,nxt,point) if upper else (apex,point,nxt))
        pieces.append('\n'.join(['{',*(' '.join('( %s %s %s )'%v for v in face)+
                                    ' compat/bump 0 0 0 1 1 0 0 0' for face in cone),'}']))
    path = folder/'brush-bevel-budget.map'
    path.write_text('{\n"classname" "worldspawn"\n'+'\n'.join(pieces)+'\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
    bsp = path.with_suffix('.bsp');r = load_records(bsp,inspect(bsp))
    if (validate(bsp)['issues'] or len(r[92])!=2 or any(not b[3]<b[4]<=255 for b in r[92]) or
            'rejected by native bevel-plane budget' not in path.with_suffix('.log').read_text(errors='replace')):
        raise RuntimeError('Convex merging overflowed the native plane budget instead of retaining its valid pieces')
    reports.append({'game':game,'fixture':'native-brush-bevel-budget','issues':[]})



def portal_boundary_fixtures(folder, command, reports, game):
    # A nonsolid slab must preserve authored partitions in otherwise convex
    # empty space. Samples remain graph-connected through ordinary portals.
    room = portal_fixture(closed=True)
    room = room[:room.rfind(box((-8, -128, 0), (8, 128, 256), 'bump'))]
    for kind in ('hint', 'areaportal'):
        path = folder / ('portal-' + kind + '.map')
        slab = box((-8, -128, 0), (8, 128, 256), kind)
        if kind == 'hint':
            # Only the final face is a hint; all other faces are skipped.
            slab = slab.replace('compat/hint', 'compat/skip', 5)
        path.write_text(room + slab + '\n}\n', encoding='utf-8')
        with path.with_suffix('.log').open('wb') as log:
            subprocess.run(command[:-1] + [str(path)], stdout=log, stderr=subprocess.STDOUT, check=True)
        bsp = path.with_suffix('.bsp')
        report = validate(bsp)
        if report['issues']:
            raise RuntimeError(f'portal {kind}: {report["issues"]}')
        records = load_records(bsp, inspect(bsp))
        a, b = [locate_cell(records, point) for point in ((-32, 0, 64), (32, 0, 64))]
        if a == b or not connected(records, a, b):
            raise RuntimeError(f'{kind} partition was erased or made opaque')
        reports.append({'game': game, 'fixture': 'portal-' + kind, 'issues': []})


def portal_budget_fixture(folder, command, reports, game):
    # Dense but connected space on either side of a sealed divider. Its ordinary
    # convex partition exceeds the native cell budget, without any game assets.
    end = 34 * 32
    pieces = [box((-16, -16, -16), (end+16, end+16, 0), 'bump'),
              box((-16, -16, 128), (end+16, end+16, 144), 'bump'),
              box((-16, -16, 0), (0, end+16, 128), 'bump'),
              box((end, -16, 0), (end+16, end+16, 128), 'bump'),
              box((0, -16, 0), (end, 0, 128), 'bump'),
              box((0, end, 0), (end, end+16, 128), 'bump'),
              box((540, 0, 0), (548, end, 128), 'bump')]
    for x in range(34):
        for y in range(34):
            pieces.append(box((x*32+8, y*32+8, 0), (x*32+24, y*32+24, 64), 'bump'))
    # A hint spanning the left chamber must also survive the nonconvex budget
    # pass, including routes around subdivisions from the many pillar faces.
    hint = box((256, 0, 0), (264, end, 128), 'hint')
    pieces.append(hint.replace('compat/hint', 'compat/skip', 5))
    path = folder / 'portal-budget.map'
    path.write_text('{\n"classname" "worldspawn"\n"_viewportals" "1"\n' + '\n'.join(pieces) + '\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1] + [str(path)], stdout=log, stderr=subprocess.STDOUT, check=True)
    bsp = path.with_suffix('.bsp')
    report = validate(bsp)
    if report['issues']:
        raise RuntimeError(f'portal budget: {report["issues"]}')
    r = load_records(bsp, inspect(bsp))
    a, b, c = [locate_cell(r, p) for p in ((4,4,96), (end-4,4,96), (4,end-4,96))]
    if a == b or connected(r, a, b) or not connected(r, a, c):
        raise RuntimeError('cell budget clustering changed closed-room connectivity')
    for y in range(4, end, 32):
        before, after = [locate_cell(r, point) for point in ((255,y,96), (257,y,96))]
        if before == after or not connected(r, before, after):
            raise RuntimeError('cell budget clustering erased an authored hint boundary')
    solid = locate_cell(r, (544,4,96))
    if solid != locate_cell(r, (-8,128,64)) or r[107][solid][0] or r[119][solid][5]:
        raise RuntimeError('opaque leaves lost their empty shared cell')
    if len(r[107]) != 1022 or len([p for p, _ in r[106] if p == -1]) <= 1022:
        raise RuntimeError('stress map did not exercise native cell budget clustering')
    reports.append({'game': game, 'fixture': 'portal-budget', 'issues': []})


# A floor with a roof over its x<0 half. The sun travels down at 60 degrees
# towards +x+y, so the roof's shadow reaches past its edge to about x=+84.
LIT_FIXTURE = (
    # Bounce is off so the roof check below isolates sky occlusion; bounce has
    # its own unit test in lightbake_tests.cpp.
    '{\n"classname" "worldspawn"\n"_bouncescale" "0"\n'
    + box((-512, -512, -16), (512, 512, 0), "bump") + "\n"
    + box((-512, -512, 256), (0, 512, 272), "bump") + "\n}\n"
    + entity(classname="light_environment", origin="0 0 512", pitch="-60", angles="60 30 0",
             _light="255 240 220 600", _ambient="150 180 255 100")
    + entity(classname="light_spot", origin="0 384 200", pitch="-90", angles="90 0 0",
             _light="255 255 255 400", _distance="400", _cone="45", _inner_cone="20")
    + entity(classname="light", origin="256 -256 64", _light="255 200 150 200", _distance="256")
    + entity(classname="light", origin="-256 0 64", _light="255 255 255 255", _distance="256", realtime="0")
    # Menu stage: environment 1 inside its volume, with a stage spotlight.
    + entity(classname="light_environment", lightEnvironmentIndex="*1", origin="5000 0 300", pitch="-50",
             angles="50 120 0", _light="255 255 255 765", _ambient="255 255 255 51")
    + entity(classname="light_environment_volume", lightEnvironmentIndex="*1", origin="5000 0 0",
             **{f"*trigger_brush_0_plane_{i}": f"{n} 1024" for i, n in enumerate(
                 ("-1 0 0", "1 0 0", "0 -1 0", "0 1 0", "0 0 -1", "0 0 1"))})
    + entity(classname="light_spot", origin="5000 -200 200", pitch="-40", angles="40 90 0",
             _light="255 255 255 255", _distance="500", _cone="50", shadow="0")
    + entity(classname="info_target_clientside", script_name="menu_scene_ref", origin="5000 0 0", angles="0 -90 0")
)


def tangent_checks(bsp, titanfall1=False):
    """Bump-lit tangents follow retail. TF2: unit, along +dP/du, bit 31 = mirrored,
    second word zero. TF1: plain tangent and bitangent normal indices, the
    bitangent being cross(normal, tangent) flipped to follow +dP/dv."""
    with bsp.open("rb") as stream:
        def lump(index):
            stream.seek(16 + index * 16)
            offset, length, _, _ = struct.unpack("<4I", stream.read(16))
            stream.seek(offset)
            return stream.read(length)
        positions = list(struct.iter_unpack("<3f", lump(0x03)))
        normals = list(struct.iter_unpack("<3f", lump(0x1E)))
        bump = list(struct.iter_unpack("<2I2f4B4f2I", lump(0x49)))
        indices = [i[0] for i in struct.iter_unpack("<H", lump(0x4F))]
        sorts = list(struct.iter_unpack("<4hi", lump(0x52)))
        meshes = list(struct.iter_unpack("<IHHHBBIHHHHI", lump(0x50)))
    dot = lambda a, b: sum(x * y for x, y in zip(a, b))
    sub = lambda a, b: tuple(x - y for x, y in zip(a, b))
    cross = lambda a, b: (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
    checked = 0
    for tri, count, _, _, kind, _, _, _, _, _, sort, _ in meshes:
        if kind != 2:
            continue
        base = sorts[sort][4]
        for t in range(count):
            a, b, c = (base + i for i in indices[tri + 3 * t: tri + 3 * t + 3])
            p = [positions[bump[k][0]] for k in (a, b, c)]
            uv = [(bump[k][2], bump[k][3]) for k in (a, b, c)]
            e1, e2 = sub(p[1], p[0]), sub(p[2], p[0])
            d1, d2 = sub(uv[1], uv[0]), sub(uv[2], uv[0])
            det = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(det) < 1e-9:
                continue
            du = tuple((x * d2[1] - y * d1[1]) / det for x, y in zip(e1, e2))
            dv = tuple((y * d1[0] - x * d2[0]) / det for x, y in zip(e1, e2))
            word, second = bump[a][-2], bump[a][-1]
            n, tangent = normals[bump[a][1]], normals[word & (0xffffffff if titanfall1 else 0x7fffffff)]
            if (second and not titanfall1) or abs(dot(tangent, tangent) - 1) > 1e-3 or abs(dot(tangent, n)) > 1e-3:
                raise RuntimeError("tangent is not a unit vector perpendicular to the normal")
            if titanfall1:
                bitangent = normals[second]
                expected = cross(n, tangent)
                if dot(cross(n, tangent), dv) < 0:
                    expected = tuple(-x for x in expected)
                if dot(tangent, du) <= 0 or dot(bitangent, expected) < 0.999:
                    raise RuntimeError("TF1 tangent or bitangent disagrees with retail convention")
            elif dot(tangent, du) <= 0 or (dot(cross(n, tangent), dv) < 0) != bool(word >> 31):
                raise RuntimeError("tangent direction or handedness bit disagrees with retail convention")
            checked += 1
    if not checked:
        raise RuntimeError("no bump-lit triangles to check")


def lit_fixture_checks(bsp):
    """Structural and shadow checks on the lit Titanfall 2 fixture."""
    with bsp.open("rb") as stream:
        def lump(index):
            stream.seek(16 + index * 16)
            offset, length, _, _ = struct.unpack("<4I", stream.read(16))
            stream.seek(offset)
            return stream.read(length)
        lights = list(struct.iter_unpack("<12f3i7f3i3f", lump(0x36)))
        headers = list(struct.iter_unpack("<I2H", lump(0x53)))
        sky, rtl, pages = lump(0x62), lump(0x69), list(struct.iter_unpack("<63h", lump(0x7A)))
        positions = list(struct.iter_unpack("<3f", lump(0x03)))
        normals = list(struct.iter_unpack("<3f", lump(0x1E)))
        bump = list(struct.iter_unpack("<2I2f4B4f2i", lump(0x49)))
        sorts = list(struct.iter_unpack("<4hi", lump(0x52)))
        parents = list(struct.iter_unpack("<i6I", lump(0x04)))
        probes = list(struct.iter_unpack("<16h4B4hI", lump(0x65)))
        tree = list(struct.iter_unpack("<2I", lump(0x67)))
        references = list(struct.iter_unpack("<3fIi", lump(0x68)))
    if parents != [(0, 0, len(probes), 0, len(references), 0, len(tree))] or not probes:
        raise RuntimeError(f"light probe parent info {parents} does not match the probe lumps")
    if sorted(r[3] for r in references) != list(range(len(probes))):
        raise RuntimeError("probe references do not cover each probe exactly once")
    leaves = [n for n in tree if n[0] & 3 == 3]
    if sum(n[1] for n in leaves) != len(references) or max(n[1] for n in leaves) > 8:
        raise RuntimeError("probe tree leaves do not partition the references")

    def probe_near(x, y, z):
        ref = min(references, key=lambda r: (r[0] - x) ** 2 + (r[1] - y) ** 2 + (r[2] - z) ** 2)
        return probes[ref[3]]
    # Hardware indices: sun 0, menu sun 1, spot 2, menu spot 3, realtime point 4, static point 5.
    stage = probe_near(5000, 0, 64)
    if stage[15] != 8192 or 3 not in stage[20:24]:
        raise RuntimeError(f"menu-stage probe lacks its environment's sun or spotlight: {stage}")
    if probe_near(256, -256, 64)[16] == 0 or 4 not in probe_near(256, -256, 64)[20:24]:
        raise RuntimeError("probe beside the realtime point light has no link to it")
    if probe_near(-300, 0, 64)[15] != 0 or probe_near(400, 0, 64)[15] != 8192:
        raise RuntimeError("probe sun visibility does not follow the roof")
    if any(5 in p[20:24] for p in probes):
        raise RuntimeError("static light was linked from a probe")
    if any(i in (1, 3) for page in pages for i in page):
        raise RuntimeError("menu-stage lights entered the gameplay RTL pages")
    if [(l[13], l[22]) for l in lights] != [(5, 0), (5, 0), (3, 24), (3, 24), (2, 28), (2, 56), (1, 28), (1, 4)]:
        raise RuntimeError(f"world light order/flags: {[(l[13], l[22]) for l in lights]}")
    if any(any(l[9:12]) or (l[13] == 5 and any(l[6:9])) or
           (l[13] == 1 and l[6:9] != (1.0, 0.0, 0.0)) for l in lights):
        raise RuntimeError('Unused world-light vectors contain uninitialized values')
    texels = sum(w * h for _, w, h in headers)
    if len(sky) != texels * 8 or len(rtl) != texels * 9 or len(headers) != 1:
        raise RuntimeError("lightmap planes do not match one header page")
    if not any(s[1] == 0 for s in sorts) or not pages:
        raise RuntimeError("no material sort or RTL page is bound to the lightmap")
    _, width, height = headers[0]
    # Affine world -> lightmap UV map from three floor-top vertices.
    floor = [(positions[v[0]], v[8], v[9]) for v in bump
             if abs(positions[v[0]][2]) < 1e-3 and normals[v[1]][2] > 0.99]
    if len(floor) < 3:
        raise RuntimeError("floor vertices missing from the lit bump pool")
    (p0, u0, v0), (p1, u1, v1), (p2, u2, v2) = floor[:3]
    det = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (p1[1] - p0[1])

    def texel(x, y):
        a = ((x - p0[0]) * (p2[1] - p0[1]) - (p2[0] - p0[0]) * (y - p0[1])) / det
        b = ((p1[0] - p0[0]) * (y - p0[1]) - (x - p0[0]) * (p1[1] - p0[1])) / det
        u = u0 + a * (u1 - u0) + b * (u2 - u0)
        v = v0 + a * (v1 - v0) + b * (v2 - v0)
        return int(v * height) * width + int(u * width)

    def realtime(x, y):
        i = texel(x, y)
        word = struct.unpack_from("<I", rtl, i * 4)[0]
        mask = rtl[texels * 4 + i * 4: texels * 4 + i * 4 + 4]
        if word == 0xffffffff:
            return {}
        page = pages[word >> 24]
        return {page[(word >> (6 * k)) & 63]: mask[k] for k in range(4) if (word >> (6 * k)) & 63 != 63}

    def sky_a(x, y):
        r, g, b, a = sky[texel(x, y) * 4: texel(x, y) * 4 + 4]
        return r / 255 * (a / 255 * 3.984375 + 0.015625)

    # Hardware indices: sun 0, menu sun 1, spot 2, menu spot 3, realtime point 4, static point 5.
    for x, expected in ((-256, 0), (64, 0), (256, 255), (448, 255)):
        if realtime(x, 0).get(0) != expected:
            raise RuntimeError(f"sun mask at x={x}: {realtime(x, 0)} (expected {expected})")
    if realtime(256, -256).get(4) != 255:
        raise RuntimeError(f"realtime point light missing below it: {realtime(256, -256)}")
    if realtime(0, 384).get(2) is None:
        raise RuntimeError(f"spotlight missing below it: {realtime(0, 384)}")
    if any(5 in realtime(x, 0) for x in (-256, -128)):
        raise RuntimeError("static light was given an RTL slot")
    if not sky_a(-256, 0) > sky_a(-256, -448) + 0.05:
        raise RuntimeError(f"static light not baked into SKY A: {sky_a(-256, 0)} vs {sky_a(-256, -448)}")
    if not sky_a(400, 0) > sky_a(-448, 400) > 0:
        raise RuntimeError("roof does not reduce sky ambient")


def physics_checks(bsp, inventory, brushes, model_index=0, z_bounds=None):
    """Check TF1 world/entity IVP ledges, outward triangles and watertight edges."""
    lump = inventory["lumps"][0x1D]
    with bsp.open("rb") as stream:
        stream.seek(lump["offset"])
        data = stream.read(lump["length"])
    model_offset = 0
    while True:
        model, size, keysize, count = struct.unpack_from("<4i", data, model_offset)
        if model in (model_index, -1):
            break
        model_offset += 16 + size + keysize
    if model != model_index or count < 1 or data[-16:] != struct.pack("<4i", -1, -1, 0, 0):
        raise RuntimeError(f"bad VPhysics model header {model, size, keysize, count}")
    keydata = data[model_offset + 16 + size:model_offset + 16 + size + keysize]
    if not keydata.startswith(b"staticsolid {" if model_index == 0 else b"solid {") or not keydata.endswith(b"\x00"):
        raise RuntimeError(f"bad VPhysics keydata {keydata[:40]!r}")
    offset, ledges = model_offset + 16, 0
    heights = []
    for _ in range(count):
        solid_size = struct.unpack_from("<i", data, offset)[0]
        solid = data[offset + 4:offset + 4 + solid_size]
        offset += 4 + solid_size
        if solid[:4] != b"VPHY" or solid[72:76] != b"IVPS":
            raise RuntimeError("VPhysics solid lacks VPHY/IVPS markers")
        surface = 28
        if struct.unpack_from("<I", solid, surface + 28)[0] >> 8 != solid_size - 28:
            raise RuntimeError("compact surface byte_size does not match the solid")
        nodes = [surface + struct.unpack_from("<i", solid, surface + 32)[0]]
        while nodes:
            node = nodes.pop()
            right, ledge = struct.unpack_from("<ii", solid, node)
            if right:
                nodes += [node + 28, node + right]
                continue
            ledges += 1
            ledge += node
            points_at, _, flags, triangles = struct.unpack_from("<iiIh", solid, ledge)
            def point(i):
                return struct.unpack_from("<3f", solid, ledge + points_at + 16 * i)
            def edge(address):
                word = struct.unpack_from("<I", solid, address)[0]
                opposite = (word >> 16) & 0x7FFF
                return word & 0xFFFF, opposite - 0x8000 if opposite & 0x4000 else opposite
            corners = sorted({edge(ledge + 20 + 16 * t + 4 * k)[0] for t in range(triangles) for k in range(3)})
            heights.extend(-point(i)[1] * 39.3701 for i in corners)
            centre = [sum(point(i)[a] for i in corners) / len(corners) for a in range(3)]
            for t in range(triangles):
                tri = ledge + 16 + 16 * t
                ids = [edge(tri + 4 + 4 * k)[0] for k in range(3)]
                a, b, c = (point(i) for i in ids)
                u = [b[i] - a[i] for i in range(3)]
                v = [c[i] - a[i] for i in range(3)]
                n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
                if sum(n[i] * (a[i] - centre[i]) for i in range(3)) <= 0:
                    raise RuntimeError("VPhysics triangle faces inward")
                for k in range(3):
                    here = tri + 4 + 4 * k
                    other = here + 4 * edge(here)[1]
                    other_tri = ledge + 16 + 16 * ((other - ledge - 16) // 16)
                    other_k = (other - other_tri - 4) // 4
                    if edge(other)[0] != ids[(k + 1) % 3] or edge(other_tri + 4 + 4 * ((other_k + 1) % 3))[0] != ids[k]:
                        raise RuntimeError("VPhysics edge is not twinned with its reverse")
    if z_bounds is not None and any(abs(a - b) > 0.001 for a, b in zip((min(heights), max(heights)), z_bounds)):
        raise RuntimeError(f"VPhysics Z bounds {(min(heights), max(heights))} differ from {z_bounds}")
    if ledges != brushes:
        raise RuntimeError(f"expected {brushes} VPhysics ledges, got {ledges}")


def physics_virtual_mesh_fixture(folder, command, reports, game):
    # World patches collide in VPhysics through the engine's TRICOLL virtual
    # meshes, not prisms. As in retail, only clip-only headers get keydata vtric
    # entries naming their collision contents; solid and bullet-clip do not.
    patches = [PATCH.replace('compat/bump', f'compat/{name}') for name in ('bump', 'playerclip', 'bulletclip')]
    patches = [p.replace('( -128 ', f'( {-128 + 512 * i} ').replace('( 0 ', f'( {512 * i} ').replace('( 128 ', f'( {128 + 512 * i} ')
               for i, p in enumerate(patches)]
    path = folder/'physics-virtual-mesh.map'
    path.write_text('{\n"classname" "worldspawn"\n' + box((-256, -256, -64), (1280, 256, -48), 'bump') + '\n' +
                    '\n'.join(patches) + '\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
    bsp = path.with_suffix('.bsp')
    inventory = inspect(bsp)
    physics_checks(bsp, inventory, 1)  # the floor brush only: no patch prisms
    records = load_records(bsp, inventory)
    if len(records[69]) != 3:
        raise RuntimeError(f'expected three patch TRICOLL headers, got {len(records[69])}')
    contents = [c for (c,) in records[91]]
    header_contents = {}
    words = [w for _, n, w in records[87] if n == 1] + [w for (w,) in records[89]]
    for word in words:
        if word >> 24 == 0x40:
            header_contents[(word >> 8) & 0xffff] = contents[word & 0xff]
    with bsp.open('rb') as stream:
        entry = inventory['lumps'][29]
        stream.seek(entry['offset']); data = stream.read(entry['length'])
    _, size, keysize, _ = struct.unpack_from('<4i', data)
    keydata = data[16 + size:16 + size + keysize].decode('ascii')
    vtric = {int(i): int(c) for i, c in re.findall(r'vtric \{\n"index" "(\d+)"\n"contents" "(\d+)"\n\}', keydata)}
    expected = {h: c for h, c in header_contents.items() if c == 0x10000}
    if sorted(header_contents.values()) != [0x1, 0x10000, 0x480000] or vtric != expected:
        raise RuntimeError(f'vtric entries {vtric} do not match clip-only headers {header_contents}')
    if not keydata.index('virtualtrimeshes {}') < keydata.index('vtric {') < keydata.index('materialtable {'):
        raise RuntimeError('vtric entries are outside their retail keydata position')
    reports.append({'game': game, 'fixture': 'physics-virtual-mesh', 'issues': []})


def physics_material_limit_fixture(folder, command, reports, game):
    # A full 1..127 table still accepts a reused property. A new 128th property
    # must fail instead of silently taking the first property's sound/friction.
    pieces = [box((i*32,0,0),(i*32+16,16,16),f'limit_{i:03}') for i in range(127)]
    pieces.append(box((4096,0,0),(4112,16,16),'limit_000'))
    path = folder/'physics-material-limit.map'
    path.write_text('{\n"classname" "worldspawn"\n'+'\n'.join(pieces)+'\n}\n')
    with path.with_suffix('.log').open('wb') as log:
        subprocess.run(command[:-1]+[str(path)],stdout=log,stderr=subprocess.STDOUT,check=True)
    bsp = path.with_suffix('.bsp')
    inventory = inspect(bsp)
    physics_checks(bsp,inventory,128)
    with bsp.open('rb') as stream:
        entry = inventory['lumps'][29]
        stream.seek(entry['offset']);data = stream.read(entry['length'])
    table = {(int(name),int(value)) for name,value in re.findall(rb'"limit_prop_(\d+)" "(\d+)"',data)}
    if table != {(i,i+1) for i in range(127)}:
        raise RuntimeError('Full VPhysics surface-property table was aliased or truncated')
    reports.append({'game':game,'fixture':'physics-material-limit','issues':[]})
    overflow = folder/'physics-material-overflow.map'
    overflow.write_text('{\n"classname" "worldspawn"\n'+'\n'.join(pieces[:-1])+ '\n'+
                        box((4096,0,0),(4112,16,16),'limit_127')+'\n}\n')
    with overflow.with_suffix('.log').open('wb') as log:
        result = subprocess.run(command[:-1]+[str(overflow)],stdout=log,stderr=subprocess.STDOUT)
    text = overflow.with_suffix('.log').read_text(errors='replace')
    if result.returncode == 0 or '127 distinct surface properties' not in text or overflow.with_suffix('.bsp').exists():
        raise RuntimeError('Unrepresentable VPhysics surface-property table was not rejected')
    reports.append({'game':game,'fixture':'physics-material-overflow-rejected','issues':[]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--remap", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    root = args.work_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shaders = root / "assets/shaders"
    shaders.mkdir(parents=True)
    types = {"flat": "LitFlatGeneric", "bump": "LitBumpGeneric",
             "unlit": "UnlitGeneric", "ts": "UnlitTSGeneric",
             "overlap_extra": "UnlitGeneric", "overlap": "UnlitGeneric",
             "vmt_bare": "LitBumpGeneric", "vmt_mixed": "LitBumpGeneric", "vmt_comment": "LitBumpGeneric",
             "vmt_inherit": "LitBumpGeneric", "vmt_replace": "LitBumpGeneric", "vmt_insert": "LitBumpGeneric",
             "vmt_chain": "LitBumpGeneric", "vmt_no_replace": "LitBumpGeneric", "vmt_cycle": "LitBumpGeneric",
             "vmt_proxy": "LitBumpGeneric"}
    (shaders / "compat.shader").write_text("\n".join(
        f"textures/compat/{name}\n{{\n $shadertype {kind}\n}}"
        for name, kind in types.items()) + '\ntextures/compat/sky\n{\n $shadertype LitBumpGeneric\n $compileflag sky\n $surfaceflag sky\n}\n' +
        ''.join(f'\ntextures/compat/{name}\n{{\n $contentflag nonsolid\n $contentflag {fluid}\n}}\n'
                for name, fluid in (('water', 'water'), ('water_alt', 'water'), ('slime', 'slime'))), encoding="utf-8")
    with (shaders / "compat.shader").open('a', encoding='utf-8') as stream:
        for kind in ('hint', 'skip', 'areaportal'):
            stream.write(f'\ntextures/compat/{kind}\n{{\n $shadertype LitBumpGeneric\n'
                         f' $contentflag nonsolid\n $compileflag nodraw\n $compileflag {kind}\n}}\n')
    with (shaders / 'compat.shader').open('a',encoding='utf-8') as stream:
        stream.write('\ntextures/compat/playerclip\n{\n $shadertype LitBumpGeneric\n $contentflag playerclip\n}\n')
        stream.write('\ntextures/compat/bulletclip\n{\n $shadertype LitBumpGeneric\n $contentflag bulletclip\n $contentflag blocklosclip\n}\n')
        for i in range(128):
            stream.write(f'\ntextures/compat/limit_{i:03}\n{{\n $shadertype LitBumpGeneric\n $surfaceprop limit_prop_{i:03}\n}}\n')
    vmts = root / 'assets/materials/compat'
    vmts.mkdir(parents=True)
    (vmts / 'vmt_bare.vmt').write_text('LightmappedGeneric { $surfaceprop metal }')
    (vmts / 'vmt_mixed.vmt').write_text('"LightmappedGeneric" { "$surfaceprop" "glass" }')
    (vmts / 'vmt_comment.vmt').write_text('LightmappedGeneric { // "$surfaceprop" "wrong"\n /* "$surfaceprop" "also_wrong" */ $surfaceprop "wood" }')
    (vmts / 'vmt_inherit.vmt').write_text('Patch { include "materials/compat/vmt_bare.vmt" insert { "$basetexture" "x" } }')
    (vmts / 'vmt_replace.vmt').write_text('Patch { include "materials/compat/vmt_bare.vmt" replace { "$surfaceprop" "rubber" } }')
    (vmts / 'vmt_insert.vmt').write_text('Patch { include "materials/compat/vmt_bare.vmt" insert { "$surfaceprop" "sand" } }')
    (vmts / 'vmt_chain.vmt').write_text('Patch { include "materials/compat/vmt_replace.vmt" replace { "$surfaceprop" "stone" } }')
    (vmts / 'vmt_empty.vmt').write_text('LightmappedGeneric { "$basetexture" "x" }')
    (vmts / 'vmt_no_replace.vmt').write_text('Patch { include "materials/compat/vmt_empty.vmt" replace { "$surfaceprop" "wrong" } }')
    (vmts / 'vmt_cycle.vmt').write_text('Patch { include "materials/compat/vmt_cycle.vmt" insert { "$surfaceprop" "wrong" } }')
    (vmts / 'vmt_proxy.vmt').write_text('LightmappedGeneric { Proxies { Test { "$surfaceprop" "wrong" } } "$surfaceprop" "dirt" }')
    geometry = '{\n"classname" "worldspawn"\n' + "\n".join([
        brush(0, True, ["bump"] * 6),
        brush(128, False, ["flat", "bump", "unlit", "ts", "flat", "bump"]),
        brush(256.25, False, ["overlap_extra"] * 6),
        brush(384.375, False, ["overlap"] * 6),
        brush(512.625, False, ["overlap"] * 6),
    ]) + "\n}\n"
    reports = []
    for game in ("titanfallonline", "titanfall2", "apexlegends"):
        folder = root / game
        folder.mkdir()
        path = folder / "regression.map"
        path.write_text(geometry, encoding="utf-8")
        command = [str(args.remap.resolve()), "-game", game, "-fs_basepath", str(root),
                   "-bsp", str(path)]
        with (folder / "build.log").open("wb") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        bsp = path.with_suffix(".bsp")
        report = inspect(bsp) if game == "apexlegends" else validate(bsp)
        if report["issues"]:
            raise RuntimeError(f"{game}: {report['issues']}")
        inventory = inspect(bsp)
        directory = inventory["lumps"]
        with bsp.open("rb") as stream:
            name_lump = directory[15 if game == "apexlegends" else 43]
            stream.seek(name_lump["offset"])
            names = stream.read(name_lump["length"])
            stream.seek(directory[2]["offset"])
            textures = stream.read(directory[2]["length"])
            if game == "apexlegends":
                texture_offsets = [v[0] for v in struct.iter_unpack("<4I", textures)]
            else:
                stream.seek(directory[44]["offset"])
                table = [v[0] for v in struct.iter_unpack("<I", stream.read(directory[44]["length"]))]
                texture_offsets = [table[v[3]] for v in struct.iter_unpack("<3f6i", textures)]
        texture_names = [names[v:names.index(b"\0", v)].decode() for v in texture_offsets]
        for name in ("compat\\overlap_extra", "compat\\overlap"):
            if texture_names.count(name) != 1:
                raise RuntimeError(f"{game}: missing or duplicated exact material {name}: {texture_names}")
        # Each authored vertex type must have emitted a pool, particularly 0x600.
        pools = (71, 73, 74) if game == "apexlegends" else (71, 72, 73, 74)
        for pool in pools:
            if not inventory["lumps"][pool]["length"]:
                raise RuntimeError(f"{game}: expected populated vertex pool {pool}")
        if game != "apexlegends":
            tangent_checks(bsp, game == "titanfallonline")
            if game == "titanfallonline":
                physics_checks(bsp, inventory, 5)
                vmt_path = folder / 'vmt-physics.map'
                vmt_path.write_text('{\n"classname" "worldspawn"\n' + '\n'.join(
                    box((x, 0, 0), (x + 64, 64, 64), name) for x, name in
                    ((0, 'vmt_bare'), (128, 'vmt_mixed'), (256, 'vmt_comment'),
                     (384, 'vmt_inherit'), (512, 'vmt_replace'), (640, 'vmt_insert'),
                     (768, 'vmt_chain'), (896, 'vmt_no_replace'), (1024, 'vmt_cycle'),
                     (1152, 'vmt_proxy'))) + '\n}\n')
                with vmt_path.with_suffix('.log').open('wb') as log:
                    subprocess.run(command[:-1] + [str(vmt_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
                if 'unable to resolve VMT materials/compat/vmt_cycle.vmt' not in vmt_path.with_suffix('.log').read_text(errors='replace'):
                    raise RuntimeError('cyclic VMT include did not produce a compiler warning')
                vmt_bsp = vmt_path.with_suffix('.bsp')
                vmt_lump = inspect(vmt_bsp)['lumps'][29]
                with vmt_bsp.open('rb') as stream:
                    stream.seek(vmt_lump['offset'])
                    physics = stream.read(vmt_lump['length'])
                _, data_size, key_size, _ = struct.unpack_from('<4i', physics)
                keydata = physics[16 + data_size:16 + data_size + key_size]
                table = {int(index): name.decode() for name, index in
                         re.findall(rb'"([^"\n]+)" "(\d+)"', keydata[keydata.index(b'materialtable {'):])}
                solid_size = struct.unpack_from('<i', physics, 16)[0]
                solid = physics[20:20 + solid_size]
                nodes = [28 + struct.unpack_from('<i', solid, 60)[0]]
                found = {}
                while nodes:
                    node = nodes.pop()
                    right, ledge = struct.unpack_from('<ii', solid, node)
                    if right:
                        nodes.extend((node + 28, node + right))
                        continue
                    ledge += node
                    point_offset = struct.unpack_from('<i', solid, ledge)[0]
                    triangle_count = struct.unpack_from('<h', solid, ledge + 12)[0]
                    vertex_ids, materials = set(), set()
                    for triangle in range(triangle_count):
                        tri = ledge + 16 + 16 * triangle
                        materials.add((struct.unpack_from('<I', solid, tri)[0] >> 24) & 127)
                        vertex_ids.update(struct.unpack_from('<I', solid, tri + 4 + 4 * k)[0] & 0xffff
                                          for k in range(3))
                    x = sum(struct.unpack_from('<f', solid, ledge + point_offset + 16 * vertex)[0]
                            for vertex in vertex_ids) * 39.3701 / len(vertex_ids)
                    found[round(x / 128)] = {table.get(material) for material in materials}
                if found != {0: {'metal'}, 1: {'glass'}, 2: {'wood'}, 3: {'metal'},
                             4: {'rubber'}, 5: {'sand'}, 6: {'stone'}, 7: {'default'},
                             8: {'default'}, 9: {'dirt'}}:
                    raise RuntimeError(f'VMT surface properties not assigned to their brushes: {found}')
                reports.append({'game': game, 'fixture': 'vmt-physics-materials', 'issues': []})
                physics_material_limit_fixture(folder,command,reports,game)
                physics_virtual_mesh_fixture(folder,command,reports,game)
                fluid_path = folder / 'fluids.map'
                fluid_path.write_text('{\n"classname" "worldspawn"\n' +
                                      box((0, 0, -64), (64, 64, -16), 'bump') + '\n' +
                                      box((0, 0, 0), (64, 64, 64), 'water') + '\n' +
                                      box((128, 0, 0), (192, 64, 64), 'slime') + '\n' +
                                      box((256, 0, 0), (320, 64, 64), 'water_alt') + '\n' +
                                      box((384, 0, 0), (448, 64, 64.04), 'water') + '\n}\n')
                with fluid_path.with_suffix('.log').open('wb') as log:
                    subprocess.run(command[:-1] + [str(fluid_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
                fluid_bsp = fluid_path.with_suffix('.bsp')
                fluid_lumps = inspect(fluid_bsp)['lumps']
                with fluid_bsp.open('rb') as stream:
                    stream.seek(fluid_lumps[29]['offset'])
                    physics = stream.read(fluid_lumps[29]['length'])
                    stream.seek(fluid_lumps[36]['offset'])
                    water_records = list(struct.iter_unpack('<ffi', stream.read(fluid_lumps[36]['length'])))
                if (physics.count(b'fluid {') != 4 or b'"contents" "16"' not in physics or
                        b'"contents" "32"' not in physics or len(water_records) != 4 or
                        len({record[2] for record in water_records}) != 3 or
                        len({record[0] for record in water_records}) != 2):
                    raise RuntimeError('fluids with different contents, surface materials or heights must be separate')
                reports.append({'game': game, 'fixture': 'distinct-fluids', 'issues': []})
                # A sloped clipping face can precede the horizontal surface in
                # the map. Its material must not replace the actual surface.
                clipped = box((0, 0, 0), (64, 64, 96), 'water')
                clipped = clipped.replace('{\n', '{\n( 64 0 64 ) ( 0 64 112 ) ( 64 64 64 ) compat/water_alt 0 0 0 1 1 0 0 0\n', 1)
                surface_path = folder / 'water-surface.map'
                surface_path.write_text('{\n"classname" "worldspawn"\n' + clipped + '\n}\n')
                with surface_path.with_suffix('.log').open('wb') as log:
                    subprocess.run(command[:-1] + [str(surface_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
                surface_bsp = surface_path.with_suffix('.bsp')
                surface_inventory = inspect(surface_bsp)
                surface_lumps = surface_inventory['lumps']
                surface_records = load_records(surface_bsp, surface_inventory)
                if not any(brush[4] for brush in surface_records[92]):
                    raise RuntimeError('clipped-water fixture has no non-axial collision plane')
                with surface_bsp.open('rb') as stream:
                    stream.seek(surface_lumps[36]['offset'])
                    surface_water = list(struct.iter_unpack('<ffi', stream.read(surface_lumps[36]['length'])))
                    stream.seek(surface_lumps[43]['offset'])
                    surface_names = stream.read(surface_lumps[43]['length'])
                    stream.seek(surface_lumps[44]['offset'])
                    surface_table = [v[0] for v in struct.iter_unpack('<I', stream.read(surface_lumps[44]['length']))]
                    stream.seek(surface_lumps[2]['offset'])
                    surface_textures = list(struct.iter_unpack('<3f6i', stream.read(surface_lumps[2]['length'])))
                if len(surface_water) != 1:
                    raise RuntimeError(f'expected one clipped water record, got {len(surface_water)}')
                texture = surface_textures[surface_water[0][2]]
                offset = surface_table[texture[3]]
                surface_name = surface_names[offset:surface_names.index(b'\0', offset)].decode()
                if surface_name != 'compat\\water':
                    raise RuntimeError(f'water surface selected the wrong material: {surface_name}')
                reports.append({'game': game, 'fixture': 'water-clipped-surface', 'issues': []})
                water_cells = folder / 'water-cells.map'
                water_cells.write_text(portal_fixture()[:-2] +
                    box((-256, -128, 0), (-208, 128, 256), 'water') + '\n' +
                    box((208, -128, 0), (256, 128, 256), 'water') + '\n}\n')
                with water_cells.with_suffix('.log').open('wb') as log:
                    subprocess.run(command[:-1] + [str(water_cells)], stdout=log, stderr=subprocess.STDOUT, check=True)
                cell_bsp = water_cells.with_suffix('.bsp')
                cell_records = load_records(cell_bsp, inspect(cell_bsp))
                for point in ((-128, 0, 64), (128, 0, 64)):
                    cell_index = locate_cell(cell_records, point)
                    if cell_records[107][cell_index][3] != -1:
                        raise RuntimeError('empty space between separated water brushes was assigned to water')
                reports.append({'game': game, 'fixture': 'separated-water-cells', 'issues': []})
                # Both triangular pools have bounding-box coverage above 50%
                # in the left chamber. Only the larger true volume does.
                for label, tip, expected_water in (('dry', -128, -1), ('wet', 0, 0)):
                    sloped = folder / ('water-triangle-'+label+'.map')
                    sloped.write_text(portal_fixture()[:-2] + triangle_prism(
                        ((-256,-128,256),(-256,128,256),(tip,-128,256)),0,'compat/water')+'\n}\n')
                    with sloped.with_suffix('.log').open('wb') as log:
                        subprocess.run(command[:-1]+[str(sloped)],stdout=log,stderr=subprocess.STDOUT,check=True)
                    sloped_bsp = sloped.with_suffix('.bsp')
                    water_records = load_records(sloped_bsp,inspect(sloped_bsp))
                    index = locate_cell(water_records,(-192,64,64))
                    if validate(sloped_bsp)['issues'] or water_records[107][index][3] != expected_water:
                        raise RuntimeError('Triangular water brush was measured as its enclosing bounds')
                    if label == 'dry':
                        bound = water_records[119][index]
                        low,high = bound[:3],bound[6:9]
                        cell_volume = math.prod(high[a]-low[a] for a in range(3))
                        box_volume = math.prod(max(0,min(high[a],(-128,128,256)[a])-max(low[a],(-256,-128,0)[a])) for a in range(3))
                        if not box_volume > cell_volume/2 > box_volume/2:
                            raise RuntimeError('Sloped water fixture does not distinguish box and solid coverage')
                    reports.append({'game':game,'fixture':'triangular-water-cell-'+label,'issues':[]})
            records = load_records(bsp, inventory)
            if not records[92][0][4] or records[92][1][4] != (4 if game == 'titanfall2' else 0) or not records[92][1][9]:
                raise RuntimeError("fixture must contain a sloped brush followed by an axial brush")
            # The box order is -X, +X, -Y, +Y, -Z, +Z (checked against retail maps).
            # Texture strings provide an independent check on axial surface identity.
            directory = inventory["lumps"]
            with bsp.open("rb") as stream:
                stream.seek(directory[43]["offset"])
                names = stream.read(directory[43]["length"])
                stream.seek(directory[44]["offset"])
                table = [v[0] for v in struct.iter_unpack("<I", stream.read(directory[44]["length"]))]
            start = 6 + records[92][1][9]
            materials = []
            for prop in records[94][start:start + 6]:
                texture = records[2][prop[0] & 0x1ff]
                offset = table[texture[3]]
                materials.append(names[offset:names.index(b"\0", offset)].decode())
            expected = ["bump", "ts", "unlit", "flat", "flat", "bump"]
            if materials != ["compat\\" + v for v in expected]:
                raise RuntimeError(f"axial material order incorrect: {materials}")
            for (_, count, word), bound in zip(records[87], records[88]):
                if count != 1 or word >> 24:
                    continue
                collision_brush = records[92][(word >> 8) & 0xffff]
                for axis in range(3):
                    minimum = collision_brush[axis] - collision_brush[axis + 6]
                    maximum = collision_brush[axis] + collision_brush[axis + 6]
                    if bound[axis] - bound[axis + 4] > minimum - 2 + 0.001 or bound[axis] + bound[axis + 4] < maximum + 2 - 0.001:
                        raise RuntimeError("quantized collision bounds lost authored geometry or margin")
        reports.append({"game": game, "bsp": str(bsp), "issues": report["issues"]})
        if game != "apexlegends":
            sky_path = folder / "sky-only.map"
            sky_path.write_text('{\n"classname" "worldspawn"\n' + brush(0, False, ["sky"] * 6) + '\n}\n', encoding="utf-8")
            with (folder / "sky-only.log").open("wb") as log:
                subprocess.run(command[:-1] + [str(sky_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
            sky_report = validate(sky_path.with_suffix(".bsp"))
            if sky_report["issues"]:
                raise RuntimeError(f"sky-only world: {sky_report['issues']}")
            reports.append({"game": game, "fixture": "sky-only", "issues": []})
        if game != "apexlegends":
            patch_entity = folder / 'patch-entities.map'
            # Keep a curved patch and a flat patch whose solid must extend below z=0.
            flat_patch = PATCH.replace(' 16 ', ' 0 ').replace(' 64 ', ' 0 ')
            patch_entity.write_text('{\n"classname" "worldspawn"\n' +
                box((1024, 0, -16), (1088, 64, 0), 'bump') + '\n}\n' +
                '{\n"classname" "func_brush"\n"targetname" "patch_only"\n' + PATCH + '\n}\n' +
                '{\n"classname" "func_brush"\n"targetname" "mixed_patch"\n' +
                box((512, 0, -16), (576, 64, 0), 'bump') + '\n' +
                flat_patch + '\n}\n')
            with patch_entity.with_suffix('.log').open('wb') as log:
                subprocess.run(command[:-1] + [str(patch_entity)], stdout=log, stderr=subprocess.STDOUT, check=True)
            patch_bsp = patch_entity.with_suffix('.bsp')
            patch_inventory = inspect(patch_bsp)
            patch_records = load_records(patch_bsp, patch_inventory)
            check_triangle_z_order(patch_records)
            if len(patch_records[14]) != 3 or any(not model[7] for model in patch_records[14]):
                raise RuntimeError('patch-only or mixed patch entity lost its render model')
            with patch_bsp.open('rb') as stream:
                entry = patch_inventory['lumps'][0]
                stream.seek(entry['offset'])
                patch_entities = [dict(values) for values in parse_entities(stream.read(entry['length']).decode('utf-8'))]
            for sidecar in folder.glob(patch_entity.stem + '_*.ent'):
                text = sidecar.read_text(encoding='utf-8')
                if text.startswith('ENTITIES'):
                    text = text.split('\n', 1)[1]
                patch_entities.extend(dict(values) for values in parse_entities(text))
            links = {e.get('targetname'): e.get('model') for e in patch_entities if e.get('classname') == 'func_brush'}
            if links != {'patch_only': '*1', 'mixed_patch': '*2'}:
                raise RuntimeError(f'patch entity model links missing: {links}')
            if len(patch_records[69]) != 2 or len(patch_records[66]) != 16:
                raise RuntimeError('patch entities lost their triangle collision')
            world_cells = patch_records[85][0][3] * patch_records[85][0][4]
            for model_index in (1, 2):
                first, count = patch_records[86][world_cells + model_index]
                words = []
                for _, primitives, word in patch_records[87][first:first + count]:
                    if primitives == 1:
                        words.append(word)
                    else:
                        start = (word >> 8) & 0xffff
                        words.extend(value[0] for value in patch_records[89][start:start + primitives])
                if not any(word >> 24 == 0x40 and ((word >> 8) & 0xffff) == model_index - 1 for word in words):
                    raise RuntimeError(f'patch entity {model_index} lacks its triangle collision in its model cell')
            if validate(patch_bsp)['issues']:
                raise RuntimeError('patch entity output failed record validation')
            if game == 'titanfallonline':
                physics_checks(patch_bsp, patch_inventory, 8, model_index=1, z_bounds=(-32, 64))
                physics_checks(patch_bsp, patch_inventory, 9, model_index=2, z_bounds=(-32, 0))
            reports.append({'game': game, 'fixture': 'patch-entities', 'issues': []})
        if game != "apexlegends":
            collision_portal_fixtures(folder, command, reports, game)
            collision_brush_merge_fixtures(folder, command, reports, game)
            collision_brush_bevel_fixture(folder, command, reports, game)
            collapsed_path = folder/'collapsed-patch.map'
            collapsed_rows = ('( ( 0 0 64 0 0 ) ( 0 0 64 0 0 ) ( 0 0 64 0 0 ) )\n' * 2 +
                              '( ( 0 0 64 0 0 ) ( 64 0 64 0 0 ) ( 0 64 64 0 0 ) )\n')
            collapsed_path.write_text('{\n"classname" "worldspawn"\n{\npatchDef2\n{\ncompat/bump\n( 3 3 0 0 0 )\n(\n'+collapsed_rows+')\n}\n}\n}\n')
            with collapsed_path.with_suffix('.log').open('wb') as log:
                subprocess.run(command[:-1]+[str(collapsed_path)],stdout=log,stderr=subprocess.STDOUT,check=True)
            collapsed_bsp = collapsed_path.with_suffix('.bsp')
            collapsed_records = load_records(collapsed_bsp,inspect(collapsed_bsp))
            if validate(collapsed_bsp)['issues'] or any(abs(collapsed_records[30][v[1]][2]-1)>1e-5 for v in collapsed_records[73]):
                raise RuntimeError('Collapsed patch vertices lack their flat upward render normal')
            reports.append({'game':game,'fixture':'collapsed-patch-normals','issues':[]})
            portal_boundary_fixtures(folder, command, reports, game)
            portal_budget_fixture(folder, command, reports, game)
        if game == "titanfall2":
            submodel_path = folder / 'submodel-bounds.map'
            submodel_path.write_text('{\n"classname" "worldspawn"\n' +
                box((0,0,0),(64,64,64),'bump') + '\n}\n' +
                '{\n"classname" "func_brush"\n' +
                box((8192,0,0),(8256,64,64),'bump') + '\n}\n')
            with submodel_path.with_suffix('.log').open('wb') as log:
                subprocess.run(command[:-1]+[str(submodel_path)],stdout=log,stderr=subprocess.STDOUT,check=True)
            sub_bsp = submodel_path.with_suffix('.bsp')
            sub_report = validate(sub_bsp)
            submodels = load_records(sub_bsp,inspect(sub_bsp))[14]
            if sub_report['issues'] or len(submodels) != 2 or submodels[1][:6] != (8192,0,0,8256,64,64):
                raise RuntimeError(f'Submodel inherited world bounds: {submodels}')
            reports.append({'game':game,'fixture':'submodel-bounds','issues':[]})
            models = root / "assets/models/compat"
            models.mkdir(parents=True)
            (models / "prop.obj").write_text("v 0 0 0\nv 8 0 0\nv 0 0 4\nf 1 2 3\n", encoding="ascii")
            prop_path = folder / "static-prop.map"
            prop_path.write_text(geometry + entity(classname="prop_static", model="models/compat/prop.obj",
                                                  origin="256 128 16", angle="90", modelscale="2.5", skin="7"),
                                 encoding="utf-8")
            with (folder / "static-prop.log").open("wb") as log:
                subprocess.run(command[:-1] + [str(prop_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
            prop_bsp = prop_path.with_suffix(".bsp")
            prop_report = validate(prop_bsp)
            placement = inspect_game_lump(prop_bsp, True)["entries"][0]["placements"][0]
            if prop_report["issues"] or placement["scale"] != 2.5 or placement["skin"] != 7 or placement["angles_raw"] != (0, 90, 0):
                raise RuntimeError(f"static prop placement fields: {placement}")
            inv = inspect(prop_bsp)
            with prop_bsp.open("rb") as stream:
                entry = inv["lumps"][120]
                stream.seek(entry["offset"])
                references = [r[0] for r in struct.iter_unpack("<H", stream.read(entry["length"]))]
                entry = inv["lumps"][121]  # OBJ_REFERENCE_BOUNDS, one record per reference
                stream.seek(entry["offset"])
                bounds = list(struct.iter_unpack("<3fI3fI", stream.read(entry["length"])))
            # Assimp's +90 X conversion followed by native yaw 90, scale 2.5.
            expected_min, expected_max = (256, 128, 16), (266, 148, 16)
            with prop_bsp.open('rb') as stream:
                stream.seek(inv['lumps'][123]['offset'] + 8)
                first_sky = struct.unpack('<I',stream.read(4))[0]
            prop_base = (first_sky + 63) & ~63
            prop_bounds = [b for ref, b in zip(references, bounds) if ref == prop_base]
            if not prop_bounds or any(abs(b[i] - expected_min[i]) > 0.001 or
                                      abs(b[i + 4] - expected_max[i]) > 0.001
                                      for b in prop_bounds for i in range(3)):
                raise RuntimeError(f"static prop transformed bounds: {prop_bounds}")
            relocated = folder / "static-prop-relocated.bsp"
            relocate_bsp(prop_bsp, relocated)
            if validate(relocated)["issues"] or inspect_game_lump(relocated)["entries"][0]["sha256"] != inspect_game_lump(prop_bsp)["entries"][0]["sha256"]:
                raise RuntimeError("static prop relocation changed its payload")
            reports.append({"game": game, "fixture": "static-prop-and-relocation", "issues": []})
            lit_path = folder / "lit.map"
            lit_path.write_text(LIT_FIXTURE, encoding="utf-8")
            with (folder / "lit.log").open("wb") as log:
                subprocess.run(command[:-1] + [str(lit_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
            lit_report = validate(lit_path.with_suffix(".bsp"))
            if lit_report["issues"]:
                raise RuntimeError(f"lit fixture: {lit_report['issues']}")
            lit_fixture_checks(lit_path.with_suffix(".bsp"))
            reports.append({"game": game, "fixture": "lit", "issues": []})
            sampled_path = folder / 'lit-sky-samples.map'
            sampled_path.write_text(LIT_FIXTURE.replace('"classname" "worldspawn"',
                                   '"classname" "worldspawn"\n"_skysamples" "128"', 1))
            with sampled_path.with_suffix('.log').open('wb') as log:
                subprocess.run(command[:-1] + [str(sampled_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
            if validate(sampled_path.with_suffix('.bsp'))['issues']:
                raise RuntimeError('High-sample sky lighting failed structural validation')
            lit_fixture_checks(sampled_path.with_suffix('.bsp'))
            reports.append({'game': game, 'fixture': 'lit-sky-samples', 'issues': []})
            from decompile_bsp import decompile, rebuild, compile_scene
            project = folder / 'recovered-project'
            decompile(bsp, project)
            preserved = rebuild(project, folder / 'preserved-roundtrip')
            if Path(preserved['bsp']).read_bytes() != bsp.read_bytes():
                raise RuntimeError('Preservation round trip changed the compiler fixture')
            recovered = compile_scene(project, folder / 'recompiled-roundtrip', args.remap)
            if not recovered['prop_fields_equal']:
                raise RuntimeError('Scene round trip changed static props')
            reports.append({'game': game, 'fixture': 'decompile-and-rebuild', 'issues': []})
    (root / "results.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
