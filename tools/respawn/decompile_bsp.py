#!/usr/bin/env python3
"""Bounded TF2 scene recovery, preservation rebuild and experimental remap compile.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original implementation; credits/limits: docs/respawn/RESPAWN_DECOMPILE.md.
"""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess

from game_lump import inspect_game_lump
from inspect_bsp import FormatError, inspect
from recover_collision_map import plane_points
from tricoll import triangle_indices
from validate_records import load_records, validate


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, relative):
    p = (root / relative).resolve()
    if not p.is_relative_to(root.resolve()):
        raise FormatError('Project path escapes its directory')
    return p


def payload(path, inventory, index):
    entry = inventory['lumps'][index]
    default = next((v for v in entry['external_files'] if v['variant'] == 'default'), None)
    if default:
        return Path(default['path']).read_bytes()
    with path.open('rb') as stream:
        stream.seek(entry['offset'])
        return stream.read(entry['length'])


def parse_entities(text):
    """Preserve duplicate keyvalues. Reject incomplete/nested entity blocks."""
    tokens, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace() or c == '\0':
            i += 1; continue
        if text.startswith('//', i):
            end = text.find('\n', i); i = len(text) if end < 0 else end+1; continue
        if c in '{}':
            tokens.append(c); i += 1; continue
        if c != '"':
            raise FormatError('Expected a quoted entity key/value')
        i += 1; value = ''
        while i < len(text) and text[i] != '"':
            if text[i] == '\\' and i+1 < len(text) and text[i+1] in '\\"':
                i += 1
            value += text[i]; i += 1
        if i == len(text):
            raise FormatError('Unterminated entity string')
        i += 1; tokens.append(('value', value))
    result, i = [], 0
    while i < len(tokens):
        if tokens[i] != '{':
            raise FormatError('Expected entity opening brace')
        pairs = []; i += 1
        while i < len(tokens) and tokens[i] != '}':
            if i+1 >= len(tokens) or not isinstance(tokens[i], tuple) or not isinstance(tokens[i+1], tuple):
                raise FormatError('Entity key/value pair is incomplete')
            pairs.append([tokens[i][1], tokens[i+1][1]]); i += 2
        if i == len(tokens):
            raise FormatError('Unterminated entity block')
        result.append(pairs); i += 1
    return result


def quote(value):
    if not isinstance(value, str) or '\0' in value or '\n' in value or '\r' in value:
        raise FormatError('Entity value is not a single NUL-free string')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


def entity_text(pairs, primitives=()):
    return '{\n' + ''.join(quote(k)+' '+quote(v)+'\n' for k, v in pairs) + ''.join(primitives) + '}\n'


def collision_owners(records):
    result = collections.defaultdict(dict)
    if not records[85]:
        return result
    grid = records[85][0]
    world_cells = grid[3]*grid[4]
    for cell_id, (first, count) in enumerate(records[86]):
        model = 0 if cell_id <= world_cells else cell_id-world_cells
        for _, count, word in records[87][first:first+count]:
            words = [word] if count == 1 else [p[0] for p in records[89][(word>>8)&65535:((word>>8)&65535)+count]]
            for primitive in words:
                kind, index, contents = primitive>>24, (primitive>>8)&65535, primitive&255
                result[model][kind, index] = records[91][contents][0]
    return result


def render_components(records, model, pages, names):
    """Split by shared vertex edges so disconnected atlas islands pack compactly."""
    result = []
    first, count = records[14][model][6:8]
    for mesh in records[80][first:first+count]:
        sort = records[82][mesh[-2]]
        kind = mesh[-1] & 0x600
        pool = records[{0:72, 0x200:73, 0x400:71, 0x600:74}[kind]]
        raw = [sort[4]+v[0] for v in records[79][mesh[0]:mesh[0]+mesh[1]*3]]
        triangles = [raw[i:i+3] for i in range(0,len(raw),3) if len(set(raw[i:i+3])) == 3]
        parents = list(range(len(triangles)))
        def find(i):
            while parents[i] != i:
                parents[i] = parents[parents[i]]; i = parents[i]
            return i
        edges = {}
        for t, tri in enumerate(triangles):
            for a, b in zip(tri, tri[1:]+tri[:1]):
                edge = tuple(sorted((a,b)))
                if edge in edges:
                    parents[find(t)] = find(edges[edge])
                else:
                    edges[edge] = t
        groups = collections.defaultdict(list)
        for t, tri in enumerate(triangles):
            groups[find(t)].append(tri)
        for group in groups.values():
            for start in range(0, len(group), 21000):
                vertices, indices, local = [], [], {}
                for tri in group[start:start+21000]:
                    for index in tri:
                        if index not in local:
                            v = pool[index]
                            xyz, normal = records[3][v[0]], records[30][v[1]]
                            if not all(math.isfinite(x) for x in (*xyz,*normal,*v[2:4])):
                                raise FormatError('Nonfinite render vertex')
                            if sum(x*x for x in normal) < 1e-12:
                                # A malformed/unused normal has no direction to preserve.
                                a,b,c = (records[3][pool[j][0]] for j in tri)
                                u,w = [b[i]-a[i] for i in range(3)],[c[i]-a[i] for i in range(3)]
                                normal = (u[1]*w[2]-u[2]*w[1],u[2]*w[0]-u[0]*w[2],u[0]*w[1]-u[1]*w[0])
                                length = math.sqrt(sum(x*x for x in normal))
                                normal = tuple(x/length for x in normal) if length else (0,0,1)
                            uv = (0,0)
                            if kind < 0x400 and sort[1] >= 0:
                                _, width, height = pages[sort[1]]
                                uv = (v[8]*width, v[9]*height)
                            local[index] = len(vertices)
                            vertices.append([*xyz,*normal,*v[2:4],*v[4:8],*uv])
                        indices.append(local[index])
                result.append({'material':names[sort[0]], 'kind':kind, 'flags':mesh[-1],
                               'vertices':vertices,'indices':indices})
    return result


def write_mesh(path, meshes):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('wb') as stream:
        stream.write(struct.pack('<4sI',b'RSM1',len(meshes)))
        for mesh in meshes:
            name = ('textures/'+mesh['material']).encode('ascii')
            if not 0 < len(name) <= 255 or len(mesh['vertices']) > 65535 or len(mesh['indices']) > 63000:
                raise FormatError('Recovered mesh exceeds compiler limits')
            stream.write(struct.pack('<I',len(name))+name+struct.pack('<2I',len(mesh['vertices']),len(mesh['indices'])))
            for v in mesh['vertices']:
                stream.write(struct.pack('<8f4B2f',*v))
            stream.write(struct.pack('<'+'I'*len(mesh['indices']),*mesh['indices']))


def write_obj(path, meshes, assimp_preview=False):
    """Engine-space OBJ for inspection. RSM1/scene.json are the rebuild source."""
    with path.open('w',encoding='utf-8') as out:
        out.write('# Recovered engine-space geometry, Z up. No game textures embedded.\n')
        offset = 1
        for i, mesh in enumerate(meshes):
            out.write(f'o mesh_{i}\nusemtl {mesh["material"]}\n')
            for v in mesh['vertices']: out.write('v %.9g %.9g %.9g\n'%((v[0],v[2],-v[1]) if assimp_preview else tuple(v[:3])))
            for v in mesh['vertices']: out.write('vt %.9g %.9g\n'%((v[6],1-v[7]) if assimp_preview else tuple(v[6:8])))
            for v in mesh['vertices']: out.write('vn %.9g %.9g %.9g\n'%((v[3],v[5],-v[4]) if assimp_preview else tuple(v[3:6])))
            for t in range(0,len(mesh['indices']),3):
                tri = mesh['indices'][t:t+3]
                if assimp_preview: tri = tri[::-1]
                out.write('f '+' '.join(f'{j+offset}/{j+offset}/{j+offset}' for j in tri)+'\n')
            offset += len(mesh['vertices'])


def brush_text(records, index, names):
    b = records[92][index]
    planes = []
    for axis in range(3):
        for sign in (-1,1):
            n = [0,0,0]; n[axis]=sign
            planes.append((*n,sign*b[axis]+b[axis+6]))
    base = records[85][0][6]
    for j in range(b[4]):
        at = b[9]+j
        planes.append(records[1][base+at-records[93][at][0]])
    # Runtime side properties store nonaxial prefix, then six axial sides.
    first = 6*b[5]+b[9]
    materials = [names[records[94][first+b[4]+j][0]&511] for j in range(6)]
    materials += [names[records[94][first+j][0]&511] for j in range(b[4])]
    lines = ['{\n']
    for plane, material in zip(planes,materials):
        coords = ' '.join('( %.9g %.9g %.9g )'%p for p in plane_points(plane))
        lines.append(coords+' '+material+' 0 0 0 1 1 0 0 0\n')
    return ''.join(lines)+'}\n'


def collision_patch(points, material):
    # 2x2 sampled grid with one real triangle, one degenerate. Native recovery
    # mode imports render meshes separately; these patches only supply collision.
    a,b,c = ['( %.9g %.9g %.9g 0 0 )'%tuple(p) for p in points]
    return '{\npatchDef2\n{\n'+material+'\n( 2 2 0 0 0 )\n(\n( '+a+' '+b+' )\n( '+c+' '+c+' )\n)\n}\n}\n'


def decompile(path, root):
    path, root = Path(path).resolve(), Path(root).resolve()
    report = validate(path)
    if report['version'] != 37 or report['issues']:
        raise FormatError('Scene recovery requires validated little-endian TF2 BSP v37; repair malformed ports first')
    root.mkdir(parents=True,exist_ok=False)
    inv = inspect(path)
    records = load_records(path,inv)
    preserved = root/'preserved'; preserved.mkdir()
    files = [{'path':path.name,'role':'bsp'}]
    for entry in inv['lumps']:
        files.extend({'path':Path(e['path']).name,'role':'sidecar'} for e in entry['external_files'])
    files.extend({'path':Path(e['path']).name,'role':'entity'} for e in inv['entity_files'])
    for file in files:
        contents = (path.parent/file['path']).read_bytes()
        (preserved/file['path']).write_bytes(contents)
        file['sha256'] = digest(contents)
    lumps = []; (root/'lumps').mkdir()
    for index, entry in enumerate(inv['lumps']):
        contents = payload(path,inv,index)
        relative = f'lumps/{index:04x}.bin'; (root/relative).write_bytes(contents)
        lumps.append({'index':index,'path':relative,'sha256':digest(contents),'version':entry['version']})
    groups = [{'name':'embedded','prefix':'','entities':parse_entities(payload(path,inv,0).decode('utf-8',errors='surrogateescape'))}]
    for e in inv['entity_files']:
        raw = Path(e['path']).read_bytes().decode('utf-8',errors='surrogateescape')
        end = raw.find('\n')
        if not raw.startswith(('ENTITIES01','ENTITIES02')) or end < 0:
            raise FormatError('Unrecognized entity partition header')
        groups.append({'name':e['kind'],'prefix':raw[:end+1],'entities':parse_entities(raw[end+1:])})
    entity_data = (json.dumps(groups,indent=2,ensure_ascii=True)+'\n').encode()
    (root/'entities.json').write_bytes(entity_data)
    game = inspect_game_lump(path,True)
    props = [p for e in game['entries'] if e['decoded'] for p in e['placements']]
    (root/'props.json').write_text(json.dumps(props,indent=2)+'\n')
    strings = payload(path,inv,43)
    table = [o[0] for o in struct.iter_unpack('<I',payload(path,inv,44))]
    names = [strings[table[t[3]]:strings.index(0,table[t[3]])].decode('ascii').replace('\\','/').lower()
             for t in records[2]]
    pages = list(struct.iter_unpack('<I2H',payload(path,inv,83)))
    scene = {'models':[render_components(records,m,pages,names) for m in range(len(records[14]))]}
    (root/'scene.json').write_text(json.dumps(scene,separators=(',',':'))+'\n')
    owners = collision_owners(records)
    all_entities = [e for group in groups for e in group['entities']]
    model_entities = collections.defaultdict(list)
    for e in all_entities:
        kv = dict(e)
        if kv.get('classname') == 'worldspawn': model_entities[0].append(e)
        elif re.fullmatch(r'\*\d+',kv.get('model','')): model_entities[int(kv['model'][1:])].append(e)
    map_entities, shaders, warnings = [], {}, []
    for m, meshes in enumerate(scene['models']):
        mesh_path = f'models/recovered/model_{m}.rsm'
        write_mesh(root/'assets'/mesh_path,meshes)
        write_obj(root/f'model_{m}.obj',meshes)
        write_obj(root/f'assets/models/recovered/model_{m}.obj',meshes,True)
        primitives, contents_keys = [], []
        for (kind,index), contents in sorted(owners[m].items()):
            if kind == 0:
                contents_keys.append([f'_remap_contents_{len(primitives)}',str(contents)])
                primitives.append(brush_text(records,index,names))
            elif kind == 0x40:
                h = records[69][index]
                material = names[h[2]]
                for (word,) in records[66][h[7]:h[7]+h[4]]:
                    points = [records[3][h[6]+v] for v in triangle_indices(word)]
                    if len(set(points)) == 3:
                        contents_keys.append([f'_remap_contents_{len(primitives)}',str(contents)])
                        primitives.append(collision_patch(points,material))
            elif kind != 0x60:
                warnings.append(f'model {m}: unsupported collision primitive kind {kind:#x}')
        for mesh in meshes:
            spec = (mesh['kind'],mesh['flags']&0x14)
            if mesh['material'] in shaders and shaders[mesh['material']] != spec:
                warnings.append('Mixed vertex formats for material '+mesh['material'])
            shaders.setdefault(mesh['material'],spec)
        entities = model_entities[m]
        if not entities:
            warnings.append(f'Model {m} has no referring entity; exported mesh is retained separately')
        for e in entities:
            pairs = [[k,v] for k,v in e if k != 'model' and not k.startswith('_remap_')]
            pairs += [['_remap_mesh',mesh_path],*contents_keys]
            map_entities.append(entity_text(pairs,primitives))
            pose = dict(e)
            map_entities.append(entity_text([['classname','misc_model'],['model',f'models/recovered/model_{m}.obj'],
                ['origin',pose.get('origin','0 0 0')],['angles',pose.get('angles','0 0 0')],['_remap_preview','1']]))
    for e in all_entities:
        kv = dict(e)
        if kv.get('classname') != 'worldspawn' and not re.fullmatch(r'\*\d+',kv.get('model','')):
            map_entities.append(entity_text(e))
    # TF2 object references use a 64-aligned non-sky world-mesh namespace,
    # independent of the world model's total (including sky) mesh count.
    level_info = payload(path,inv,123)
    if len(level_info) != 28:
        raise FormatError('Scene recovery requires one TF2 LEVEL_INFO record')
    first_sky = struct.unpack_from('<I',level_info,8)[0]
    prop_base = (first_sky + 63) & ~63
    bounds = collections.defaultdict(list)
    for (ref,), b in zip(records[120],records[121]):
        if ref >= prop_base:
            bounds[ref-prop_base].append(b)
    for p in props:
        radius = 128.
        for b in bounds[p['index']]:
            for corner in (b[:3],b[4:7]):
                radius = max(radius,math.sqrt(sum((corner[a]-p['origin'][a])**2 for a in range(3))))
        pairs = [['classname','prop_static'],['model',p['model']],['origin',' '.join(map(str,p['origin']))],
                 ['angles',' '.join(map(str,p['angles_raw']))],['modelscale',str(p['scale'])],['skin',str(p['skin'])],
                 ['solid',str(p['solid'])],['flags',str(p['flags'])],['_cullradius',str(radius)]]
        pairs += [['_remap_prop_fade_scale',str(p['fade_scale'])],['_remap_prop_cubemap',str(p['cubemap_raw'])],
                  ['_remap_prop_rgba',' '.join(map(str,p['diffuse_modulation']))],
                  ['_remap_prop_levels',' '.join(map(str,(*p['cpu_levels'],*p['gpu_levels'])))],
                  ['_remap_prop_collision_add',str(p['collision_flags'][0])],
                  ['_remap_prop_collision_remove',str(p['collision_flags'][1])]]
        if p['lighting_origin'] is not None:
            pairs += [['_remap_prop_lighting_origin',' '.join(map(str,p['lighting_origin']))]]
        map_entities.append(entity_text(pairs))
    # Collision-only tool materials still need shader definitions. Rendering is
    # supplied by RSM1, so these shader references retain their original names.
    for name in names: shaders.setdefault(name,(0x200,4 if 'sky' in name else 0))
    shader_text = ''
    for name,(kind,flags) in sorted(shaders.items()):
        body = '$shadertype '+{0:'LitFlatGeneric',0x200:'LitBumpGeneric',0x400:'UnlitGeneric',0x600:'UnlitTSGeneric'}[kind]
        if flags&4: body += '\n $compileflag sky\n $surfaceflag sky'
        if flags&16: body += '\n $compileflag trans'
        if 'clip' in name:
            body += '\n $contentflag playerclip' if 'human' in name or 'player' in name else ''
        shader_text += 'textures/'+name+'\n{\n '+body+'\n}\n'
    target = root/'assets/shaders/recovered.shader'; target.parent.mkdir(parents=True,exist_ok=True); target.write_text(shader_text)
    (root/(path.stem+'.map')).write_text('// Recovered render meshes + collision, not original editor CSG.\n'+''.join(map_entities),encoding='utf-8')
    manifest = {'format':'MRVN-decompile-1','source_name':path.name,'files':files,'lumps':lumps,
                'entities_sha256':digest(entity_data),'models':len(records[14]),'props':len(props),
                'render_triangles':sum(len(m['indices'])//3 for mm in scene['models'] for m in mm),
                'render_charts':sum(map(len,scene['models'])),'collision_brushes':len(records[92]),
                'collision_triangles':len(records[66]),'warnings':sorted(set(warnings))}
    (root/'project.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def rebuild(root, output):
    root, output = Path(root).resolve(),Path(output).resolve()
    project = json.loads((root/'project.json').read_text())
    if project['format'] != 'MRVN-decompile-1' or output.exists():
        raise FormatError('Unsupported project or output exists')
    for entry in project['lumps']:
        if digest(safe_path(root,entry['path']).read_bytes()) != entry['sha256']:
            raise FormatError('Raw lump edits require a typed writer; preservation rebuild refuses them')
    output.mkdir(parents=True)
    for entry in project['files']:
        source = safe_path(root/'preserved',entry['path'])
        if digest(source.read_bytes()) != entry['sha256']:
            raise FormatError('Preserved input was modified')
        shutil.copyfile(source,safe_path(output,entry['path']))
    bsp = safe_path(output,project['source_name'])
    edited = (root/'entities.json').read_bytes()
    if digest(edited) != project['entities_sha256']:
        groups = json.loads(edited)
        data = bytearray(bsp.read_bytes())
        for group in groups:
            body = ''.join(entity_text(e) for e in group['entities']).encode('utf-8',errors='surrogateescape')+b'\0'
            if group['name'] == 'embedded':
                sidecar = output/(bsp.name+'.0000.bsp_lump')
                if sidecar.exists(): sidecar.write_bytes(body)
                else:
                    at = (len(data)+15)&~15; data += bytes(at-len(data))+body
                    struct.pack_into('<4I',data,16,at,len(body),0,0)
            elif re.fullmatch(r'[a-z]+',group['name']):
                (output/(bsp.stem+'_'+group['name']+'.ent')).write_bytes(group['prefix'].encode()+body)
            else: raise FormatError('Invalid entity partition name')
        bsp.write_bytes(data)
    result = validate(bsp)
    if result['issues']: raise FormatError('Rebuilt BSP failed selected-record validation')
    return {'bsp':str(bsp),'sha256':digest(bsp.read_bytes()),'preserved_byte_identical':digest(edited)==project['entities_sha256']}


def compile_scene(root, output, remap, allow_edits=False):
    root,output = Path(root).resolve(),Path(output).resolve()
    if output.exists(): raise FormatError('Compile output must be a new directory')
    output.mkdir(parents=True)
    project = json.loads((root/'project.json').read_text())
    scene = json.loads((root/'scene.json').read_text())
    for m, meshes in enumerate(scene['models']):
        write_mesh(root/f'assets/models/recovered/model_{m}.rsm',meshes)
    map_path = root/(Path(project['source_name']).stem+'.map')
    # Compile a copy, so remap cannot overwrite an exported source's sibling BSP.
    build_map = output/map_path.name; shutil.copyfile(map_path,build_map)
    command = [str(Path(remap).resolve()),'-game','titanfall2','-fs_basepath',str(root),'-bsp',str(build_map)]
    with (output/'compile.log').open('wb') as log:
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    result = validate(build_map.with_suffix('.bsp'))
    (output/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    if result['issues']: raise FormatError('Compiled recovered scene failed selected-record validation')
    bsp = build_map.with_suffix('.bsp')
    inv = inspect(bsp); r = load_records(bsp,inv)
    strings = payload(bsp,inv,43)
    table = [t[0] for t in struct.iter_unpack('<I',payload(bsp,inv,44))]
    names = [strings[table[t[3]]:strings.index(0,table[t[3]])].decode().replace('\\','/').lower() for t in r[2]]
    pages = list(struct.iter_unpack('<I2H',payload(bsp,inv,83)))
    actual = {'models':[render_components(r,m,pages,names) for m in range(len(r[14]))]}
    def signature(scene):
        counts = collections.Counter()
        for model, meshes in enumerate(scene['models']):
            for mesh in meshes:
                for t in range(0,len(mesh['indices']),3):
                    vertices = [mesh['vertices'][i] for i in mesh['indices'][t:t+3]]
                    tri = tuple(tuple(round(x,5) for x in (*v[:3],*v[6:8])) for v in vertices)
                    key = min(tri,tri[1:]+tri[:1],tri[2:]+tri[:2])
                    counts[model,mesh['material'],key] += 1
        return counts
    expected, observed = signature(scene),signature(actual)
    comparison = {'expected_triangles':sum(expected.values()),'compiled_triangles':sum(observed.values()),
                  'missing_triangles':sum((expected-observed).values()),'added_triangles':sum((observed-expected).values())}
    (output/'render-comparison.json').write_text(json.dumps(comparison,indent=2)+'\n')
    if expected != observed and not allow_edits:
        raise FormatError(f'Render geometry/UV round trip differs: {comparison}; use a compiler with RSM1 support')
    original = safe_path(root/'preserved',project['source_name'])
    old_inv = inspect(original); old = load_records(original,old_inv)
    def collision_signature(records):
        triangles, brushes = collections.Counter(),collections.Counter()
        for model, shapes in collision_owners(records).items():
            for (kind,index), contents in shapes.items():
                if kind == 0:
                    b = records[92][index]
                    brushes[model,contents,tuple(round(x,3) for x in (*b[:3],*b[6:9]))] += 1
                elif kind == 0x40:
                    h = records[69][index]
                    for (word,) in records[66][h[7]:h[7]+h[4]]:
                        tri = tuple(tuple(round(x,3) for x in records[3][h[6]+v]) for v in triangle_indices(word))
                        if len(set(tri)) < 3: continue
                        triangles[model,contents,min(tri,tri[1:]+tri[:1],tri[2:]+tri[:2])] += 1
        return triangles,brushes
    old_tri,old_brush = collision_signature(old); new_tri,new_brush = collision_signature(r)
    collision = {'expected_triangles':sum(old_tri.values()),'compiled_triangles':sum(new_tri.values()),
                 'triangle_geometry_contents_equal':old_tri==new_tri,'brush_bounds_contents_equal':old_brush==new_brush}
    (output/'collision-comparison.json').write_text(json.dumps(collision,indent=2)+'\n')
    if (old_tri != new_tri or old_brush != new_brush) and not allow_edits:
        raise FormatError(f'Recovered collision geometry/contents differ: {collision}')
    original_props = json.loads((root/'props.json').read_text())
    compiled_props = [p for entry in inspect_game_lump(bsp,True)['entries'] if entry['decoded'] for p in entry['placements']]
    fields = ('model','origin','angles_raw','scale','solid','flags','skin','cubemap_raw','fade_scale',
              'lighting_origin','cpu_levels','gpu_levels','diffuse_modulation','collision_flags')
    def prop_signature(p):
        return json.dumps({k:p[k] for k in fields},sort_keys=True)
    props_equal = [prop_signature(p) for p in original_props] == [prop_signature(p) for p in compiled_props]
    (output/'prop-comparison.json').write_text(json.dumps({'expected':len(original_props),'compiled':len(compiled_props),
                                                        'placement_fields_equal':props_equal},indent=2)+'\n')
    if not props_equal and not allow_edits: raise FormatError('Recovered static prop fields differ')
    return {'bsp':str(bsp),'issues':result['issues'],'render_comparison':comparison,
            'collision_comparison':collision,'prop_fields_equal':props_equal,'engine_verified':False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command',required=True)
    export = commands.add_parser('export'); export.add_argument('bsp',type=Path); export.add_argument('project',type=Path)
    build = commands.add_parser('rebuild'); build.add_argument('project',type=Path); build.add_argument('output',type=Path)
    compile = commands.add_parser('compile'); compile.add_argument('project',type=Path); compile.add_argument('output',type=Path); compile.add_argument('--remap',required=True,type=Path)
    compile.add_argument('--allow-edits',action='store_true',help='report intentional scene/collision/prop differences without failing the round-trip gate')
    args = parser.parse_args()
    if args.command == 'export': result = decompile(args.bsp,args.project)
    elif args.command == 'rebuild': result = rebuild(args.project,args.output)
    else: result = compile_scene(args.project,args.output,args.remap,args.allow_edits)
    print(json.dumps(result,indent=2))


if __name__ == '__main__':
    main()
