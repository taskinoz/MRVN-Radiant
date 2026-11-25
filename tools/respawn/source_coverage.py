#!/usr/bin/env python3
"""Which visible faces of a Source map have no render geometry in its converted Titanfall 2 map?

Samples points on every visible face of the original BSP (the world plus
func_brush, func_illusionary, func_wall, func_detail and func_lod, at their
entity origins; displacements excluded) and reports the share of visible area
with no compiled render triangle within 2 units, by owner and by material.
Water and clear glass are expected to show up: the converter leaves them out.

  python tools/respawn/source_coverage.py original.bsp converted.bsp

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import sys, struct, collections
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_engine as se
from inspect_bsp import inspect
from validate_records import load_records

src, out = sys.argv[1], sys.argv[2]
b = se.BSP(src)
pts = np.array([struct.unpack_from('<3f', b.lumps[se.VERTEXES], i) for i in range(0, len(b.lumps[se.VERTEXES]), 12)])
edges = list(struct.iter_unpack('<2H', b.lumps[se.EDGES])); sfe = [s[0] for s in struct.iter_unpack('<i', b.lumps[se.SURFEDGES])]
faces = list(struct.iter_unpack('<HBBihhhh4BiF2i2iiHHI'.replace('F', 'f'), b.lumps[se.FACES]))
models = {0: ('world', np.zeros(3))}
for e in b.entities:
    m = e.get('model', '')
    if m.startswith('*') and e.get('classname') in ('func_brush', 'func_illusionary', 'func_wall', 'func_detail', 'func_lod'):
        models[int(m[1:])] = (e.get('classname'), np.array([float(v) for v in e.get('origin', '0 0 0').split()]))
samples = []  # (point, area share, material, owner)
for model, (owner, offset) in models.items():
    first, count = b.models[model][10], b.models[model][11]
    for f in faces[first:first + count]:
        if f[5] < 0: continue
        t = b.texinfo[f[5]]; m = (t.material or '').lower()
        if t.flags & (se.SURF_NODRAW | se.SURF_SKY | se.SURF_SKY2D | se.SURF_HINT | se.SURF_SKIP) or m.startswith('tools/'): continue
        if f[6] >= 0: continue  # displacement faces are converted separately
        poly = [offset + (pts[edges[e][0]] if e >= 0 else pts[edges[-e][1]]) for e in sfe[f[3]:f[3] + f[4]]]
        for i in range(1, len(poly) - 1):
            a, c, d = poly[0], poly[i], poly[i + 1]
            area = np.linalg.norm(np.cross(c - a, d - a)) / 2
            if area < 16: continue
            for u, v in ((1/3, 1/3), (.6, .2), (.2, .6)):
                samples.append(((a + (c - a) * u + (d - a) * v), area / 3, m, owner))
print('samples', len(samples))

r = load_records(out, inspect(out))
tris = []
for mi in range(len(r[14])):
    first, count = r[14][mi][6:8]
    for m in range(first, first + count):
        mesh = r[80][m]; sort = r[82][mesh[-2]]
        pool = r[{0: 72, 0x200: 73, 0x400: 71, 0x600: 74}[mesh[-1] & 0x600]]
        raw = [sort[4] + v[0] for v in r[79][mesh[0]:mesh[0] + mesh[1] * 3]]
        for i in range(0, len(raw), 3):
            tt = raw[i:i + 3]
            if len(set(tt)) == 3: tris.append([r[3][pool[j][0]] for j in tt])
T = np.array(tris, float)
# Distance from each sample to the nearest compiled triangle plane within its projection, via a coarse grid.
cell = 256.0
grid = collections.defaultdict(list)
lo, hi = T.min(1), T.max(1)
for i in range(len(T)):
    for x in range(int(lo[i, 0] // cell), int(hi[i, 0] // cell) + 1):
        for y in range(int(lo[i, 1] // cell), int(hi[i, 1] // cell) + 1):
            for z in range(int(lo[i, 2] // cell), int(hi[i, 2] // cell) + 1):
                grid[(x, y, z)].append(i)


def covered(p, tol=2.0):
    ids = grid.get(tuple((p // cell).astype(int)), [])
    if not ids: return False
    t = T[ids]; a, bb, c = t[:, 0], t[:, 1], t[:, 2]
    n = np.cross(bb - a, c - a); ln = np.linalg.norm(n, axis=1); ok = ln > 1e-9; n = n[ok] / ln[ok, None]; a, bb, c = a[ok], bb[ok], c[ok]
    d = np.einsum('ij,ij->i', p - a, n); q = p - d[:, None] * n
    def side(x, y): return np.einsum('ij,ij->i', np.cross(y - x, q - x), n)
    inside = (side(a, bb) >= -1) & (side(bb, c) >= -1) & (side(c, a) >= -1)
    return bool((inside & (np.abs(d) <= tol)).any())


miss = collections.Counter(); total = collections.Counter(); bymat = collections.Counter()
for p, area, m, owner in samples:
    total[owner] += area
    if not covered(np.asarray(p, float)):
        miss[owner] += area; bymat[m] += area
for o in total: print(f'{o}: {100 * miss[o] / total[o]:.1f}% of {total[o]:.0f} visible area uncovered')
print('top uncovered materials:', [(m, int(a)) for m, a in bymat.most_common(12)])
