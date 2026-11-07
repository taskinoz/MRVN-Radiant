"""Port a Source engine map (Half-Life 2, Team Fortress 2, ...) to a Titanfall 2 Northstar mod.

Reads the compiled BSP's brush list, which keeps every original brush, and its
displacements, entities and textures. Writes an editable Valve 220 .map, then
compiles and packages it like the Minecraft ports.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

import numpy as np
from PIL import Image

from build_minecraft_ports import MESH_BUDGET, visibility_coverage, write_dds_bc1
from build_quake_materials import solid, write_dds
from compiler_regression import entity
from inspect_bsp import inspect
from minecraft_scenery import SKY_LEVEL, sky_dome
from pack_vpk import pack_files
from rpak import RPak
from source_engine import (BSP, Content, CONTENTS_GRATE, CONTENTS_PLAYERCLIP, CONTENTS_SOLID, CONTENTS_WINDOW, Model,
                           SURF_HINT, SURF_NODRAW, SURF_SKIP, SURF_SKY, SURF_SKY2D, angle_matrix, material_info, read_vtf,
                           vtf_size, VERTEXES, EDGES, SURFEDGES, FACES)
from validate_records import load_records, validate
import stbsp

VERSION = '0.1.0'
ASSET_ROOT = 'world/source_ports/'
MESH_CLUSTER = 3072
MAX_TEXTURE = 1024
SPAWN_SPACING = 160
# Mesh grid cells up to the whole map; Source maps are far larger than the Minecraft ports.
MAX_MESH_CLUSTER = 262144
LUXEL_SIZE = 16
MAX_LUXEL_SIZE = 128
# Converted maps tested in game have used at most six lightmap pages (Drop-Off: four of 2048 pixels);
# more is untested, so bigger maps get coarser lightmaps instead.
LIGHTMAP_PAGE = 2048
MAX_LIGHTMAP_PAGES = 6
# Displacement collision grid size (control points per side); remap collides each grid quad separately.
DISPLACEMENT_COLLISION = 5
# Brush entities that stand still in the original; doors and breakables are left out, so their openings are open.
NONSOLID = '_ns'  # material suffix of render-only (non-colliding) brushes
# Brush entities that render but never collide in Source.
RENDER_ONLY_ENTITIES = {'func_illusionary'}
STATIC_BRUSH_ENTITIES = {'func_brush', 'func_wall', 'func_lod', 'func_detail', 'func_wall_toggle'}
TOOL_MATERIALS = {'tools/toolsclip': '_clip', 'tools/toolsplayerclip': '_clip', 'tools/toolsblack': '_black'}
# Ground NPC nodes are on walkable floor; HL2 has no multiplayer spawns to use.
NODE_CLASSES = {'info_node', 'info_node_hint'}
CS_SPAWNS = {'info_player_terrorist': 2, 'info_player_counterterrorist': 3}


def sanitize(name):
    return re.sub(r'[^a-z0-9_/]', '_', name.lower().replace('\\', '/'))


def tangents(normal):
    """Two axes with t1 x t2 = normal."""
    n = np.array(normal, float)
    helper = np.array((0, 0, 1.0)) if abs(n[2]) < .9 else np.array((1.0, 0, 0))
    t1 = np.cross(helper, n); t1 /= np.linalg.norm(t1)
    return t1, np.cross(n, t1)


def valve_face(normal, dist, material, s, t):
    """Valve 220 brush face: three points whose winding gives the outward normal."""
    p1 = np.array(normal, float)*dist; t1, t2 = tangents(normal)
    points = (p1, p1+t2*1024, p1+t1*1024)
    return (' '.join('( %.4f %.4f %.4f )' % tuple(p) for p in points)+f' {material} '
            f'[ {s[0]:.6g} {s[1]:.6g} {s[2]:.6g} {s[3]:.6g} ] [ {t[0]:.6g} {t[1]:.6g} {t[2]:.6g} {t[3]:.6g} ] 0 1 1')


def valve_box(lo, hi, material, texels_per_unit=.25):
    faces = []
    for axis in range(3):
        for sign, d in ((-1, -lo[axis]), (1, hi[axis])):
            n = [0, 0, 0]; n[axis] = sign
            u = [0.0]*4; v = [0.0]*4
            # Axial projection like Quake's: drop the face axis.
            a, b = [(1, 2), (0, 2), (0, 1)][axis]
            u[a] = texels_per_unit; v[b] = -texels_per_unit
            faces.append(valve_face(n, d, material, u, v))
    return '{\n'+'\n'.join(faces)+'\n}'


def cubemap_direction_lookup(faces, directions):
    """Sample a Source skybox (rt bk lf ft up dn images) along unit directions (..., 3)."""
    x, y, z = directions[..., 0], directions[..., 1], directions[..., 2]
    ax, ay, az = np.abs(x), np.abs(y), np.abs(z)
    out = np.zeros(directions.shape[:-1]+(3,), np.float32)
    # Engine st_to_vec for rt bk lf ft up dn, inverted: face, mask, s, t.
    cases = (('rt', (ax >= ay) & (ax >= az) & (x > 0), -y/ax, z/ax),
             ('bk', (ax >= ay) & (ax >= az) & (x <= 0), y/ax, z/ax),
             ('lf', (ay > ax) & (ay >= az) & (y > 0), x/ay, z/ay),
             ('ft', (ay > ax) & (ay >= az) & (y <= 0), -x/ay, z/ay),
             ('up', (az > ax) & (az > ay) & (z > 0), -y/az, -x/az),
             ('dn', (az > ax) & (az > ay) & (z <= 0), -y/az, x/az))
    for name, mask, s, t in cases:
        image = faces[name]; h, w = image.shape[:2]
        u = np.clip(((s+1)/2*w).astype(int), 0, w-1); v = np.clip(((1-t)/2*h).astype(int), 0, h-1)
        out[mask] = image[v[mask], u[mask], :3]
    return out


def source_sky_texture(faces, size=2048):
    """The skybox's upper hemisphere in sky_dome's azimuthal projection."""
    axis = (np.arange(size)+.5)/size*2-1
    u, v = np.meshgrid(axis, axis)
    r = np.minimum(np.hypot(u, v), 1); theta = r*math.pi/2
    scale = np.sin(theta)/np.maximum(r, 1e-6)
    directions = np.stack((u*scale, v*scale, np.cos(theta)), -1)
    rgb = cubemap_direction_lookup(faces, directions)
    rgb = np.clip(rgb*SKY_LEVEL, 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, np.full((size, size), 255, np.uint8)]), 'RGBA')


def load_skybox(content, skyname):
    faces = {}
    for base in dict.fromkeys((skyname.removesuffix('_hdr'), skyname)):
        try:
            for face in ('rt', 'bk', 'lf', 'ft', 'up', 'dn'):
                shader, values = material_info(content, 'skybox/'+base+face)
                faces[face] = np.asarray(read_vtf(content.read('materials/'+values['$basetexture'].replace('\\', '/')+'.vtf')))
            return faces
        except (KeyError, ValueError):
            faces = {}
    return None


def mip_levels(image):
    levels = []; im = image
    while True:
        levels.append((im.width, im.height, im.tobytes()))
        if im.width == 1 and im.height == 1: return levels
        im = im.resize((max(1, im.width//2), max(1, im.height//2)), Image.Resampling.BOX)


def choose_spawns(bsp, middle):
    """Four spawns per team: Source team spawns where the map has them, else NPC nodes at opposite ends."""
    teams = {2: [], 3: []}
    for e in bsp.entities:
        if e.get('classname') == 'info_player_teamspawn' and e.get('TeamNum') in ('2', '3'):
            teams[int(e['TeamNum'])].append(tuple(map(float, e['origin'].split())))
        # Counter-Strike: Source and CS:GO spawns.
        elif e.get('classname') in CS_SPAWNS:
            teams[CS_SPAWNS[e['classname']]].append(tuple(map(float, e['origin'].split())))
    if all(teams.values()):
        return {t: spread(p, p[0]) for t, p in teams.items()}
    nodes = np.array([tuple(map(float, e['origin'].split())) for e in bsp.entities if e.get('classname') in NODE_CLASSES])
    if len(nodes) < 8:
        nodes = np.array([tuple(map(float, e['origin'].split())) for e in bsp.entities if e.get('classname') == 'info_player_start'])
    if not len(nodes): raise ValueError('no spawn candidates; pass --spawns')
    flat = nodes[:, :2]-flat_mean(nodes)
    axis = np.linalg.svd(flat, full_matrices=False)[2][0]
    along = flat@axis
    ends = (nodes[along.argmin()], nodes[along.argmax()])
    return {t: spread([tuple(p) for p in nodes], tuple(end)) for t, end in zip((2, 3), ends)}


def flat_mean(nodes):
    return nodes[:, :2].mean(0)


def spread(points, target, count=4):
    chosen = []
    for p in sorted(points, key=lambda p: math.dist(p[:2], target[:2])):
        if all(math.dist(p[:2], q[:2]) >= SPAWN_SPACING for q in chosen): chosen.append(p)
        if len(chosen) == count: break
    return chosen


class Materials:
    """Source materials to Titanfall 2 ones, keyed by base texture so cubemap patches share one."""

    def __init__(self, bsp, content, prefix, templates=None):
        self.bsp = bsp; self.content = content; self.prefix = prefix
        self.textures = {}; self.missing = Counter(); self.invisible = set(); self.nonsolid = set()
        # extract_material_templates.py output: with it, $translucent and $alphatest
        # textures draw blended and alpha-tested instead of opaque or invisible.
        self.templates = templates; self.kinds = {}

    def see_through(self, values):
        """'translucent', 'cutout' or None for a Source material's keys."""
        if not self.templates: return None
        if values.get('$translucent') == '1': return 'translucent'
        if values.get('$alphatest') == '1': return 'cutout'
        return None

    def render_only(self, name):
        """A non-colliding variant of a material, for Source func_illusionary and non-solid brushes."""
        base = name[len(self.prefix):]
        if base.startswith('_'): return name  # nodraw, sky and clip stay as they are
        self.nonsolid.add(base); return name+NONSOLID

    def name(self, texinfo_index):
        if texinfo_index < 0: return self.prefix+'_nodraw'
        info = self.bsp.texinfo[texinfo_index]
        if info.flags & (SURF_SKY | SURF_SKY2D): return self.prefix+'_skyhole'
        material = (info.material or '').lower().replace('\\', '/')
        if material in TOOL_MATERIALS: return self.prefix+TOOL_MATERIALS[material]
        if material.startswith('tools/') or info.flags & (SURF_NODRAW | SURF_HINT | SURF_SKIP):
            return self.prefix+'_nodraw'
        texdata = next(t for t in self.bsp.texdata if t[0] == info.material)
        try:
            shader, values = material_info(self.content, material)
        except KeyError:
            self.missing[material] += 1; shader, values = None, {}
        kind = self.see_through(values)
        if shader == 'water' or not kind and values.get('$translucent') == '1' and 'glass' in material:
            # Clear glass stays solid but unseen: an opaque pane would hide the room.
            self.invisible.add(material); return self.prefix+'_nodraw'
        base = sanitize(values.get('$basetexture', material))
        if kind: self.kinds[base] = kind
        self.textures.setdefault(base, (values.get('$basetexture'), texdata[1], texdata[2], values))
        return self.prefix+base

    def build(self, out, args, sky_image, void_colour):
        assets = out/'assets'; files = []; shader = []
        def texture(name, levels):
            path = 'texture/'+self.prefix+name+'.rpak'
            write_dds_bc1(assets/Path(path).with_suffix('.dds'), levels)
            files.append({'_type': 'txtr', '_path': path, '$disableStreaming': True}); return path
        flats = {'1': texture('_normal', solid((128, 128, 255, 255))), '2': texture('_gloss', solid((18, 18, 18, 255))),
                 '3': texture('_spec', solid((5, 5, 5, 255)))}
        images = {'_sky': sky_image, '_sky_void': Image.new('RGBA', (64, 64), void_colour), '_black': Image.new('RGBA', (16, 16), (0, 0, 0, 255))}
        for name, (vtf, width, height, values) in sorted(self.textures.items()):
            try:
                # Source 2 ports pass exported images instead of VTF names.
                if isinstance(vtf, Path): image = Image.open(vtf).convert('RGBA')
                else: image = read_vtf(self.content.read('materials/'+vtf.replace('\\', '/').lower()+'.vtf'))
                if values.get('tint'): image = Image.fromarray(np.clip(np.asarray(image)*np.array(values['tint']), 0, 255).astype(np.uint8))
            except (KeyError, ValueError, AttributeError, OSError):
                self.missing[name] += 1; image = Image.new('RGBA', (64, 64), (128, 128, 128, 255))
            if self.kinds.get(name) == 'translucent' and image.getextrema()[3][0] == 255:
                # Blended without any transparency (often a missing glass texture): faint glass instead of a grey wall.
                image = Image.blend(image, Image.new('RGBA', image.size, (200, 215, 225, 255)), 0.5); image.putalpha(70)
            if min(image.size) < 4:
                # A pak with a BC1 texture smaller than one 4x4 block never finishes loading.
                image = image.resize((max(4, image.width), max(4, image.height)), Image.Resampling.NEAREST)
            if image.getextrema()[3][0] < 255 and name not in self.kinds:
                # Without templates, alpha-tested fences and decals become opaque.
                backing = Image.new('RGBA', image.size, (60, 60, 60, 255)); backing.alpha_composite(image); image = backing
            images[name] = (image, width, height)
        for name in ('_nodraw', '_skyhole', '_clip'):
            shader.append(f'textures/{self.prefix}{name}\n{{\n $compileflag nodraw\n'+(' $contentflag playerclip\n' if name == '_clip' else '')+'}\n')
        for name, entry in sorted(images.items()):
            image, width, height = entry if isinstance(entry, tuple) else (entry, entry.width, entry.height)
            # Remap divides texinfo texels by this image's size, so it keeps the BSP's texture size.
            png = assets/('textures/'+self.prefix+name+'.png'); png.parent.mkdir(parents=True, exist_ok=True)
            if name in self.kinds:
                # The lightmapper reads alpha-tested shadows from this image's alpha.
                image.convert('RGBA').resize((width, height), Image.Resampling.NEAREST).save(png)
            else:
                Image.new('RGB', (width, height)).save(png)
            scale = min(1, MAX_TEXTURE/max(image.size))
            if scale < 1: image = image.resize((int(image.width*scale), int(image.height*scale)), Image.Resampling.LANCZOS)
            kind = self.kinds.get(name)
            if kind:
                # BC1 has no alpha channel to blend or test.
                path = 'texture/'+self.prefix+name+'.rpak'
                write_dds(assets/Path(path).with_suffix('.dds'), mip_levels(image.convert('RGBA')), True)
                files.append({'_type': 'txtr', '_path': path, '$disableStreaming': True}); albedo = path
                write_see_through(assets, files, self.templates, kind, self.prefix+name, image.size, albedo, flats)
            else:
                albedo = texture(name, mip_levels(image.convert('RGBA')))
            for suffix in (() if kind else ('_colpass_wld', '_wld')):
                src = args.material_template.with_name(args.material_template.name+suffix)
                spec = json.loads(src.with_suffix('.json').read_text())
                spec.update(name=self.prefix+name+('_colpass' if suffix.startswith('_colpass') else ''), width=image.width, height=image.height)
                spec['$textures'] = {'0': albedo, **flats}
                spec['$colpassMaterial'] = '0x0' if suffix.startswith('_colpass') else 'material/'+self.prefix+name+'_colpass_wld.rpak'
                dst = assets/('material/'+self.prefix+name+suffix+'.rpak'); dst.parent.mkdir(parents=True, exist_ok=True)
                dst.with_suffix('.json').write_text(json.dumps(spec, indent=2)); shutil.copyfile(src.with_suffix('.uber'), dst.with_suffix('.uber'))
                files.append({'_type': 'matl', '_path': dst.relative_to(assets).as_posix()})
            flags = {'translucent': ' $compileflag trans\n', 'cutout': ' $compileflag alphashadow\n'}.get(kind, '')
            shader.append(f'textures/{self.prefix}{name}\n{{\n $shadertype LitBumpGeneric\n'+(' $compileflag sky\n' if name.startswith('_sky') else '')+flags+'}\n')
            if name in self.nonsolid:
                # The same textures under a second name whose shader has no collision.
                for suffix in ('_colpass_wld', '_wld'):
                    src = assets/('material/'+self.prefix+name+suffix+'.rpak')
                    if not src.with_suffix('.json').exists(): continue  # translucent ones have no colpass
                    spec = json.loads(src.with_suffix('.json').read_text())
                    spec['name'] = self.prefix+name+NONSOLID+('_colpass' if suffix.startswith('_colpass') else '')
                    if not suffix.startswith('_colpass'):
                        spec['$colpassMaterial'] = 'material/'+self.prefix+name+NONSOLID+'_colpass_wld.rpak'
                    dst = assets/('material/'+self.prefix+name+NONSOLID+suffix+'.rpak')
                    dst.with_suffix('.json').write_text(json.dumps(spec, indent=2)); shutil.copyfile(src.with_suffix('.uber'), dst.with_suffix('.uber'))
                    files.append({'_type': 'matl', '_path': dst.relative_to(assets).as_posix()})
                shutil.copyfile(png, assets/('textures/'+self.prefix+name+NONSOLID+'.png'))
                shader.append(f'textures/{self.prefix}{name}{NONSOLID}\n{{\n $shadertype LitBumpGeneric\n $contentflag nonsolid\n{flags}}}\n')
        shaders = assets/'shaders'; shaders.mkdir(parents=True, exist_ok=True)
        (shaders/'source_ports.shader').write_text('\n'.join(shader))
        pak = 'source_'+args.name
        manifest = {'version': 7, 'name': pak, 'keepDevOnly': True, 'assetsDir': str(assets), 'outputDir': str(out/'pak-build'),
                    'compressLevel': 0, 'hasDynamicLibrary': False, 'files': files}
        (out/'build-rpak.json').write_text(json.dumps(manifest, indent=2))
        with (out/'repak.log').open('wb') as log:
            subprocess.run([str(args.repak.resolve()), str(out/'build-rpak.json')], cwd=out, stdout=log, stderr=subprocess.STDOUT, check=True)
        return RPak(out/'pak-build'/(pak+'.rpak'))


def write_see_through(assets, files, templates, kind, material, size, albedo, flats):
    """Translucent or alpha-tested world material from extract_material_templates.py output."""
    def clone(key, name, textures, extra={}):
        spec = json.loads((templates/(key+'.json')).read_text())
        spec.update(name=name, width=size[0], height=size[1], **extra); spec['$textures'] = textures
        dst = assets/('material/'+name+'_wld.rpak'); dst.parent.mkdir(parents=True, exist_ok=True)
        dst.with_suffix('.json').write_text(json.dumps(spec, indent=2)); shutil.copyfile(templates/(key+'.uber'), dst.with_suffix('.uber'))
        files.append({'_type': 'matl', '_path': dst.relative_to(assets).as_posix()})
        return dst.relative_to(assets).as_posix()
    if kind == 'translucent':
        return clone('translucent_wld', material, {'0': albedo, **flats})
    # Alpha-tested depth passes, or the holes cast shadows and fill the depth prepass.
    depth = {f'$depth{K}Material': clone(f'cutout_{k}_wld', 'depth/'+material+'_'+k, {'0': albedo})
             for k, K in (('shadow', 'Shadow'), ('prepass', 'Prepass'), ('vsm', 'VSM'))}
    colpass = clone('cutout_colpass_wld', material+'_colpass', {'0': albedo, **flats}, depth)
    return clone('cutout_wld', material, {'0': albedo, **flats}, {**depth, '$colpassMaterial': colpass})


def prop_material(materials, candidates):
    """Material for a prop mesh, or None for additive ones, and for cutout and translucent ones without templates."""
    for name in candidates:
        try: shader, values = material_info(materials.content, name)
        except KeyError: continue
        kind = materials.see_through(values)
        if values.get('$additive') == '1' or not kind and any(values.get(k) == '1' for k in ('$translucent', '$alphatest')): return None
        vtf = values.get('$basetexture')
        try: width, height = vtf_size(materials.content.read('materials/'+vtf.replace('\\', '/').lower()+'.vtf'))
        except (KeyError, AttributeError): width, height = 64, 64
        base = sanitize(vtf or name)
        materials.textures.setdefault(base, (vtf, width, height, values))
        if kind: materials.kinds[base] = kind
        return materials.prefix+base
    materials.missing[candidates[0] if candidates else '?'] += 1
    return None


def prop_charts(positions, normals, uvs, triangles):
    """Split triangles into lightmap charts: connected faces sharing a dominant axis, projected along it."""
    a, b, c = (positions[triangles[:, k]] for k in range(3))
    face = np.cross(b-a, c-a)
    axis = np.abs(face).argmax(1); label = axis*2+(face[np.arange(len(face)), axis] < 0)
    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for tri, l in zip(triangles, label):
        roots = [find((v, l)) for v in tri]
        for r in roots[1:]: parent[r] = roots[0]
    charts = {}
    for tri, l in zip(triangles, label):
        charts.setdefault(find((tri[0], l)), []).append((tri, l))
    out = []
    for members in charts.values():
        index = {}; verts = []; tris = []
        drop = members[0][1]//2; keep = [k for k in range(3) if k != drop]
        for tri, _ in members:
            for v in tri:
                if v not in index:
                    index[v] = len(verts)
                    verts.append((positions[v], normals[v], uvs[v], positions[v][keep]/16))
            tris += [index[v] for v in tri]
        out.append((verts, tris))
    return out


def face_charts(bsp, model, offset, materials):
    """Render-only charts from a brush model's compiled faces.

    Non-solid entity brushes (func_illusionary) are not listed in the BSP's leaves,
    so their brushes cannot be recovered; their faces are the reliable source."""
    import struct as _struct
    lumps = bsp.lumps
    if not hasattr(bsp, '_face_cache'):
        points = np.frombuffer(lumps[VERTEXES], np.float32).reshape(-1, 3)
        edges = np.frombuffer(lumps[EDGES], np.uint16).reshape(-1, 2)
        surfedges = np.frombuffer(lumps[SURFEDGES], np.int32)
        faces = list(_struct.iter_unpack('<HBBihhhh4Bif2i2iiHHI', lumps[FACES]))
        bsp._face_cache = (points, edges, surfedges, faces)
    points, edges, surfedges, faces = bsp._face_cache
    first, count = bsp.models[model][10], bsp.models[model][11]
    charts = []
    for face in faces[first:first+count]:
        planenum, side, _, firstedge, numedges, texinfo, dispinfo = face[:7]
        if texinfo < 0 or dispinfo >= 0: continue
        material = materials.name(texinfo)
        if material[len(materials.prefix):].startswith('_'): continue  # nodraw, sky, invisible glass and water
        info = bsp.texinfo[texinfo]
        width, height = next((t[1], t[2]) for t in bsp.texdata if t[0] == info.material)
        normal = np.array(bsp.planes[planenum][0], float) * (-1 if side else 1)
        polygon = [points[edges[e][0]] if e >= 0 else points[edges[-e][1]] for e in surfedges[firstedge:firstedge+numedges]]
        polygon = [np.asarray(v, float)+offset for v in polygon]
        keep = [k for k in range(3) if k != int(np.abs(normal).argmax())]
        verts = []
        for v in polygon:
            u = (np.dot(v-offset, info.s[:3])+info.s[3])/width; t = (np.dot(v-offset, info.t[:3])+info.t[3])/height
            verts.append((v, normal, (u, t), v[keep]/16))
        # Source faces wind clockwise seen from the front, as Respawn front faces do.
        tris = [k for i in range(1, len(polygon)-1) for k in (0, i, i+1)]
        charts.append((material, verts, tris))
    return charts


def write_props(path, charts):
    """RSM1: per chart a material, vertices (xyz, normal, uv, colour, lightmap uv) and triangles."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('wb') as f:
        f.write(struct.pack('<4sI', b'RSM1', len(charts)))
        for material, verts, tris in charts:
            name = ('textures/'+material).encode('ascii')
            f.write(struct.pack('<I', len(name))+name+struct.pack('<2I', len(verts), len(tris)))
            for p, n, uv, lm in verts:
                f.write(struct.pack('<8f', *p, *n, *uv)+b'\xff\xff\xff\xff'+struct.pack('<2f', *lm))
            f.write(struct.pack(f'<{len(tris)}I', *tris))


def convert_props(bsp, materials, skybox_box):
    """Static props as render charts plus nodraw collision brushes from their physics hulls."""
    models = {}; charts = []; brushes = []; skipped = Counter()
    for name, origin_, angles, solid, skin in bsp.static_props():
        if skybox_box and all(skybox_box[0][k] <= origin_[k] <= skybox_box[1][k] for k in range(3)):
            skipped['3D skybox prop'] += 1; continue
        if name not in models:
            try: models[name] = Model(materials.content, name)
            except (KeyError, ValueError, struct.error) as error:
                models[name] = None; skipped['unreadable model'] += 1
        model = models[name]
        if model is None: continue
        rotation = angle_matrix(*angles); offset = np.array(origin_)
        positions = model.vertices[:, :3]@rotation.T+offset
        normals = model.vertices[:, 3:6]@rotation.T
        for material_index, triangles in model.meshes:
            material = prop_material(materials, model.material(material_index, skin))
            if material is None: skipped['cutout or translucent mesh'] += 1; continue
            # Source and Respawn both wind front faces clockwise (retail RSM recoveries agree).
            for verts, tris in prop_charts(positions, normals, model.vertices[:, 6:8], triangles):
                charts.append((material, verts, tris))
        if solid:
            for hull in model.hulls:
                faces = []
                for n, d in hull:
                    n = rotation@n; faces.append(valve_face(n, d+n@offset, materials.prefix+'_nodraw', (1, 0, 0, 0), (0, 1, 0, 0)))
                brushes.append('{\n'+'\n'.join(faces)+'\n}')
    return charts, brushes, skipped


def brush_text(bsp, brush, materials, offset=(0, 0, 0), clip=False, nonsolid=False):
    faces = []
    for side in brush.sides:
        if side.bevel: continue
        dist = side.dist+sum(n*o for n, o in zip(side.normal, offset))
        if clip: material = materials.prefix+'_clip'
        else: material = materials.name(side.texinfo)
        if nonsolid: material = materials.render_only(material)
        if side.texinfo >= 0:
            info = bsp.texinfo[side.texinfo]
            s = (*info.s[:3], info.s[3]-sum(a*o for a, o in zip(info.s, offset)))
            t = (*info.t[:3], info.t[3]-sum(a*o for a, o in zip(info.t, offset)))
        else:
            s, t = (1, 0, 0, 0), (0, 1, 0, 0)
        faces.append(valve_face(side.normal, dist, material, s, t))
    return '{\n'+'\n'.join(faces)+'\n}'


def displacement_patch(bsp, disp, materials):
    info = bsp.texinfo[disp.texinfo]
    width, height = next((t[1], t[2]) for t in bsp.texdata if t[0] == info.material)
    n = len(disp.rows); corners = disp.corners; lines = []
    # A patch faces along rows x columns; swap them where that points into the face.
    swap = np.dot(np.cross(np.subtract(corners[1], corners[0]), np.subtract(corners[3], corners[0])), disp.normal) < 0
    for i in range(n):
        points = []
        for j in range(n):
            y, x = (j, i) if swap else (i, j)
            # Texture coordinates come from the flat face, as in Source.
            a = [c0+(c1-c0)*y/(n-1) for c0, c1 in zip(corners[0], corners[1])]
            b = [c3+(c2-c3)*y/(n-1) for c3, c2 in zip(corners[3], corners[2])]
            base = [p+(q-p)*x/(n-1) for p, q in zip(a, b)]
            u = (sum(p*q for p, q in zip(info.s[:3], base))+info.s[3])/width
            v = (sum(p*q for p, q in zip(info.t[:3], base))+info.t[3])/height
            points.append('( %.3f %.3f %.3f %.6g %.6g )' % (*disp.rows[y][x], u, v))
        lines.append('( '+' '.join(points)+' )')
    return '{\npatchDef2\n{\n'+materials.name(disp.texinfo)+f'\n( {n} {n} 0 0 0 )\n(\n'+'\n'.join(lines)+'\n)\n}\n}'


def displacement_collision(disp, material, size=DISPLACEMENT_COLLISION):
    """A coarser nodraw copy of a displacement for collision: one collision piece per quad of the full grid overflows remap."""
    n = len(disp.rows); corners = disp.corners
    if n <= size: return None
    swap = np.dot(np.cross(np.subtract(corners[1], corners[0]), np.subtract(corners[3], corners[0])), disp.normal) < 0
    picks = [round(k*(n-1)/(size-1)) for k in range(size)]
    lines = []
    for i in picks:
        row = [disp.rows[j][i] if swap else disp.rows[i][j] for j in picks]
        lines.append('( '+' '.join('( %.3f %.3f %.3f 0 0 )' % tuple(p) for p in row)+' )')
    return '{\npatchDef2\n{\n'+material+f'\n( {size} {size} 0 0 0 )\n(\n'+'\n'.join(lines)+'\n)\n}\n}'


def origin(e):
    return tuple(map(float, e.get('origin', '0 0 0').split()))


def light_entities(bsp):
    text = ''; sun = None
    for e in bsp.entities:
        cls = e.get('classname')
        if cls == 'light_environment' and sun is None:
            sun = e
            text += entity(classname='light_environment', origin=e.get('origin', '0 0 0'), angles=e.get('angles', '0 0 0'),
                           pitch=e.get('pitch', '-45'), _light=e.get('_light', '255 255 255 200'),
                           _ambient=e.get('_ambient', '128 128 128 20'), lightEnvironmentIndex='*0', shadows='1')
        elif cls in ('light', 'light_spot'):
            brightness = float((e.get('_light', '255 255 255 200').split()+['200'])[3])
            # Source lights fall off with distance squared, normalised at 100 units.
            zero = float(e.get('_zero_percent_distance') or 0) or min(2048, max(256, 100*math.sqrt(brightness/2)))
            fifty = float(e.get('_fifty_percent_distance') or 0) or zero*.3
            keys = dict(classname=cls, origin=e['origin'], _light=e.get('_light', '255 255 255 200'), realtime='0',
                        _zero_percent_distance=f'{zero:g}', _fifty_percent_distance=f'{fifty:g}')
            if cls == 'light_spot':
                keys.update(angles=e.get('angles', '0 0 0'), pitch=e.get('pitch', '-90'), _cone=e.get('_cone', '45'),
                            _inner_cone=e.get('_inner_cone', '30'), _exponent=e.get('_exponent', '1'))
            text += entity(**keys)
    if sun is None:
        text += entity(classname='light_environment', origin='0 0 0', angles='-60 45 0', pitch='-60',
                       _light='255 250 240 300', _ambient='170 190 210 60', lightEnvironmentIndex='*0', shadows='1')
    return text


def menu_stage(prefix, z, floor):
    """A plain floor under its own small dome, for the menu Titan; the gameplay dome hides it."""
    brushes = [valve_box((-2064, -2064, z-96), (2064, 2064, z), prefix+floor, .5)]
    brushes += sky_dome(prefix+'_sky', prefix+'_sky_void', (0, 0), 2040, z, floor=False)
    return brushes


def build(args):
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    bsp = BSP(args.bsp)
    content = Content(args.game_dir, bsp.pakfile)
    prefix = ASSET_ROOT+args.name+'/'
    materials = Materials(bsp, content, prefix, args.material_templates)
    world = bsp.model_brushes(0)
    skybox = bsp.skybox_brushes(world); skybox_box = None
    if skybox:
        bounds = np.array([sum(bsp.brush_bounds(bsp.brushes[i]), []) for i in skybox])
        lo, hi = bounds[:, :3].min(0), bounds[:, 3:].max(0); skybox_box = (lo, hi)
        skybox = {i for i in world if all(lo[a] <= v for a, v in enumerate(bsp.brush_bounds(bsp.brushes[i])[0]))
                  and all(v <= hi[a] for a, v in enumerate(bsp.brush_bounds(bsp.brushes[i])[1]))}
    brushes = []; skipped = Counter(); boxes = []
    def add(index, offset=(0, 0, 0), render_only=False):
        brush = bsp.brushes[index]; clip = False
        if render_only: pass
        elif brush.contents & (CONTENTS_SOLID | CONTENTS_WINDOW | CONTENTS_GRATE): pass
        elif brush.contents & CONTENTS_PLAYERCLIP: clip = True
        elif brush.contents == 0:
            # Empty contents: visible but non-solid world brushes (Source's non-solid detail).
            render_only = True; skipped['non-solid world brush (render only)'] += 1
        else: skipped[f'contents {brush.contents:#x}'] += 1; return
        lo, hi = bsp.brush_bounds(brush)
        boxes.append([l+o for l, o in zip(lo, offset)]+[h+o for h, o in zip(hi, offset)])
        brushes.append(brush_text(bsp, brush, materials, offset, clip, render_only))
    for i in world:
        if i in skybox: skipped['3D skybox'] += 1
        else: add(i)
    render_only_charts = []
    for e in bsp.entities:
        model = e.get('model', '')
        if not model.startswith('*'): continue
        if e.get('classname') in STATIC_BRUSH_ENTITIES and e.get('angles', '0 0 0') in ('0 0 0', ''):
            for i in bsp.model_brushes(int(model[1:])): add(i, origin(e))
        elif e.get('classname') in RENDER_ONLY_ENTITIES and e.get('angles', '0 0 0') in ('0 0 0', ''):
            render_only_charts.extend(face_charts(bsp, int(model[1:]), np.array(origin(e)), materials))
        else: skipped[e.get('classname')] += 1
    charts, prop_brushes, prop_skipped = convert_props(bsp, materials, skybox_box) if args.props else ([], [], Counter())
    skipped.update(prop_skipped); brushes += prop_brushes; charts += render_only_charts
    patches = []; collision = []; contents_keys = []
    for d in bsp.displacements():
        coarse = displacement_collision(d, prefix+'_nodraw')
        if coarse:
            # Primitives are numbered brushes first, then patches, in map order.
            contents_keys.append(f'"_remap_contents_{len(brushes)+len(patches)}" "0"'); collision.append(coarse)
        patches.append(displacement_patch(bsp, d, materials))
    displacement_count = len(patches); patches += collision
    if charts: write_props(out/'assets/models/source_props.rsm', charts)
    boxes = np.array(boxes); lo = boxes[:, :3].min(0); hi = boxes[:, 3:].max(0)
    skyname = bsp.entities[0].get('skyname', 'sky_day01_01')
    faces = load_skybox(content, skyname)
    if faces:
        sky_image = source_sky_texture(faces)
        void = tuple(int(c*SKY_LEVEL) for c in faces['dn'][..., :3].reshape(-1, 3).mean(0))+(255,)
    else:
        sky_image = Image.new('RGBA', (64, 64), (150, 175, 205, 255)); void = (150, 175, 205, 255)
    middle = ((lo[0]+hi[0])/2, (lo[1]+hi[1])/2)
    if args.spawns:
        teams = {2: spread(nodes_or_all(bsp), args.spawns[:2]), 3: spread(nodes_or_all(bsp), args.spawns[2:])}
    else:
        teams = choose_spawns(bsp, middle)
    print(f'{args.name}: {len(brushes)} brushes, {displacement_count} displacements, {len(materials.textures)} textures; skipped {dict(skipped)}', flush=True)
    converted = ('''Brush geometry, displacements (as patches), static props with their physics
collision, textures, lights and the 2D skybox are converted. Dynamic and physics
props, cutout or translucent prop parts (foliage, wires), the 3D skybox, water,
doors, breakables, decals, overlays and normal maps are not.
''')
    metadata = {'brushes': len(brushes), 'displacements': displacement_count, 'textures': len(materials.textures),
                'skipped': dict(skipped), 'invisible_glass': sorted(materials.invisible), 'missing_materials': dict(materials.missing),
                'static_props': len(bsp.static_props()), 'prop_charts': len(charts), 'prop_collision_brushes': len(prop_brushes)}
    return assemble(args, out, materials, dict(brushes=brushes, patches=patches, keys=contents_keys, charts=charts),
                    lo, hi, sky_image, void, teams, light_entities(bsp), args.bsp, converted, metadata, teleports(bsp), pushes(bsp))


def assemble(args, out, materials, world, lo, hi, sky_image, void, teams, lights, source, converted, metadata, teleports=(), pushes=()):
    surf = getattr(args, 'surf', None)
    if surf is None: surf = Path(source).stem.lower().startswith('surf_')
    """Sky dome, menu stage, spawns and lights around converted world geometry; compile, validate and package the mod."""
    prefix = materials.prefix; brushes = world['brushes']
    centre = ((lo[0]+hi[0])/2, (lo[1]+hi[1])/2)
    radius = max(16000, math.hypot(hi[0]-lo[0], hi[1]-lo[1])/2+4000)
    sky_base = lo[2]-2000
    sky = sky_dome(prefix+'_sky', prefix+'_sky_void', centre, radius, sky_base, floor=False)
    sky.append(valve_box((centre[0]-radius, centre[1]-radius, sky_base-64), (centre[0]+radius, centre[1]+radius, sky_base), prefix+'_sky_void'))
    floor = (Counter(m for b in brushes for m in re.findall(r' (\S+) \[ [^\]]*\] \[ [^\]]*\]', b)
                     if not m.endswith(('_nodraw', '_clip', '_skyhole'))).most_common(1) or [(prefix+'_black', 0)])[0][0].removeprefix(prefix)
    menu_z = sky_base+radius+2000
    stage = menu_stage(prefix, menu_z, floor)
    middle = ((lo[0]+hi[0])/2, (lo[1]+hi[1])/2)
    pak = materials.build(out, args, sky_image, void)
    kill_z = args.kill_z if args.kill_z is not None else lo[2]-256
    text = lights
    text += entity(classname='mrvn_mp_menu', origin=f'0 0 {menu_z:g}', angles='0 -90 0', lightEnvironmentIndex='1')
    spawninfo = []
    for team, sites in teams.items():
        for p in sites:
            p = (p[0], p[1], p[2]+16)
            yaw = round(math.degrees(math.atan2(middle[1]-p[1], middle[0]-p[0])))
            spawninfo.append({'team': team, 'origin': p, 'yaw': yaw})
            for cls in ('info_spawnpoint_human', 'info_spawnpoint_human_start'):
                text += entity(classname=cls, origin=' '.join(f'{v:g}' for v in p), angles=f'0 {yaw} 0', teamnum=str(team))
    text += entity(classname='info_player_start', origin=' '.join(f'{v:g}' for v in spawninfo[0]['origin']))
    level = 'mp_source_'+args.name; path = out/(level+'.map')
    (out/'spawns.json').write_text(json.dumps(spawninfo, indent=2))
    def world_entity(cluster, luxel):
        return '\n'.join(['{', '"classname" "worldspawn"', '"_lightmapscale" "16"', f'"_remap_luxelsize" "{luxel:g}"',
                          '"_remap_lightmap_by_material" "1"', f'"_remap_lightmap_pagesize" "{LIGHTMAP_PAGE}"', '"_bouncescale" "0"',
                          '"_skyocclusion" "1"', '"_skysamples" "128"', '"_skyfixedpattern" "1"', f'"_meshcluster" "{cluster}"',
                          *(['"_remap_props" "models/source_props.rsm"'] if world['charts'] else []), *world['keys'], *brushes,
                          *world['patches'], *sky, *stage, '}'])+'\n'
    cluster = args.mesh_cluster; luxel = args.luxel_size
    while True:
        path.write_text(world_entity(cluster, luxel)+text)
        with (out/'compile.log').open('wb') as log:
            subprocess.run([str(args.remap.resolve()), '-game', 'titanfall2', '-fs_basepath', str(out), '-bsp', str(path)], stdout=log, stderr=subprocess.STDOUT, check=True)
        meshes = len(load_records(path.with_suffix('.bsp'), inspect(path.with_suffix('.bsp')))[80])
        pages = int(re.findall(r'(\d+) lightmap pages', (out/'compile.log').read_text(errors='ignore'))[-1])
        print(f'{meshes} world meshes at cluster size {cluster}, {pages} lightmap pages at {luxel:g} units per luxel', flush=True)
        if meshes <= MESH_BUDGET and pages <= MAX_LIGHTMAP_PAGES: break
        # Meshes split by material and lightmap page: coarser cells first, then fewer lightmap pages.
        if pages > MAX_LIGHTMAP_PAGES and luxel < MAX_LUXEL_SIZE: luxel = round(luxel*math.sqrt(pages/MAX_LIGHTMAP_PAGES)*1.1)
        elif cluster < MAX_MESH_CLUSTER: cluster *= 2
        elif luxel < MAX_LUXEL_SIZE: luxel *= 2
        else: raise ValueError(f'{meshes} meshes and {pages} lightmap pages exceed the budgets')
    report = validate(path.with_suffix('.bsp')); (out/'validation.json').write_text(json.dumps(report, indent=2))
    if report['issues']: raise ValueError(report['issues'])
    coverage = visibility_coverage(load_records(path.with_suffix('.bsp'), inspect(path.with_suffix('.bsp'))))
    (out/'visibility-coverage.json').write_text(json.dumps(coverage, indent=2))
    stbsp.write(out/(level+'.stbsp'), [(n, a['guid']) for a, n in pak.materials() if not n.endswith('_colpass') and not n.startswith('depth/')], lo[:2], hi[:2])
    modname = 'MRVN.Source'+args.name.title().replace('_', ''); mod = out/modname; maps = mod/'mod/maps'; maps.mkdir(parents=True)
    members = {}
    for part in ('env', 'fx', 'script', 'snd', 'spawn'):
        p = out/(level+'_'+part+'.ent')
        if not p.exists(): p.write_bytes(b'ENTITIES01\n\0')
    for p in out.glob(level+'*'):
        if p.suffix in ('.bsp', '.ent', '.stbsp'):
            shutil.copyfile(p, maps/p.name); members['maps/'+p.name] = p.read_bytes()
    pack_files(members, mod/'vpk', 'client_'+level+'.bsp.pak000')
    scripts = mod/'mod/scripts/vscripts/mp/levels'; scripts.mkdir(parents=True)
    # Teleport triggers (jump maps' resets and course doors) are checked by script: no trigger brushes are compiled.
    # "<-" is Squirrel's slot operator, so vector literals open with a space.
    adds = ''.join(f' AddTeleport( < {lo[0]:g}, {lo[1]:g}, {lo[2]:g} >, < {hi[0]:g}, {hi[1]:g}, {hi[2]:g} >, < {d[0]:g}, {d[1]:g}, {d[2]:g} >, {yaw:g}, {n} )\n'
                   for lo, hi, d, yaw, n in teleports)
    adds += ''.join(f' AddPush( < {lo[0]:g}, {lo[1]:g}, {lo[2]:g} >, < {hi[0]:g}, {hi[1]:g}, {hi[2]:g} >, < {v[0]:.4g}, {v[1]:.4g}, {v[2]:.4g} > )\n'
                    for lo, hi, v in pushes)
    (scripts/(level+'.nut')).write_text('''global function CodeCallback_MapInit
struct
{
 array<vector> mins
 array<vector> maxs
 array<vector> destinations
 array<float> yaws
 array<int> choices
 array<vector> pushMins
 array<vector> pushMaxs
 array<vector> pushVelocities
 table<entity, float> rampTimes
} file
void function CodeCallback_MapInit()
{
 ClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )
 ClassicMP_ForceDisableEpilogue( true )
 Riff_ForceTitanAvailability( eTitanAvailability.Never )
TELEPORTS thread KillFallenPilots()
SURF
}
void function AddTeleport( vector mins, vector maxs, vector destination, float yaw, int choices )
{
 // Players touch a trigger when their hull overlaps it; origins are at the feet.
 file.mins.append( mins - <16, 16, 72> )
 file.maxs.append( maxs + <16, 16, 0> )
 file.destinations.append( destination )
 file.yaws.append( yaw )
 // The first of `choices` consecutive entries with this box; one is picked at random.
 file.choices.append( choices )
}
void function AddPush( vector mins, vector maxs, vector velocity )
{
 file.pushMins.append( mins - <16, 16, 72> )
 file.pushMaxs.append( maxs + <16, 16, 0> )
 file.pushVelocities.append( velocity )
}
// trigger_push: while inside, the player moves at least the push speed along its direction.
void function ApplyPushes( entity player, vector o )
{
 for ( int i = 0; i < file.pushMins.len(); i++ )
 {
  vector lo = file.pushMins[i]
  vector hi = file.pushMaxs[i]
  if ( o.x < lo.x || o.y < lo.y || o.z < lo.z || o.x > hi.x || o.y > hi.y || o.z > hi.z )
   continue
  vector push = file.pushVelocities[i]
  float speed = Length( push )
  vector dir = push / speed
  vector v = player.GetVelocity()
  float along = DotProduct( v, dir )
  if ( along < speed )
   player.SetVelocity( v + dir * ( speed - along ) )
 }
}
void function KillFallenPilots()
{
 while ( true )
 {
  foreach ( entity player in GetPlayerArray() )
  {
   if ( !IsAlive( player ) )
    continue
   vector o = player.GetOrigin()
   if ( o.z < KILL_Z )
   {
    player.TakeDamage( 10000, null, null, { damageSourceId = eDamageSourceId.fall } )
    continue
   }
   ApplyPushes( player, o )
   for ( int i = 0; i < file.mins.len(); i++ )
   {
    vector lo = file.mins[i]
    vector hi = file.maxs[i]
    if ( o.x < lo.x || o.y < lo.y || o.z < lo.z || o.x > hi.x || o.y > hi.y || o.z > hi.z )
     continue
    int k = i + RandomInt( file.choices[i] )
    player.SetOrigin( file.destinations[k] )
    player.SetAngles( <0, file.yaws[k], 0> )
    player.SetVelocity( <0, 0, 0> )
    break
   }
  }
  wait 0.05
 }
}
'''.replace('KILL_Z', f'{kill_z:.1f}').replace('TELEPORTS', adds).replace('SURF', ' thread SurfRamps()' if surf else '')
      + (SURF_SCRIPT if surf else ''))
    paks = mod/'paks'; paks.mkdir(); pakname = 'source_'+args.name+'.rpak'
    # Installed as <level>_patch.rpak, which the engine requests right after the level's pak, so it loads and unloads with the level. A Postload pak is never unloaded, but Coliseum, whose shader sets its materials use, is reloaded on every map change; the stale references crashed materialsystem_dx11 on the next map.
    shutil.copyfile(out/'pak-build'/pakname, paks/(level+'_patch.rpak'))
    (paks/'rpak.json').write_text(json.dumps({'Aliases': {level+'.rpak': 'mp_coliseum.rpak', level+'_loadscreen.rpak': 'mp_coliseum_loadscreen.rpak'}}, indent=2))
    display = args.display_name or args.name
    resource = mod/'mod/resource'; resource.mkdir(parents=True)
    tokens = {level: display, level+'_ALLCAPS': display.upper(), level+'_CLASSIC': display,
              level+'_CLASSIC_DESC': 'Port of '+source.stem, level+'_DESC': 'Port of '+source.stem}
    body = ''.join(f'\t\t"{k}" "{v}"\n' for k, v in tokens.items())
    (resource/(level+'_english.txt')).write_bytes(b'\xff\xfe'+('"lang"\n{\n\t"Language" "english"\n\t"Tokens"\n\t{\n'+body+'\t}\n}\n').encode('utf-16-le'))
    (mod/'mod.json').write_text(json.dumps({'Name': modname, 'Version': VERSION, 'LoadPriority': 200, 'RequiredOnClient': True,
        'Description': display+'. Local test port of a Source engine map', 'Localisation': ['resource/'+level+'_%language%.txt'],
        'Scripts': [{'Path': 'mp/levels/'+level+'.nut', 'RunOn': 'SERVER && MP && MAP_'+level}]}, indent=2))
    readme = f'''# {display}: Source engine to Titanfall 2 test port

Source map: {source.name}. Original game assets belong to their owners (Valve).
Local conversion by MRVN-Radiant, for local testing only: no redistribution licence is granted.

Extract {modname} into R2Northstar/mods and run `map {level} tdm`.

{converted}'''
    (mod/'README.md').write_text(readme); (out/'README.md').write_text(readme)
    metadata = {'level': level, 'source': str(source), 'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), **metadata,
                'world_meshes': meshes, 'mesh_cluster': cluster, 'luxel_size': luxel, 'lightmap_pages': pages, 'teleports': len(teleports), 'pushes': len(pushes), 'surf': surf, 'kill_z': kill_z, 'engine_verified': False}
    (out/'conversion.json').write_text(json.dumps(metadata, indent=2))
    with zipfile.ZipFile(out/(modname+'-'+VERSION+'.zip'), 'x', zipfile.ZIP_DEFLATED) as z:
        for p in sorted(mod.rglob('*')):
            if p.is_file(): z.write(p, p.relative_to(out))
    return metadata


SURF_SCRIPT = '''
// Surf ramps. Standing, Titanfall counts a slope as ground well past Source's 45.6 degree
// walkable limit: ground movement stops a pilot sliding along a 52 degree ramp within half a
// second. Crouched, the same ramp is not ground (tested in Northstar): the pilot keeps their
// speed along it and slides down it as in Source. So on anything steeper than Source's limit
// pilots are crouched, with no ground friction, until a quarter second after leaving it.
void function SurfRamps()
{
 while ( true )
 {
  foreach ( entity player in GetPlayerArray() )
  {
   bool surfing = player in file.rampTimes
   if ( !IsAlive( player ) )
   {
    if ( surfing )
     StopSurfing( player )
    continue
   }
   vector o = player.GetOrigin()
   // A line from the feet: on a 52 degree ramp the surface under the centre is up to 21 units below them.
   TraceResults r = TraceLine( o + <0, 0, 4>, o - <0, 0, 40>, player, TRACE_MASK_SOLID, TRACE_COLLISION_GROUP_NONE )
   if ( r.fraction < 1.0 && r.surfaceNormal.z > 0.05 && r.surfaceNormal.z < 0.7 )
   {
    if ( !surfing )
    {
     player.ForceCrouch()
     player.SetGroundFrictionScale( 0.0 )
    }
    file.rampTimes[player] <- Time()
   }
   else if ( surfing && Time() - file.rampTimes[player] > 0.25 )
    StopSurfing( player )
  }
  WaitFrame()
 }
}
void function StopSurfing( entity player )
{
 delete file.rampTimes[player]
 player.UnforceCrouch()
 player.SetGroundFrictionScale( 1.0 )
}
'''


def teleports(bsp):
    """(mins, maxs, destination, yaw) for each trigger_teleport with a destination; rotated or filtered ones too."""
    targets = {e.get('targetname'): e for e in bsp.entities if e.get('targetname')}
    # Destinations a logic_case sets with "<trigger>,AddOutput,target <name>" (surf_utopia's jail
    # picks a random cell this way); the trigger's own target is then a placeholder.
    chosen = {}
    for e in bsp.entities:
        for key, value in e.items():
            if not key.startswith('OnCase'): continue
            m = re.match(r'([^,\x1b]+)[,\x1b]AddOutput[,\x1b]target (\S+?)[,\x1b]', value)
            if m and m[2] in targets: chosen.setdefault(m[1], []).append(targets[m[2]])
    out = []
    for e in bsp.entities:
        if e.get('classname') != 'trigger_teleport' or not e.get('model', '').startswith('*'): continue
        dests = chosen.get(e.get('targetname'), [])
        if not dests and e.get('target') in targets: dests = [targets[e['target']]]
        model = bsp.models[int(e['model'][1:])]; offset = np.array(origin(e))
        # Consecutive entries with the same box are alternatives; the level script picks one at random.
        for dest in dests:
            yaw = float((dest.get('angles', '0 0 0').split()+['0', '0'])[1])
            out.append((np.array(model[0:3])+offset, np.array(model[3:6])+offset, origin(dest), yaw, len(dests)))
    return out


def pushes(bsp):
    """(mins, maxs, velocity) for each player trigger_push (spawnflags 1) that starts enabled."""
    out = []
    for e in bsp.entities:
        if e.get('classname') != 'trigger_push' or not e.get('model', '').startswith('*'): continue
        if not int(e.get('spawnflags', '0')) & 1 or e.get('StartDisabled') == '1' or float(e.get('speed', '0')) <= 0: continue
        model = bsp.models[int(e['model'][1:])]; offset = np.array(origin(e))
        pitch, yaw = (float(v) for v in (e.get('pushdir', '0 0 0').split()+['0', '0'])[:2])
        p, y = math.radians(pitch), math.radians(yaw)
        # Source angles: positive pitch looks down.
        direction = np.array((math.cos(p)*math.cos(y), math.cos(p)*math.sin(y), -math.sin(p)))
        out.append((np.array(model[0:3])+offset, np.array(model[3:6])+offset, direction*float(e['speed'])))
    return out


def nodes_or_all(bsp):
    return [origin(e) for e in bsp.entities if e.get('classname') in NODE_CLASSES | {'info_player_start', 'info_player_teamspawn'}]


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bsp', type=Path, required=True)
    p.add_argument('--game-dir', type=Path, action='append', required=True,
                   help='Game content folder holding *_dir.vpk files, e.g. .../Half-Life 2/hl2; repeat for more')
    p.add_argument('--name', required=True, type=lambda v: v if v.replace('_', '').isalnum() and v.islower() else p.error('--name must be lowercase letters, digits and _'),
                   help='Map becomes mp_source_NAME')
    for name in ('output', 'remap', 'repak', 'material-template'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--material-templates', type=Path, help='Directory from extract_material_templates.py: translucent and alpha-tested materials draw as such')
    p.add_argument('--display-name')
    p.add_argument('--spawns', type=float, nargs=4, metavar=('X1', 'Y1', 'X2', 'Y2'), help='Centre of each team\'s spawn area, Source units')
    p.add_argument('--kill-z', type=float)
    p.add_argument('--mesh-cluster', type=int, default=MESH_CLUSTER)
    p.add_argument('--luxel-size', type=float, default=LUXEL_SIZE, help='World units per lightmap texel to start from')
    p.add_argument('--surf', action=argparse.BooleanOptionalAction, default=None,
                   help='No ground friction on slopes steeper than Source allows standing on, so surf ramps work (default: on for surf_ maps)')
    p.add_argument('--no-props', dest='props', action='store_false', help='Leave static props out')
    print(json.dumps(build(p.parse_args()), indent=2))
