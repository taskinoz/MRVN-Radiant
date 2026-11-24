#!/usr/bin/env python3
"""Recompile Titanfall 1 static-prop models (MDL v52) as Titanfall 2 models (MDL v53).

Each model's LOD 0 meshes, skin families and PHY convex pieces are written as SMD + QC
and compiled with r2studiomdl (taskinoz/r2-model-compiler). Material names and search
directories are kept, so the model looks up the same materials as in Titanfall 1.

  python tf1_models.py --assets ASSETS --compiler r2studiomdl.exe --output MOD/mod \\
      models/rocks/rock_01.mdl [...]

ASSETS holds the extracted TF1 files (models/*.mdl, .vvd, .dx11.vtx, .phy).
Copyright (c) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import json
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_engine import Content, Model  # noqa: E402

IVP_TO_UNITS = 39.3701  # IVP metres to inches


def load_dmx_writer():
    """r2-model-compiler's tools/decompile53.py (write_dmx), found next to the compiler or via R2C_TOOLS."""
    import importlib.util, os
    for root in filter(None, (os.environ.get('R2C_TOOLS'),)):
        path = Path(root) / 'decompile53.py'
        if path.exists():
            sys.path.insert(0, str(path.parent))
            spec = importlib.util.spec_from_file_location('decompile53', path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    return None


DMX = None


class TF1Content(Content):
    """Loose TF1 files; Titanfall 1 ships DirectX 11 VTX files instead of dx90."""

    def read(self, name):
        name = name.replace('\\', '/').lower()
        if name.endswith('.dx90.vtx'):
            name = name[:-len('.dx90.vtx')] + '.dx11.vtx'
        return super().read(name)


def phy_pieces(data):
    """Convex pieces of every PHY solid, as (points, triangles) in model space."""
    header, _, solids, _ = struct.unpack_from('<4i', data)
    p = header
    pieces = []
    for _ in range(solids):
        size, = struct.unpack_from('<i', data, p)
        start = p + 4
        p = start + size
        surface = start + 28 if data[start:start + 4] == b'VPHY' else start
        root, = struct.unpack_from('<i', data, surface + 32)
        end = surface + (struct.unpack_from('<I', data, surface + 28)[0] >> 8)
        for node in range(surface + root, min(end, p) - 27, 28):
            right, ledge_offset = struct.unpack_from('<ii', data, node)
            if right:
                continue  # internal node: its ledge is the hull of its whole subtree
            ledge = node + ledge_offset
            points_offset, _, _, tri_count = struct.unpack_from('<iiih', data, ledge)
            tris = [[e & 0xFFFF for e in struct.unpack_from('<3I', data, ledge + 20 + 16 * t)][:3]
                    for t in range(tri_count)]
            if not tris:
                continue
            used = sorted({i for t in tris for i in t})
            remap = {i: k for k, i in enumerate(used)}
            pts = []
            for i in used:
                x, y, z = struct.unpack_from('<3f', data, ledge + points_offset + 16 * i)
                pts.append((x * IVP_TO_UNITS, z * IVP_TO_UNITS, -y * IVP_TO_UNITS))
            pts = np.array(pts)
            centre = pts.mean(0)
            out = []
            for a, b, c in ((remap[a], remap[b], remap[c]) for a, b, c in tris):
                n = np.cross(pts[b] - pts[a], pts[c] - pts[a])
                if np.linalg.norm(n) < 1e-9:
                    continue
                # Outward winding, as studiomdl expects for collision meshes.
                out.append((a, b, c) if n @ (pts[a] - centre) >= 0 else (a, c, b))
            if len(out) >= 4:
                pieces.append((pts, out))
    return pieces


def vvc_colours(vvc, vvd):
    """LOD 0 vertex colours (RGBA 0-1) in Model.vertices order, from a VVC beside the VVD."""
    if vvc[:4] != b'IDCV':
        raise ValueError('not a VVC')
    colour_start, = struct.unpack_from('<i', vvc, 48)
    lod0, = struct.unpack_from('<i', vvd, 16)
    fixups, fixup_start = struct.unpack_from('<2i', vvd, 48)
    total = (len(vvc) - colour_start) // 4

    def rows(first, count):
        return np.frombuffer(vvc, np.uint8, count * 4, colour_start + 4 * first).reshape(-1, 4) / 255.0
    if not fixups:
        return rows(0, min(lod0, total))
    return np.concatenate([rows(source, count) for lod, source, count in
                           (struct.unpack_from('<3i', vvd, fixup_start + 12 * k) for k in range(fixups)) if lod >= 0])


def write_dmx_body(model, path):
    """The render mesh as keyvalues2 DMX with vertex colours (color$0), via r2-model-compiler's writer."""
    v, colours = model.vertices, model.colours
    faces = []
    for material, tris in model.meshes:
        texture = model.textures[material] if material < len(model.textures) else model.textures[0]
        for tri in tris:
            corners = [(tuple(float(x) for x in v[i, 0:3]), tuple(float(x) for x in v[i, 3:6]), [(0, 1.0)],
                        {'uv': (float(v[i, 6]), 1.0 - float(v[i, 7])), 'color': tuple(float(c) for c in colours[i])})
                       for i in (tri[0], tri[2], tri[1])]
            faces.append((texture, 0, corners))
    DMX.write_dmx(str(path), [{'name': 'root', 'parent': -1}], [((0, 0, 0), (0, 0, 0))], faces)


def smd(rows):
    return 'version 1\nnodes\n0 "root" -1\nend\nskeleton\ntime 0\n0 0 0 0 0 0 0\nend\ntriangles\n' + ''.join(rows) + 'end\n'


def vertex(p, n, uv):
    return (f'0 {p[0]:.6f} {p[1]:.6f} {p[2]:.6f} {n[0]:.6f} {n[1]:.6f} {n[2]:.6f} '
            f'{uv[0]:.6f} {1.0 - uv[1]:.6f} 1 0 1\n')


def write_sources(model, name, folder, prefix='', physics=False):
    """Write <stem>_ref.smd, <stem>_phys.smd and <stem>.qc; returns the QC path."""
    stem = Path(name).stem
    v = model.vertices
    rows = []
    for material, tris in model.meshes:
        texture = model.textures[material] if material < len(model.textures) else model.textures[0]
        for tri in tris:
            rows.append(texture + '\n')
            # Source VTX winding is clockwise; SMD triangles are counter-clockwise.
            for i in (tri[0], tri[2], tri[1]):
                rows.append(vertex(v[i, 0:3], v[i, 3:6], v[i, 6:8]))
    if not rows:
        raise ValueError(f'{name}: no LOD 0 triangles')
    body = f'{stem}_ref.smd'
    (folder / body).write_text(smd(rows))
    if getattr(model, 'colours', None) is not None and DMX is not None:
        # Vertex colours (blends, fades on light shafts and waterfalls) need DMX; SMD has no field.
        body = f'{stem}_ref.dmx'
        write_dmx_body(model, folder / body)
    qc = [f'$modelname "{name.removeprefix("models/")}"',
          # A prefix keeps the port's materials apart from same-named ones in loaded game paks.
          '$cdmaterials ' + ' '.join(f'"{prefix}{cd}"' for cd in (model.cd or [''])),
          f'$body "body" "{body}"'] + ([] if physics and model.pieces else ['$staticprop']) + [f'$sequence "idle" "{stem}_ref.smd"']
    if model.surfaceprop:
        qc.append(f'$surfaceprop "{model.surfaceprop}"')
    if len(model.skins) > 1:
        used = sorted({m for m, _ in model.meshes})
        families = ['{ ' + ' '.join(f'"{model.textures[f[m]]}"' for m in used) + ' }' for f in model.skins]
        qc.append('$texturegroup "skinfamilies"\n{\n' + '\n'.join(families) + '\n}')
    pieces = getattr(model, 'pieces', [])
    if pieces:
        phys = []
        for pts, tris in pieces:
            for a, b, c in tris:
                phys.append('phys\n')
                n = np.cross(pts[b] - pts[a], pts[c] - pts[a]); n = n / np.linalg.norm(n)
                for i in (a, b, c):
                    phys.append(vertex(pts[i], n, (0.0, 1.0)))
        (folder / f'{stem}_phys.smd').write_text(smd(phys))
        mass = f'\t$mass {model.mass:g}\n' if physics and model.mass else ''
        qc.append(f'$collisionmodel "{stem}_phys.smd"\n{{\n{mass}\t$concave\n\t$maxconvexpieces 4096\n}}')
    (folder / f'{stem}.qc').write_text('\n'.join(qc) + '\n')
    return folder / f'{stem}.qc'


def load(content, name):
    model = Model(content, name)
    base = name.removesuffix('.mdl')
    try:
        model.pieces = phy_pieces(content.read(base + '.phy'))
    except KeyError:
        model.pieces = []
    model.mass, model.surfaceprop = None, None
    try:
        text = content.read(base + '.phy').decode('latin-1', 'replace')
        masses = [float(m) for m in re.findall(r'"mass"\s+"([-\d.]+)"', text)]
        model.mass = sum(masses) or None
        prop = re.search(r'"surfaceprop"\s+"([^"]+)"', text)
        model.surfaceprop = prop.group(1) if prop else None
    except KeyError:
        pass
    model.colours = None
    try:
        colours = vvc_colours(content.read(base + '.vvc'), content.read(base + '.vvd'))
        if len(colours) == len(model.vertices):
            model.colours = colours
    except (KeyError, ValueError):
        pass
    return model


def convert(names, assets, compiler, output, work=None, prefix='', physics=(), sources=None):
    """Compile each TF1 model into OUTPUT/models/...; returns {name: 'ok' | error}.

    PHYSICS names compile as physics props (no $staticprop). SOURCES maps an output name to the
    TF1 model it is built from, so one model can be compiled both ways: a static prop needs
    $staticprop (Titanfall 2 refuses others with "Unsupported per tri version 0") and a
    prop_physics needs a physics model.
    """
    global DMX
    import os
    if DMX is None:
        os.environ.setdefault('R2C_TOOLS', str(Path(compiler).resolve().parent / 'tools'))
        DMX = load_dmx_writer()
    content = TF1Content([assets])
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(work or tmp)
        for name in names:
            name = name.lower().replace('\\', '/')
            folder = root / Path(name).with_suffix('')
            folder.mkdir(parents=True, exist_ok=True)
            try:
                source = (sources or {}).get(name, name).lower().replace('\\', '/')
                qc = write_sources(load(content, source), name, folder, prefix, name in physics)
                run = subprocess.run([str(compiler), '-nop4', '-game', str(output), str(qc)],
                                     capture_output=True, text=True, cwd=folder)
                if run.returncode and 'collision model' in run.stdout + run.stderr:
                    # A flat or degenerate TF1 collision mesh: keep the model, without collision.
                    text = qc.read_text()
                    qc.write_text(text[:text.index('$collisionmodel')])
                    run = subprocess.run([str(compiler), '-nop4', '-game', str(output), str(qc)],
                                         capture_output=True, text=True, cwd=folder)
                target = Path(output) / name
                if run.returncode or not target.exists():
                    tail = (run.stdout + run.stderr).strip().splitlines()[-3:]
                    results[name] = 'compile failed: ' + ' | '.join(tail)
                else:
                    results[name] = 'ok'
            except Exception as e:  # report and continue with the other models
                results[name] = f'{type(e).__name__}: {e}'
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--compiler', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='mod folder that receives models/...')
    p.add_argument('--work', type=Path, help='keep the SMD/QC sources here')
    p.add_argument('--material-prefix', default='', help='prepended to every material directory, e.g. mrvn_lagoon/')
    p.add_argument('--report', type=Path)
    p.add_argument('models', nargs='+')
    a = p.parse_args(argv)
    results = convert(a.models, a.assets, a.compiler, a.output, a.work, a.material_prefix)
    if a.report:
        a.report.write_text(json.dumps(results, indent=1))
    failed = {k: v for k, v in results.items() if v != 'ok'}
    print(f'{len(results) - len(failed)} compiled, {len(failed)} failed')
    for k, v in list(failed.items())[:20]:
        print(' ', k, v)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
