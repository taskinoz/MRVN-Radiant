"""Port a Source 2 map (Counter-Strike 2) to a Titanfall 2 Northstar mod.

Source2Viewer-CLI exports the compiled world's render meshes and textures to
glTF and dumps its physics and entity lumps as KeyValues3 text. Render meshes
become remap RSM1 meshes (`_remap_props`); physics hulls become nodraw brushes
and physics triangle meshes become collision patches. Compilation and packaging
are shared with the Source 1 converter.
"""
import argparse
from collections import Counter
from pathlib import Path
import subprocess

import numpy as np
from PIL import Image

from build_source_ports import (ASSET_ROOT, LUXEL_SIZE, MESH_CLUSTER, Materials, assemble, prop_charts, sanitize, spread, valve_face,
                                write_props)
from compiler_regression import entity
from source2_engine import GLTF, Physics, entities

INCHES_PER_METRE = 1/0.0254
# Render triangles kept after simplification; the Titanfall 2 world index budget is about 1M triangles.
TRIANGLE_BUDGET = 950_000
# Vertex snapping grid sizes tried in order, in Source units.
GRID_CELLS = (1, 2, 3, 4, 5, 6, 8, 12, 16)
# Collision triangles share 16-bit collision index ranges with brushes, so world collision meshes are welded coarser.
COLLISION_WELD = 6
SKIP_MATERIALS = ('tools', 'wires', 'skybox', 'caustics', 'decal', 'overlay', 'nodraw', 'blocklight')
# Collision attribute interactions: solid for players, player clip, or neither (bullets, grenades, sound, sky).
SOLID_INTERACTIONS = {'', 'passbullets', 'window', 'solid'}
CLIP_INTERACTIONS = {'playerclip', 'npcclip', 'ladder'}


def gltf_to_source(points):
    """Source2Viewer exports Source (x, y, z) inches as glTF (y, z, x) metres."""
    return points[:, [2, 0, 1]]*INCHES_PER_METRE


def export(args):
    """Run Source2Viewer-CLI once into args.export: world glTF with textures, physics and entity dumps."""
    out = args.export; out.mkdir(parents=True, exist_ok=True)
    level = args.vpk.stem; game = ['--game', str(args.gameinfo)] if args.gameinfo else []
    def dump(path, block, name):
        if (out/name).exists(): return
        text = subprocess.run([str(args.vrf), '-i', str(args.vpk), '--vpk_filepath', path, '-b', block], capture_output=True, text=True,
                              encoding='utf-8', errors='replace').stdout
        (out/name).write_text(text, encoding='utf-8')
    if not (out/'world.gltf').exists():
        subprocess.run([str(args.vrf), '-i', str(args.vpk), '--vpk_filepath', f'maps/{level}/world.vwrld_c', '-o', str(out/'world'), '-d',
                        *game, '--gltf_export_format', 'gltf', '--gltf_export_materials'], check=True, stdout=subprocess.DEVNULL)
    dump(f'maps/{level}/world_physics.vmdl_c', 'PHYS', 'physics.kv3')
    dump(f'maps/{level}/entities/default_ents.vents_c', 'DATA', 'entities.txt')


class SceneMaterials(Materials):
    """glTF materials to Titanfall 2 ones, keyed by material name."""

    def __init__(self, gltf, prefix):
        super().__init__(None, None, prefix); self.gltf = gltf; self.names = {}

    def name(self, index):
        if index not in self.names:
            name, image, alpha, factor = self.gltf.material(index)
            if alpha != 'OPAQUE': self.names[index] = None  # Cutout and blended surfaces: no template for them yet.
            elif any(s in name.lower() for s in SKIP_MATERIALS): self.names[index] = None
            else:
                base = sanitize(name)
                size = Image.open(image).size if image and image.exists() else (64, 64)
                if image is None or not image.exists(): self.missing[name] += 1
                values = {'tint': list(factor[:3])+[1]} if any(abs(f-1) > .01 for f in factor[:3]) else {}
                self.textures.setdefault(base, (image, size[0], size[1], values))
                self.names[index] = self.prefix+base
        return self.names[index]


def render_charts(gltf, materials, budget=TRIANGLE_BUDGET):
    """Opaque render triangles in Source units, simplified to the budget by snapping vertices to a grid.

    Each kept triangle keeps its own corners' texture coordinates and normals, so
    texture seams survive; only positions move, by at most one grid cell.
    """
    parts = []; skipped = Counter()
    for mesh, matrix in gltf.instances():
        for material_index, positions, normals, uvs, triangles in gltf.primitives(mesh):
            material = materials.name(material_index) if material_index is not None else None
            if material is None: skipped['cutout, translucent or tool triangles'] += len(triangles); continue
            p = gltf_to_source(positions@matrix[:3, :3].T+matrix[:3, 3])
            n = normals@matrix[:3, :3].T; n = n[:, [2, 0, 1]]
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            # Respawn front faces wind clockwise: cross(b-a, c-a) points against the normal. Flip the rest.
            a, b, c = (p[triangles[:, k]] for k in range(3))
            if np.einsum('ij,ij->', np.cross(b-a, c-a), n[triangles[:, 0]]) > 0: triangles = triangles[:, ::-1]
            parts.append((material, p, n, uvs, triangles))
    points = np.concatenate([part[1] for part in parts]); first = np.cumsum([0]+[len(part[1]) for part in parts])
    total = sum(len(part[4]) for part in parts)
    for cell in GRID_CELLS:
        _, cluster = np.unique(np.floor(points/cell).astype(np.int64), axis=0, return_inverse=True); cluster = cluster.reshape(-1)
        kept = 0
        for (material, p, n, uvs, triangles), start in zip(parts, first):
            t = cluster[triangles+start]
            kept += int(((t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])).sum())
        if kept <= budget: break
    # Snap to each cell's mean position, so flat surfaces stay flat.
    counts = np.bincount(cluster); mean = np.stack([np.bincount(cluster, points[:, k])/counts for k in range(3)], 1)
    charts = []; lo = np.full(3, np.inf); hi = -lo
    for (material, p, n, uvs, triangles), start in zip(parts, first):
        t = cluster[triangles+start]
        keep = (t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])
        _, unique = np.unique(np.sort(t[keep], 1), axis=0, return_index=True)
        kept = triangles[keep][np.sort(unique)]
        skipped['simplified away'] += len(triangles)-len(kept)
        if not len(kept): continue
        snapped = mean[cluster[start:start+len(p)]]
        used = np.unique(kept); lo = np.minimum(lo, snapped[used].min(0)); hi = np.maximum(hi, snapped[used].max(0))
        for verts, tris in prop_charts(snapped, n, uvs, kept):
            charts.append((material, verts, tris))
    return charts, lo, hi, cell, skipped


def quad_patches(vertices, triangles, material, weld):
    """Collision patches for a triangle mesh: welded coarser, adjacent triangles paired into one quad patch."""
    key = np.round(vertices/weld).astype(np.int64)
    _, rep, inv = np.unique(key, axis=0, return_index=True, return_inverse=True); inv = inv.reshape(-1)
    points = vertices[rep]; t = inv[triangles]
    t = t[(t[:, 0] != t[:, 1]) & (t[:, 1] != t[:, 2]) & (t[:, 0] != t[:, 2])]
    t = t[np.unique(np.sort(t, 1), axis=0, return_index=True)[1]]
    edges = {}
    for i, (a, b, c) in enumerate(t):
        for u, v, w in ((a, b, c), (b, c, a), (c, a, b)): edges.setdefault((v, u), []).append((i, w))
    used = np.zeros(len(t), bool); patches = []
    def text(rows):
        return '{\npatchDef2\n{\n'+material+'\n( 2 2 0 0 0 )\n(\n'+'\n'.join(
            '( '+' '.join('( %.3f %.3f %.3f 0 0 )' % tuple(points[v]) for v in row)+' )' for row in rows)+'\n)\n}\n}'
    for i, (a, b, c) in enumerate(t):
        if used[i]: continue
        used[i] = True; partner = None
        for u, v, w in ((a, b, c), (b, c, a), (c, a, b)):
            # A neighbour across edge u-v, wound the same way, is (v, u, x); quad u, x, v, w keeps the shared diagonal.
            for j, x in edges.get((u, v), []):
                if not used[j]: partner = (u, x, v, w); used[j] = True; break
            if partner: break
        # Patch columns: ( v0 v2 ) ( v1 v3 ) gives remap triangles (v0 v2 v3) and (v0 v3 v1).
        if partner:
            q0, q1, q2, q3 = partner; patches.append(text(((q0, q1), (q3, q2))))
        else:
            patches.append(text(((a, b), (c, c))))
    return patches


def collision(physics, prefix):
    """Brushes from convex hulls and patches from triangle meshes, for player-solid and player-clip attributes."""
    def kind(index):
        attribute = physics.attributes[index] if index < len(physics.attributes) else {}
        interacts = {str(s).lower() for s in attribute.get('m_InteractAsStrings', [])} or {''}
        if interacts & CLIP_INTERACTIONS: return prefix+'_clip'
        if interacts <= SOLID_INTERACTIONS: return prefix+'_nodraw'
        return None
    brushes = []; patches = []; skipped = Counter()
    for index, planes in physics.hulls:
        material = kind(index)
        if material is None: skipped['non-player hulls'] += 1; continue
        brushes.append('{\n'+'\n'.join(valve_face(p[:3], p[3], material, (1, 0, 0, 0), (0, 1, 0, 0)) for p in planes)+'\n}')
    for index, vertices, triangles in physics.meshes:
        material = kind(index)
        if material is None: skipped['non-player mesh triangles'] += len(triangles); continue
        patches += quad_patches(vertices, triangles, material, COLLISION_WELD)
    return brushes, patches, skipped


def lights(ents):
    text = ''; sun = next((e for e in ents if e.get('classname') == 'light_environment'), None)
    if sun:
        pitch, yaw = sun['angles'][0], sun['angles'][1]
        r, g, b = sun.get('color', [255, 255, 255]); sky = sun.get('skycolor', [128, 150, 180])
        text += entity(classname='light_environment', origin='0 0 0', angles=f'0 {yaw:g} 0', pitch=f'{-pitch:g}',
                       _light=f'{r} {g} {b} {min(600, 150*float(sun.get("brightness", 2))):.0f}',
                       _ambient=f'{sky[0]} {sky[1]} {sky[2]} {min(120, 25*float(sun.get("skyintensity", 1))):.0f}',
                       lightEnvironmentIndex='*0', shadows='1')
    else:
        text += entity(classname='light_environment', origin='0 0 0', angles='0 45 0', pitch='-60', _light='255 250 240 300',
                       _ambient='170 190 210 60', lightEnvironmentIndex='*0', shadows='1')
    for e in ents:
        if e.get('classname') not in ('light_omni', 'light_omni2', 'light_spot', 'light_barn', 'light_rect') or not e.get('enabled', True): continue
        if str(e.get('directlight', '1')) == '0': continue
        r, g, b = (e.get('color') or [255, 255, 255])[:3]
        brightness = float(e.get('brightness_legacy') or e.get('brightness') or 1)
        zero = min(2048, max(128, float(e.get('range') or 512)))
        text += entity(classname='light', origin=' '.join(f'{v:g}' for v in e['origin']), realtime='0',
                       _light=f'{r} {g} {b} {min(600, max(20, 30*brightness)):.0f}',
                       _zero_percent_distance=f'{zero:g}', _fifty_percent_distance=f'{zero*.3:g}')
    return text


def build(args):
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    export(args)
    gltf = GLTF(args.export/'world.gltf')
    prefix = ASSET_ROOT+args.name+'/'
    materials = SceneMaterials(gltf, prefix)
    charts, lo, hi, cell, skipped = render_charts(gltf, materials, args.triangle_budget)
    print(f'{args.name}: {sum(len(c[2])//3 for c in charts)} render triangles in {len(charts)} charts, '
          f'vertices snapped to a {cell}-unit grid', flush=True)
    write_props(out/'assets/models/source_props.rsm', charts)
    physics = Physics((args.export/'physics.kv3').read_text(encoding='utf-8'))
    brushes, patches, collision_skipped = collision(physics, prefix); skipped.update(collision_skipped)
    if args.collision != 'all': patches = []
    if args.collision == 'none': brushes = []
    print(f'{len(brushes)} collision hulls, {len(patches)} collision patches; skipped {dict(skipped)}', flush=True)
    ents = entities((args.export/'entities.txt').read_text(encoding='utf-8'))
    teams = {}
    for team, cls in ((2, 'info_player_terrorist'), (3, 'info_player_counterterrorist')):
        sites = [tuple(e['origin']) for e in ents if e.get('classname') == cls]
        teams[team] = spread(sites, sites[0])
    sun = next((e for e in ents if e.get('classname') == 'light_environment'), {})
    sky = tuple(sun.get('skycolor', [120, 160, 210]))
    sky_image = Image.new('RGBA', (64, 64), sky+(255,)); void = tuple(int(c*.8) for c in sky)+(255,)
    converted = ('''Render meshes, textures (base colour only), physics collision, lights and spawns are
converted. Render meshes are simplified by snapping vertices to a grid. Cutout and
translucent materials (glass, decals), wires, the 3D skybox, doors, physics props
and normal maps are not.
''')
    metadata = {'render_triangles': sum(len(c[2])//3 for c in charts), 'render_charts': len(charts),
                'snap_grid': cell, 'textures': len(materials.textures),
                'collision_hulls': len(brushes), 'collision_patches': len(patches),
                'skipped': {k: int(v) for k, v in skipped.items()}, 'missing_materials': dict(materials.missing)}
    return assemble(args, out, materials, dict(brushes=brushes, patches=patches, keys=[], charts=charts),
                    lo, hi, sky_image, void, teams, lights(ents), args.vpk, converted, metadata)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--vpk', type=Path, required=True, help='Map package, e.g. .../game/csgo/maps/de_nuke.vpk')
    p.add_argument('--vrf', type=Path, required=True, help='Source2Viewer-CLI.exe')
    p.add_argument('--gameinfo', type=Path, help='gameinfo.gi, so shared materials and textures resolve')
    p.add_argument('--export', type=Path, required=True, help='Folder for the Source2Viewer export; reused when present')
    p.add_argument('--name', required=True, type=lambda v: v if v.replace('_', '').isalnum() and v.islower() else p.error('--name must be lowercase letters, digits and _'),
                   help='Map becomes mp_source_NAME')
    for name in ('output', 'remap', 'repak', 'material-template'): p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--display-name')
    p.add_argument('--kill-z', type=float)
    p.add_argument('--triangle-budget', type=int, default=TRIANGLE_BUDGET, help='Render triangles to simplify to')
    p.add_argument('--collision', choices=('all', 'hulls', 'none'), default='all', help='Physics collision to convert')
    p.add_argument('--mesh-cluster', type=int, default=MESH_CLUSTER)
    p.add_argument('--luxel-size', type=float, default=LUXEL_SIZE, help='World units per lightmap texel to start from')
    import json
    print(json.dumps(build(p.parse_args()), indent=2))
