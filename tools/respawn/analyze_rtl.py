#!/usr/bin/env python3
"""Decode and audit Respawn realtime-light (RTL) lightmap planes.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original analysis code; findings recorded in docs/respawn/RESPAWN_TF1_LUMPS.md
and docs/respawn/RESPAWN_LIGHTING.md.

Maps every lightmap texel of lit world meshes to a world position and normal,
then tests what LIGHTMAP_DATA_REAL_TIME_LIGHTS stores there:

* v29 (Titanfall 1): 4 bytes per texel, each a hardware light index (255 = none).
* v37 (Titanfall 2): RTL A (4 bytes: four 6-bit page slots, page in the top
  byte), RTL B (4 bytes: per-slot shadow visibility), then RTL C (1 byte per
  texel) when embedded; sidecars carry only A and B.

`lights` prints a field-by-field WORLD_LIGHTS summary so retail and compiled
maps can be compared. Offline statistics only: nothing here proves a shader.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import struct
import sys

import numpy as np

from inspect_bsp import FormatError, HEADER_SIZE, inspect

L_VERTICES, L_NORMALS, L_WORLD_LIGHTS = 0x03, 0x1E, 0x36
L_LIT_FLAT, L_LIT_BUMP = 0x48, 0x49
L_MESH_INDICES, L_MESHES, L_MATERIAL_SORT = 0x4F, 0x50, 0x52
L_LIGHTMAP_HEADERS, L_SKY, L_RTL, L_RTL_PAGES = 0x53, 0x62, 0x69, 0x7A

LIGHT_TYPES = {0: "surface", 1: "point", 2: "spot", 3: "sun", 4: "quake", 5: "ambient"}
UNUSED_TF1 = 255
UNUSED_TF2_SLOT = 63
UNUSED_TF2_WORD = 0xFFFFFFFF


def raw_lump(path, inventory, index, limit=512 * 1024 * 1024):
    """Bytes of one lump, preferring its default `.bsp_lump` sidecar."""
    entry = inventory["lumps"][index]
    external = next((e for e in entry["external_files"] if e["variant"] == "default"), None)
    size = external["size"] if external else entry["length"]
    if size > limit or (size and entry["fourcc"]):
        raise FormatError(f"lump {index:#x}: oversized or encoded payload")
    if external:
        return Path(external["path"]).read_bytes()
    if not size:
        return b""
    if entry["offset"] < HEADER_SIZE or entry["offset"] + size > inventory["size"]:
        raise FormatError(f"lump {index:#x}: embedded payload outside file")
    with Path(path).open("rb") as stream:
        stream.seek(entry["offset"])
        data = stream.read(size)
    if len(data) != size:
        raise FormatError(f"lump {index:#x}: truncated payload")
    return data


def rtl_is_external(inventory):
    entry = inventory["lumps"][L_RTL]
    return any(e["variant"] == "default" for e in entry["external_files"])


def world_lights(data, version):
    """WORLD_LIGHTS records as dicts; v29 records are 100 bytes, v37 are 112."""
    stride = 100 if version == 29 else 112
    if len(data) % stride:
        raise FormatError(f"WORLD_LIGHTS: {len(data)} bytes is not a multiple of {stride}")
    lights = []
    for i in range(len(data) // stride):
        v = struct.unpack_from("<12f3i7f3i", data, i * stride)
        tail = struct.unpack_from("<3f", data, i * stride + 100) if stride == 112 else ()
        lights.append({
            "index": i, "origin": v[0:3], "intensity": v[3:6], "normal": v[6:9],
            "shadow_offset": v[9:12], "viscluster": v[12], "type": v[13], "style": v[14],
            "stopdot": v[15], "stopdot2": v[16], "exponent": v[17], "radius": v[18],
            "constant": v[19], "linear": v[20], "quadratic": v[21], "flags": v[22],
            "texdata": v[23], "owner": v[24], "tail": tail})
    return lights


def hardware_indices(lights):
    """WORLD_LIGHTS index -> hardware index (ambient lights are not counted)."""
    table, hw = {}, 0
    for light in lights:
        if light["type"] == 5:
            continue
        table[light["index"]] = hw
        hw += 1
    return table


class Map:
    """Lit world geometry and lighting lumps of one v29 or v37 BSP."""

    def __init__(self, path):
        self.path = Path(path)
        self.inventory = inspect(path)
        self.version = self.inventory["version_raw"]
        if self.version not in (29, 37):
            raise FormatError(f"unsupported BSP version {self.version}")
        read = lambda index: raw_lump(path, self.inventory, index)
        self.lights = world_lights(read(L_WORLD_LIGHTS), self.version)
        self.hardware = hardware_indices(self.lights)
        self.by_hardware = {hw: i for i, hw in self.hardware.items()}
        self.headers = [struct.unpack_from("<I2H", read(L_LIGHTMAP_HEADERS), o)
                        for o in range(0, len(read(L_LIGHTMAP_HEADERS)), 8)]
        self.rtl = read(L_RTL)
        self.sky = read(L_SKY)
        self.rtl_external = rtl_is_external(self.inventory)
        pages = read(L_RTL_PAGES) if self.version == 37 else b""
        self.rtl_pages = [struct.unpack_from("<63h", pages, o) for o in range(0, len(pages) - 125, 126)]
        self._read = read

    # -- plane layout ---------------------------------------------------
    def texel_counts(self):
        return [w * h for _, w, h in self.headers]

    def rtl_bytes_per_texel(self):
        total = sum(self.texel_counts())
        return len(self.rtl) / total if total else 0.0

    def rtl_planes(self, page):
        """Per page: v29 -> (indices[h,w,4],); v37 -> (A[h,w,4], B[h,w,4])."""
        counts = self.texel_counts()
        _, w, h = self.headers[page]
        if self.version == 29:
            offset = sum(counts[:page]) * 4
            a = np.frombuffer(self.rtl, np.uint8, w * h * 4, offset).reshape(h, w, 4)
            return (a,)
        per_texel = 8 if self.rtl_external else 9
        offset = sum(counts[:page]) * per_texel
        a = np.frombuffer(self.rtl, np.uint8, w * h * 4, offset).reshape(h, w, 4)
        b = np.frombuffer(self.rtl, np.uint8, w * h * 4, offset + w * h * 4).reshape(h, w, 4)
        return a, b

    def slots(self, page):
        """Hardware light indices [h,w,4] (-1 = unused) and, for v37, the
        per-slot RTL B visibility [h,w,4] (None for v29)."""
        planes = self.rtl_planes(page)
        if self.version == 29:
            a = planes[0].astype(np.int16)
            return np.where(a == UNUSED_TF1, -1, a), None
        a, b = planes
        word = a.astype(np.uint32)
        word = word[..., 0] | (word[..., 1] << 8) | (word[..., 2] << 16) | (word[..., 3] << 24)
        table = np.array(self.rtl_pages, np.int16).reshape(-1, 63)
        out = np.full(word.shape + (4,), -1, np.int16)
        live = word != UNUSED_TF2_WORD
        page_index = (word >> 24).astype(np.int64)
        for k in range(4):
            slot = ((word >> (6 * k)) & 63).astype(np.int64)
            ok = live & (slot != UNUSED_TF2_SLOT) & (page_index < len(table))
            out[..., k][ok] = table[page_index[ok], slot[ok]]
        return out, b

    # -- geometry -------------------------------------------------------
    def lit_triangles(self, mesh_fraction=1.0, seed=1):
        """Per lightmap page: dict of triangle positions[n,3,3], vertex normals
        [n,3,3], lightmap uv[n,3,2] and the owning MESHES index[n]. With
        mesh_fraction < 1 a reproducible random subset of meshes is kept."""
        read = self._read
        positions = np.frombuffer(read(L_VERTICES), np.float32).reshape(-1, 3)
        normals = np.frombuffer(read(L_NORMALS), np.float32).reshape(-1, 3)
        streams = {0x000: (read(L_LIT_FLAT), 36), 0x200: (read(L_LIT_BUMP), 44)}
        indices = np.frombuffer(read(L_MESH_INDICES), np.uint16)
        sort_data = read(L_MATERIAL_SORT)
        sorts = [struct.unpack_from("<4hi", sort_data, o) for o in range(0, len(sort_data), 12)]
        meshes = read(L_MESHES)
        per_page = defaultdict(lambda: defaultdict(list))
        vertex_cache = {}
        keep = np.random.default_rng(seed).random(len(meshes) // 28) < mesh_fraction
        for mesh, o in enumerate(range(0, len(meshes), 28)):
            if not keep[mesh]:
                continue
            tri_offset, tri_count = struct.unpack_from("<IH", meshes, o)
            material, flags = struct.unpack_from("<HI", meshes, o + 22)
            kind = flags & 0x600
            if kind not in streams or tri_count == 0:
                continue
            _, page, _, _, vertex_offset = sorts[material]
            if page < 0 or page >= len(self.headers):
                continue
            if kind not in vertex_cache:
                data, stride = streams[kind]
                records = np.frombuffer(data, np.uint8).reshape(-1, stride)
                vertex_cache[kind] = (records[:, 0:4].copy().view(np.uint32).ravel(),
                                      records[:, 4:8].copy().view(np.uint32).ravel(),
                                      records[:, 20:28].copy().view(np.float32).reshape(-1, 2))
            pos_index, nrm_index, uv = vertex_cache[kind]
            local = indices[tri_offset:tri_offset + tri_count * 3].astype(np.int64) + vertex_offset
            out = per_page[page]
            out["pos"].append(positions[pos_index[local]].reshape(-1, 3, 3))
            out["nrm"].append(normals[nrm_index[local]].reshape(-1, 3, 3))
            out["uv"].append(uv[local].reshape(-1, 3, 2))
            out["mesh"].append(np.full(tri_count, mesh))
        return {p: {k: np.concatenate(v) for k, v in d.items()} for p, d in per_page.items()}

    def texels(self, max_per_page=None, seed=1, mesh_fraction=1.0):
        """Rasterize lit triangles: per page, arrays of texel x, y, world
        position, interpolated vertex normal and mesh index.

        Texel (x, y) has its centre at ((x + 0.5) / width, (y + 0.5) / height)
        in lightmap UV space. Each texel takes the first triangle covering it.
        """
        result = {}
        for page, tris in sorted(self.lit_triangles(mesh_fraction, seed).items()):
            _, w, h = self.headers[page]
            owner = np.zeros((h, w), bool)
            px = tris["uv"][:, :, 0] * w - 0.5
            py = tris["uv"][:, :, 1] * h - 0.5
            x0 = np.clip(np.floor(px.min(1)).astype(np.int64), 0, w - 1)
            x1 = np.clip(np.ceil(px.max(1)).astype(np.int64), 0, w - 1)
            y0 = np.clip(np.floor(py.min(1)).astype(np.int64), 0, h - 1)
            y1 = np.clip(np.ceil(py.max(1)).astype(np.int64), 0, h - 1)
            pieces = []
            for t in range(len(px)):
                gx, gy = np.meshgrid(np.arange(x0[t], x1[t] + 1), np.arange(y0[t], y1[t] + 1))
                ax, ay = px[t], py[t]
                d = (ay[1] - ay[2]) * (ax[0] - ax[2]) + (ax[2] - ax[1]) * (ay[0] - ay[2])
                if abs(d) < 1e-12:
                    continue
                l0 = ((ay[1] - ay[2]) * (gx - ax[2]) + (ax[2] - ax[1]) * (gy - ay[2])) / d
                l1 = ((ay[2] - ay[0]) * (gx - ax[2]) + (ax[0] - ax[2]) * (gy - ay[2])) / d
                l2 = 1 - l0 - l1
                inside = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4) & ~owner[gy, gx]
                if not inside.any():
                    continue
                gx, gy = gx[inside], gy[inside]
                owner[gy, gx] = True
                pieces.append((t, gx, gy, l0[inside], l1[inside], l2[inside]))
            if not pieces:
                continue
            tri = np.concatenate([np.full(len(p[1]), p[0]) for p in pieces])
            xs = np.concatenate([p[1] for p in pieces])
            ys = np.concatenate([p[2] for p in pieces])
            lam = np.stack([np.concatenate([p[k] for p in pieces]) for k in (3, 4, 5)], 1)
            if max_per_page and len(xs) > max_per_page:
                pick = np.random.default_rng(seed + page).choice(len(xs), max_per_page, replace=False)
                tri, xs, ys, lam = tri[pick], xs[pick], ys[pick], lam[pick]
            pos = np.einsum("nk,nkd->nd", lam, tris["pos"][tri].astype(np.float64))
            normal = np.einsum("nk,nkd->nd", lam, tris["nrm"][tri].astype(np.float64))
            normal /= np.maximum(np.linalg.norm(normal, axis=1, keepdims=True), 1e-12)
            result[page] = {"x": xs, "y": ys, "pos": pos, "normal": normal, "mesh": tris["mesh"][tri]}
        return result


def all_triangles(bsp):
    """World positions[n,3,3] of opaque MESHES triangles (occluders; static
    props are not included)."""
    read = bsp._read
    positions = np.frombuffer(read(L_VERTICES), np.float32).reshape(-1, 3)
    streams = {0x000: (read(L_LIT_FLAT), 36), 0x200: (read(L_LIT_BUMP), 44),
               0x400: (read(0x47), 20), 0x600: (read(0x4A), 28)}
    pools = {k: np.frombuffer(d, np.uint8).reshape(-1, s)[:, 0:4].copy().view(np.uint32).ravel()
             for k, (d, s) in streams.items() if d}
    indices = np.frombuffer(read(L_MESH_INDICES), np.uint16)
    sort_data = read(L_MATERIAL_SORT)
    meshes = read(L_MESHES)
    out = []
    for o in range(0, len(meshes), 28):
        tri_offset, tri_count = struct.unpack_from("<IH", meshes, o)
        material, flags = struct.unpack_from("<HI", meshes, o + 22)
        if not tri_count or (flags & 0x600) not in pools or flags & 0x16:
            continue  # sky (0x2, 0x4) and translucent (0x10) meshes do not occlude
        vertex_offset = struct.unpack_from("<i", sort_data, material * 12 + 8)[0]
        local = indices[tri_offset:tri_offset + tri_count * 3].astype(np.int64) + vertex_offset
        out.append(positions[pools[flags & 0x600][local]].reshape(-1, 3, 3))
    return np.concatenate(out).astype(np.float64)


class Occluders:
    """Uniform-grid segment/triangle visibility test (approximate: the
    segment is sampled every third of a cell, so grazing corners can be missed)."""

    def __init__(self, triangles, cell=64.0):
        self.tri = triangles
        self.cell = cell
        lo = np.floor(triangles.min(1) / cell).astype(np.int64)
        hi = np.floor(triangles.max(1) / cell).astype(np.int64)
        self.origin = lo.min(0)
        self.dims = hi.max(0) - self.origin + 1
        keys, ids = [], []
        span = hi - lo
        simple = np.all(span == 0, axis=1)
        keys.append(self._key(lo[simple]))
        ids.append(np.nonzero(simple)[0])
        for t in np.nonzero(~simple)[0]:
            if np.prod(span[t] + 1) > 4096:
                continue  # huge triangles (skies, terrain): skipped
            g = np.stack(np.meshgrid(*[np.arange(lo[t, a], hi[t, a] + 1) for a in range(3)],
                                     indexing="ij"), -1).reshape(-1, 3)
            keys.append(self._key(g))
            ids.append(np.full(len(g), t))
        keys = np.concatenate(keys)
        ids = np.concatenate(ids)
        order = np.argsort(keys, kind="stable")
        self.keys, self.ids = keys[order], ids[order]

    def _key(self, cells):
        c = cells - self.origin
        return (c[:, 0] * self.dims[1] + c[:, 1]) * self.dims[2] + c[:, 2]

    def blocked(self, start, end):
        """True if any triangle crosses the open segment start->end."""
        return self.hits(start, end).size > 0

    def hits(self, start, end):
        """Sorted segment parameters (0..1) of triangle crossings."""
        length = np.linalg.norm(end - start)
        steps = max(2, int(length / (self.cell / 3)) + 1)
        pts = start + (end - start) * np.linspace(0, 1, steps)[:, None]
        cells = np.unique(np.floor(pts / self.cell).astype(np.int64), axis=0)
        inside = np.all((cells >= self.origin) & (cells < self.origin + self.dims), axis=1)
        keys = self._key(cells[inside])
        a = np.searchsorted(self.keys, keys, "left")
        b = np.searchsorted(self.keys, keys, "right")
        if not np.any(b > a):
            return np.empty(0)
        cand = np.unique(np.concatenate([self.ids[i:j] for i, j in zip(a, b)]))
        tri = self.tri[cand]
        d = end - start
        e1 = tri[:, 1] - tri[:, 0]
        e2 = tri[:, 2] - tri[:, 0]
        p = np.cross(d, e2)
        det = (e1 * p).sum(1)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1), 0)
        s = start - tri[:, 0]
        u = (s * p).sum(1) * inv
        q = np.cross(s, e1)
        v = (q @ d) * inv
        t = (e2 * q).sum(1) * inv
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-4) & (t < 1 - 1e-4)
        return np.sort(t[hit])


# -- analysis -------------------------------------------------------------

def light_reach(light, pos, normal):
    """Geometric reach of a point/spot light: inside its radius, in front of
    the surface and inside the outer cone. Returns (mask, dist/radius)."""
    d = np.asarray(light["origin"]) - pos
    dist = np.linalg.norm(d, axis=1)
    dn = d / np.maximum(dist[:, None], 1e-9)
    radius = light["radius"]
    ratio = dist / radius if radius > 0 else np.zeros(len(pos))
    reach = (ratio <= 1) & ((dn * normal).sum(1) > 0)
    if light["type"] == 2:
        reach &= (-dn @ np.asarray(light["normal"])) >= light["stopdot2"]
    return reach, ratio


def gather(bsp, **texel_options):
    """Flattened texels: hardware slots[n,4], RTL B masks[n,4] (zeros for v29),
    SKY B[n,4], positions, normals and mesh ids."""
    counts = bsp.texel_counts()
    out = defaultdict(list)
    for page, t in bsp.texels(**texel_options).items():
        hw, mask = bsp.slots(page)
        _, w, h = bsp.headers[page]
        offset = sum(counts[:page]) * 8 + w * h * 4
        sky_b = np.frombuffer(bsp.sky, np.uint8, w * h * 4, offset).reshape(h, w, 4)
        out["slots"].append(hw[t["y"], t["x"]])
        out["masks"].append(mask[t["y"], t["x"]] if mask is not None
                            else np.zeros((len(t["x"]), 4), np.uint8))
        out["sky_b"].append(sky_b[t["y"], t["x"]])
        for key in ("pos", "normal", "mesh"):
            out[key].append(t[key])
    if not out:
        return None
    return {k: np.concatenate(v) for k, v in out.items()}


def kind(light):
    return f"type{light['type']}/flags{light['flags']}"


def analyze(path, rays=2000, seed=3, **texel_options):
    """Statistics that test the RTL encoding of one map (see module docstring)."""
    bsp = Map(path)
    report = {"map": str(path), "version": bsp.version, "pages": [list(h) for h in bsp.headers],
              "rtl_bytes_per_texel": round(bsp.rtl_bytes_per_texel(), 3),
              "rtl_external": bsp.rtl_external, "rtl_pages": len(bsp.rtl_pages),
              "lights": dict(Counter(kind(l) for l in bsp.lights))}
    if bsp.version == 37:
        page_kinds = Counter()
        for table in bsp.rtl_pages:
            for hw in set(table):
                if hw in bsp.by_hardware:
                    page_kinds[kind(bsp.lights[bsp.by_hardware[hw]])] += 1
        report["rtl_page_entry_kinds"] = dict(page_kinds)
    data = gather(bsp, **texel_options)
    if data is None:
        report["texels"] = 0
        return report
    slots, pos, normal = data["slots"].astype(np.int64), data["pos"], data["normal"]
    used = slots >= 0
    report["texels"] = int(len(slots))
    report["slots_used_histogram"] = {int(k): int(v) for k, v in sorted(Counter(used.sum(1).tolist()).items())}
    report["filled_in_order"] = float(np.mean(np.all(np.diff(used.astype(int), axis=1) <= 0, axis=1)))
    kinds = Counter()
    for hw, count in Counter(slots[used].tolist()).items():
        kinds[kind(bsp.lights[bsp.by_hardware[hw]]) if hw in bsp.by_hardware else "invalid"] += count
    report["slot_light_kinds"] = dict(kinds)
    if bsp.version == 37:
        masks = data["masks"]
        unused_mask = masks[~used]
        report["rtl_b_unused_slot_values"] = {int(k): int(v) for k, v in Counter(unused_mask.tolist()).most_common(4)}

    # Geometric reach of every realtime or slotted point/spot light.
    slotted = set(slots[used].tolist())
    local = [l for l in bsp.lights if l["type"] in (1, 2) and
             (bsp.hardware.get(l["index"]) in slotted or l["flags"] & 8)]
    in_slot, reach = {}, {}
    by_kind = defaultdict(Counter)
    for light in local:
        hw = bsp.hardware[light["index"]]
        in_slot[hw] = (slots == hw).any(1)
        reach[hw] = light_reach(light, pos, normal)[0]
        c = by_kind[kind(light)]
        c["reached"] += int(reach[hw].sum())
        c["reached_in_slot"] += int((reach[hw] & in_slot[hw]).sum())
        c["slot_outside_reach"] += int((in_slot[hw] & ~reach[hw]).sum())
    report["geometric_recall"] = {k: dict(v, recall=round(v["reached_in_slot"] / max(v["reached"], 1), 4))
                                  for k, v in by_kind.items()}

    multi = used.sum(1) >= 2
    ascending = sum(1 for row in slots[multi] if list(row[row >= 0]) == sorted(row[row >= 0]))
    report["multi_slot_ascending_fraction"] = round(ascending / max(int(multi.sum()), 1), 4)

    if rays:
        occ = Occluders(all_triangles(bsp))
        rng = np.random.default_rng(seed)
        groups = defaultdict(list)
        for light in local:
            groups[kind(light)].append(light)
        occlusion = {}
        for key, lights in sorted(groups.items()):
            pairs = [(i, l) for l in lights for i in np.nonzero(reach[bsp.hardware[l["index"]]])[0]]
            if not pairs:
                continue
            table, mask_values = Counter(), defaultdict(list)
            for k in rng.choice(len(pairs), min(rays, len(pairs)), replace=False):
                i, light = pairs[k]
                hw = bsp.hardware[light["index"]]
                blocked = occ.blocked(pos[i] + normal[i], np.asarray(light["origin"]))
                slot = bool(in_slot[hw][i])
                table[(slot, blocked)] += 1
                if slot and bsp.version == 37:
                    mask_values[blocked].append(int(data["masks"][i][list(slots[i]).index(hw)]))
            entry = {}
            for blocked, name in ((False, "clear"), (True, "blocked")):
                total = table[(True, blocked)] + table[(False, blocked)]
                entry[name] = total
                entry[f"p_slot_given_{name}"] = round(table[(True, blocked)] / max(total, 1), 4)
                if mask_values[blocked]:
                    entry[f"mean_rtl_b_given_{name}"] = round(float(np.mean(mask_values[blocked])), 1)
            occlusion[key] = entry
        report["occlusion"] = occlusion

        sun = next((l for l in bsp.lights if l["type"] == 3), None)
        if sun is not None:
            toward = -np.asarray(sun["normal"])
            facing = np.nonzero(normal @ toward > 0.05)[0]
            alpha = data["sky_b"][:, 3]
            table = Counter()
            for i in rng.choice(facing, min(rays, len(facing)), replace=False):
                start = pos[i] + normal[i]
                blocked = occ.blocked(start, start + toward * 30000)
                a = alpha[i]
                table[(blocked, "255" if a == 255 else "0" if a == 0 else "between")] += 1
            report["sky_b_alpha_vs_sun"] = {
                name: {c: table[(b, c)] for c in ("0", "between", "255")}
                for b, name in ((False, "clear"), (True, "blocked"))}
    report["sky_b_alpha_top"] = {int(k): int(v) for k, v in
                                 Counter(data["sky_b"][:, 3].tolist()).most_common(8)}
    return report


SCALAR_FIELDS = ("style", "viscluster", "texdata", "owner", "exponent", "constant",
                 "linear", "quadratic", "radius", "stopdot", "stopdot2")


def light_summary(path):
    """Per (type, flags) group: value ranges of every WORLD_LIGHTS field."""
    bsp = Map(path)
    groups = defaultdict(list)
    for light in bsp.lights:
        groups[kind(light)].append(light)
    summary = {}
    for key, lights in sorted(groups.items()):
        entry = {"count": len(lights)}
        for field in SCALAR_FIELDS:
            values = [l[field] for l in lights]
            entry[field] = [round(min(values), 4), round(max(values), 4)]
        for field in ("shadow_offset", "tail"):
            values = Counter(tuple(round(x, 3) for x in l[field]) for l in lights)
            entry[field] = {str(k): v for k, v in values.most_common(3)}
        peak = [max(l["intensity"]) for l in lights]
        entry["max_intensity"] = [round(min(peak), 4), round(max(peak), 4)]
        summary[key] = entry
    return {"map": str(path), "version": bsp.version, "lights": len(bsp.lights),
            "pages": [list(h) for h in bsp.headers], "groups": summary}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rtl = sub.add_parser("rtl", help="decode and test the realtime-light plane")
    rtl.add_argument("bsp", nargs="+")
    rtl.add_argument("--rays", type=int, default=2000, help="ray-cast samples per light group (0: off)")
    rtl.add_argument("--mesh-fraction", type=float, default=1.0, help="rasterize this share of meshes")
    lights = sub.add_parser("lights", help="WORLD_LIGHTS field ranges per type/flags")
    lights.add_argument("bsp", nargs="+")
    args = parser.parse_args(argv)
    for path in args.bsp:
        if args.command == "rtl":
            result = analyze(path, rays=args.rays, mesh_fraction=args.mesh_fraction)
        else:
            result = light_summary(path)
        print(json.dumps(result, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
