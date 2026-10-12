#!/usr/bin/env python3
# GPL-2.0-or-later. Usage: probe_axial_order.py MAP.bsp [...]
"""Score candidate axial brush-side orders against a retail rBSP v29/v37 map."""
import os, struct, sys
path = sys.argv[1]  # adjacent .bsp_lump sidecars override embedded lumps
def lump(i):
    side = f"{path}.{i:04x}.bsp_lump"
    if os.path.exists(side):
        return open(side, "rb").read()
    with open(path, "rb") as f:
        f.seek(16 + i * 16); off, ln, _, _ = struct.unpack("<4I", f.read(16))
        f.seek(off); return f.read(ln)
planes = list(struct.iter_unpack("<4f", lump(0x01)))
grid = struct.unpack("<f6i", lump(0x55)[:28]); first_plane = grid[6]
brushes = list(struct.iter_unpack("<3f2BH3fi", lump(0x5C)))
offs = [o[0] for o in struct.iter_unpack("<H", lump(0x5D))]
props = [p[0] for p in struct.iter_unpack("<H", lump(0x5E))]
texvecs = list(struct.iter_unpack("<8f", lump(0x5F)))
H = {
 "+X -X +Y -Y +Z -Z (current)": [(0,1),(0,-1),(1,1),(1,-1),(2,1),(2,-1)],
 "-X +X -Y +Y -Z +Z (old)":     [(0,-1),(0,1),(1,-1),(1,1),(2,-1),(2,1)],
 "+X +Y +Z -X -Y -Z (bsp_tool)":[(0,1),(1,1),(2,1),(0,-1),(1,-1),(2,-1)],
 "-X -Y -Z +X +Y +Z":           [(0,-1),(1,-1),(2,-1),(0,1),(1,1),(2,1)],
}
score = {k: [0, 0] for k in H}; axis_hits = {k: [0, 0] for k in H}; n = 0
for b in brushes:
    _, _, _, unk, count, index, _, _, _, spi = b
    start = 6 * index + spi
    for k in range(6):  # texture vectors: s and t are perpendicular to the face normal
        s, t = texvecs[start + k][0:3], texvecs[start + k][4:7]
        for name, order in H.items():
            a = order[k][0]
            if abs(s[a]) < 1e-3 and abs(t[a]) < 1e-3: axis_hits[name][0] += 1
            axis_hits[name][1] += 1
    cuts = []
    for i in range(count):
        o = spi + i
        cuts.append(planes[first_plane + o - offs[o]][:3])
    if not count: continue
    for k in range(6):
        if not props[start + k] & 0x4000: continue
        n += 1
        for name, order in H.items():
            a, sgn = order[k]
            score[name][1] += 1
            if any(c[a] * sgn > 0.01 for c in cuts): score[name][0] += 1
print(os.path.basename(path), "brushes", len(brushes), "discarded axial slots", n)
for name in H:
    print(f"  {name:30s} discard-consistent {score[name][0]}/{score[name][1]}  texvec-axis {axis_hits[name][0]}/{axis_hits[name][1]}")

# Discriminating test: a discarded slot whose cut normals all point one way
# along that slot's axis. Count which sign convention each such slot supports.
plus_first = minus_first = 0
for b in brushes:
    _, _, _, unk, count, index, _, _, _, spi = b
    if not count: continue
    start = 6 * index + spi
    cuts = [planes[first_plane + spi + i - offs[spi + i]][:3] for i in range(count)]
    for k in range(6):
        if not props[start + k] & 0x4000: continue
        a = k // 2
        signs = {1 if c[a] > 0.01 else -1 for c in cuts if abs(c[a]) > 0.01}
        if len(signs) != 1: continue
        sgn = signs.pop()
        slot_sign_if_plus_first = 1 if k % 2 == 0 else -1
        if sgn == slot_sign_if_plus_first: plus_first += 1
        else: minus_first += 1
print(f"  unambiguous slots: support +X-first {plus_first}, support -X-first {minus_first}")
