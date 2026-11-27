#!/usr/bin/env python3
"""TF1 PHYSICS_TRIANGLES (lump 0x46): parser, validator and hull generator.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original code. Layout read from retail v29 maps and the TFO vphysics.dll
packer (RVA 0x6870/0x56b0) and unpacker (0x6dd0); see
docs/respawn/RESPAWN_TF1_LUMPS.md ("PHYSICS_TRIANGLES").

Lump: u16 count (= TRICOLL headers), u16 size[count], then the non-null
blobs back to back. Sizes 0 and 0xffff are null (retail writes 0xffff).
Blob (Source's packed virtual-mesh hull):

    u8  hullCount; u8 pad[3]                     (pad is zero)
    hullCount x { u8 faces, virtualFaces, edges, virtualEdges, baseVertex }
    per hull: faces x { u8 edge[3], u8 pierce }, then edges x { u8 v0, v1 }

A face's edges run in its winding (counter-clockwise from outside). The
first face using an edge walks it v0->v1, the second v1->v0. Vertices are
header-local vertex indices minus baseVertex. Faces [0, virtualFaces) and
edges [0, virtualEdges) carry IVP's is_virtual bit. pierce is the hull face
index IVP stores as pierce_index.

The retail hull is IVP's qhull-based root hull of the header's triangles,
whose face order, triangulation and virtual bits vary between translated
copies of identical geometry. build_hull() therefore produces an equivalent
hull (same convex shape and limits), not retail's exact bytes.
"""
import argparse
import json
import math
import struct
from fractions import Fraction
from pathlib import Path

NULL_SIZES = (0, 0xffff)
# Engine (vphysics FitsInPackedHull, RVA 0x67e0): 3 * faces <= 512 and the
# hull's vertex index range above min(baseVertex, 255) must fit in a byte.
MAX_FACES = 170
SOLID_MASK = 0x1 | 0x2 | 0x8  # CONTENTS_SOLID | WINDOW | GRATE
MAX_SIMPLIFY = 2.0  # units a simplified hull may leave points outside


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------- parsing

def split_lump(data):
    """Return one blob (bytes) or None per TRICOLL header."""
    if len(data) == 0:
        return []
    if len(data) < 2:
        raise FormatError("PHYSICS_TRIANGLES shorter than its count")
    count = struct.unpack_from("<H", data, 0)[0]
    if len(data) < 2 + 2 * count:
        raise FormatError("PHYSICS_TRIANGLES size table truncated")
    sizes = struct.unpack_from(f"<{count}H", data, 2)
    pos = 2 + 2 * count
    blobs = []
    for size in sizes:
        if size in NULL_SIZES:
            blobs.append(None)
            continue
        if pos + size > len(data):
            raise FormatError("PHYSICS_TRIANGLES blob outside lump")
        blobs.append(bytes(data[pos:pos + size]))
        pos += size
    if pos != len(data):
        raise FormatError(f"PHYSICS_TRIANGLES has {len(data) - pos} trailing bytes")
    return blobs


def parse_blob(blob):
    """Decode a blob into a list of hull dicts."""
    if len(blob) < 4:
        raise FormatError("hull blob shorter than its hull count")
    count = blob[0]
    if count == 0:
        raise FormatError("hull blob with no hulls")
    pos = 4 + 5 * count
    if len(blob) < pos:
        raise FormatError("hull headers truncated")
    hulls = []
    for h in range(count):
        faces, vfaces, edges, vedges, base = blob[4 + 5 * h:9 + 5 * h]
        end = pos + 4 * faces + 2 * edges
        if end > len(blob):
            raise FormatError("hull face/edge data truncated")
        face_records = [tuple(blob[pos + 4 * i:pos + 4 * i + 4]) for i in range(faces)]
        pos += 4 * faces
        edge_records = [tuple(blob[pos + 2 * i:pos + 2 * i + 2]) for i in range(edges)]
        pos += 2 * edges
        hulls.append({"faces": face_records, "edges": edge_records, "virtual_faces": vfaces,
                      "virtual_edges": vedges, "base": base})
    if pos != len(blob):
        raise FormatError(f"hull blob has {len(blob) - pos} trailing bytes")
    return {"pad": bytes(blob[1:4]), "hulls": hulls}


def hull_triangles(hull):
    """Header-local vertex triangles, reconstructed exactly as the engine
    unpacker does (first use of an edge starts at v0, the second at v1)."""
    seen = set()
    result = []
    for face in hull["faces"]:
        tri = []
        for e in face[:3]:
            v0, v1 = hull["edges"][e]
            tri.append((v1 if e in seen else v0) + hull["base"])
            seen.add(e)
        result.append(tuple(tri))
    return result


def check_blob(blob, vertex_count=None):
    """Structural checks; returns a list of problem strings."""
    try:
        parsed = parse_blob(blob)
    except FormatError as error:
        return [str(error)]
    problems = []
    if parsed["pad"] != b"\0\0\0":
        problems.append("nonzero hull-count padding")
    if len(parsed["hulls"]) > 2:
        problems.append("more than two hulls (engine queries use at most two)")
    for index, hull in enumerate(parsed["hulls"]):
        def bad(message):
            problems.append(f"hull {index}: {message}")
        faces, edges = hull["faces"], hull["edges"]
        if len(faces) < 2 or len(faces) > MAX_FACES:
            bad(f"{len(faces)} faces outside 2..{MAX_FACES}")
        if 2 * len(edges) != 3 * len(faces):
            bad("edge count is not 1.5 x face count")
        if hull["virtual_faces"] > len(faces) or hull["virtual_edges"] > len(edges):
            bad("virtual count exceeds its array")
        uses = [0] * len(edges)
        for face in faces:
            if face[3] >= len(faces):
                bad("pierce index outside hull faces")
                break
            for e in face[:3]:
                if e >= len(edges):
                    bad("face edge index outside hull edges")
                    break
                uses[e] += 1
        if any(u != 2 for u in uses):
            bad("an edge is not shared by exactly two faces")
            continue
        try:
            tris = hull_triangles(hull)
        except IndexError:
            continue
        # Each face's edges must chain into its triangle, and every directed
        # edge must appear once in each direction (closed, consistently wound).
        directed = set()
        for tri in tris:
            if len(set(tri)) != 3:
                bad("degenerate face")
                break
            for k in range(3):
                directed.add((tri[k], tri[(k + 1) % 3]))
        if len(directed) != 3 * len(tris) or any((b, a) not in directed for a, b in directed):
            bad("faces do not close into a consistently wound hull")
        for f, face in enumerate(faces):
            ends = [hull["edges"][e] for e in face[:3]]
            if not all(set(ends[k]) & set(ends[(k + 1) % 3]) for k in range(3)):
                bad(f"face {f} edges do not chain")
                break
        verts = {v for e in edges for v in e}
        if len(verts) - len(edges) + len(faces) != 2:
            bad("Euler characteristic is not 2")
        if vertex_count is not None and verts and max(verts) + hull["base"] >= vertex_count:
            bad("vertex index outside the TRICOLL header")
    return problems


# ---------------------------------------------------------------- geometry

def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    length = math.sqrt(_dot(a, a))
    return (a[0] / length, a[1] / length, a[2] / length) if length > 0 else (0.0, 0.0, 0.0)


def _plane(p, a, b, c):
    n = _unit(_cross(_sub(p[b], p[a]), _sub(p[c], p[a])))
    return n, _dot(n, p[a])


def _exact(points):
    """Points as exact integers (float coordinates are dyadic rationals), so
    hull orientation tests are exact and the hull is always convex."""
    shift = 0
    for p in points:
        for c in p:
            shift = max(shift, Fraction(c).denominator.bit_length() - 1)
    return [tuple(int(Fraction(c) * (1 << shift)) for c in p) for p in points], float(1 << shift)


def convex_hull(points, eps):
    """Outward, counter-clockwise triangles (indices into points) of the
    convex hull. Points less than eps outside the hull are skipped, so only
    clearly extreme points become vertices. Returns (triangles, flat) or
    (None, False) for collinear/degenerate input."""
    n = len(points)
    if n < 3:
        return None, False
    q, scale = _exact(points)
    i0 = min(range(n), key=lambda i: points[i])
    i1 = max(range(n), key=lambda i: _dot(_sub(points[i], points[i0]), _sub(points[i], points[i0])))
    axis = _sub(points[i1], points[i0])
    if _dot(axis, axis) <= eps * eps:
        return None, False

    def line_distance(i):
        c = _cross(axis, _sub(points[i], points[i0]))
        return _dot(c, c)
    i2 = max(range(n), key=line_distance)
    if line_distance(i2) <= (eps * eps) * _dot(axis, axis):
        return None, False
    normal, d = _plane(points, i0, i1, i2)
    i3 = max(range(n), key=lambda i: abs(_dot(normal, points[i]) - d))
    if abs(_dot(normal, points[i3]) - d) <= eps:
        return _flat_hull(points, q, eps * scale), True

    faces = {}
    edge_face = {}
    next_id = [0]

    def add(a, b, c):
        fid = next_id[0]
        next_id[0] += 1
        nq = _cross(_sub(q[b], q[a]), _sub(q[c], q[a]))
        faces[fid] = [(a, b, c), nq, math.sqrt(float(_dot(nq, nq))), []]
        for k in range(3):
            edge_face[((a, b, c)[k], (a, b, c)[(k + 1) % 3])] = fid
        return fid

    def side(fid, i):
        f = faces[fid]
        return _dot(f[1], _sub(q[i], q[f[0][0]]))

    def far_face(i, candidates):
        best, far = None, eps * scale
        for fid in candidates:
            s = side(fid, i)
            if s > 0 and s / faces[fid][2] > far:
                best, far = fid, s / faces[fid][2]
        return best

    first = add(i0, i1, i2)
    if side(first, i3) > 0:
        del faces[first]
        edge_face.clear()
        i1, i2 = i2, i1
        first = add(i0, i1, i2)
    initial = [first, add(i0, i3, i1), add(i1, i3, i2), add(i2, i3, i0)]
    used = {i0, i1, i2, i3}
    for i in range(n):
        if i not in used:
            best = far_face(i, initial)
            if best is not None:
                faces[best][3].append(i)
    while True:
        pending = next((fid for fid in sorted(faces) if faces[fid][3]), None)
        if pending is None:
            # A point can be outside a face it was never queued on; re-queue.
            for i in range(n):
                best = far_face(i, sorted(faces))
                if best is not None:
                    faces[best][3].append(i)
                    pending = best
            if pending is None:
                break
            continue
        f = faces[pending]
        apex = max(f[3], key=lambda i: side(pending, i))
        visible = {pending}
        stack = [pending]
        while stack:
            fid = stack.pop()
            tri = faces[fid][0]
            for k in range(3):
                other = edge_face.get((tri[(k + 1) % 3], tri[k]))
                if other is not None and other not in visible and side(other, apex) > 0:
                    visible.add(other)
                    stack.append(other)
        horizon = []
        orphans = []
        for fid in sorted(visible):
            tri = faces[fid][0]
            for k in range(3):
                a, b = tri[k], tri[(k + 1) % 3]
                if edge_face.get((b, a)) not in visible:
                    horizon.append((a, b))
            orphans.extend(i for i in faces[fid][3] if i != apex)
        for fid in sorted(visible):
            tri = faces[fid][0]
            for k in range(3):
                key = (tri[k], tri[(k + 1) % 3])
                if edge_face.get(key) == fid:
                    del edge_face[key]
            del faces[fid]
        created = [add(a, b, apex) for a, b in sorted(horizon)]
        for i in orphans:
            best = far_face(i, created)
            if best is not None:
                faces[best][3].append(i)
    return [faces[fid][0] for fid in sorted(faces)], False


def _flat_hull(points, q, tolerance):
    """Coplanar input: a double-sided polygon (top fan from its first vertex,
    bottom fan from its second, so the two sides use different diagonals).
    The polygon is the 2D hull after dropping the dominant normal axis, without
    vertices less than `tolerance` (scaled units) from their neighbours' line."""
    n = len(points)
    i0 = min(range(n), key=lambda i: points[i])
    i1 = max(range(n), key=lambda i: _dot(_sub(points[i], points[i0]), _sub(points[i], points[i0])))
    axis = _sub(points[i1], points[i0])
    i2 = max(range(n), key=lambda i: _dot(_cross(axis, _sub(points[i], points[i0])),
                                         _cross(axis, _sub(points[i], points[i0]))))
    normal = _cross(_sub(q[i1], q[i0]), _sub(q[i2], q[i0]))
    drop = max(range(3), key=lambda k: abs(normal[k]))
    keep = [k for k in range(3) if k != drop]
    flat = sorted(set((q[i][keep[0]], q[i][keep[1]], i) for i in range(n)))

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def chain(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and turn(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = chain(flat), chain(list(reversed(flat)))
    ring = lower[:-1] + upper[:-1]
    # Then drop vertices nearly on the line through their ring neighbours.
    changed = True
    while changed and len(ring) > 3:
        changed = False
        for k in range(len(ring)):
            o, a, b = ring[k - 1], ring[k], ring[(k + 1) % len(ring)]
            if turn(o, a, b) <= tolerance * math.hypot(b[0] - o[0], b[1] - o[1]):
                del ring[k]
                changed = True
                break
    ring = [p[2] for p in ring]
    # Counter-clockwise in (keep0, keep1) is counter-clockwise about +axis
    # `drop` when (keep0, keep1, drop) is a right-handed order.
    if (normal[drop] > 0) == (drop == 1):
        ring.reverse()
    if len(ring) < 3:
        return None
    top = [(ring[0], ring[i], ring[i + 1]) for i in range(1, len(ring) - 1)]
    back = [ring[1], ring[0]] + ring[:1:-1]
    bottom = [(back[0], back[i], back[i + 1]) for i in range(1, len(back) - 1)]
    return top + bottom


def build_hull(vertices, triangles, eps=None, max_simplify=MAX_SIMPLIFY, window=None):
    """Pack the hull of a TRICOLL header's triangles.

    vertices: header-local (x, y, z) Source positions; triangles: local index
    triples. window: only use vertex indices in [window, window + 255].
    Returns a hull dict for pack_blob(), or None when the triangles have no
    2D/3D extent or the hull exceeds the engine's packing limits.
    """
    used = sorted({v for tri in triangles for v in tri})
    # The engine maps each hull point to the nearest header vertex, the
    # lowest index winning ties (vphysics RVA 0x53f0).
    first_at = {}
    for i, p in enumerate(vertices):
        first_at.setdefault(tuple(float(c) for c in p), i)
    unique = sorted({first_at[tuple(float(c) for c in vertices[i])] for i in used})
    if window is not None:
        unique = [i for i in unique if window <= i <= window + 255]
    if len(unique) < 3:
        return None
    points = [tuple(float(c) for c in vertices[i]) for i in unique]
    if eps is None:
        extent = max(max(abs(c) for c in p) for p in points)
        eps = max(1e-3, extent * 1e-6)
    # Over the packing limits: simplify by ignoring points within a growing
    # distance of the hull, up to max_simplify units (retail's IVP hulls are
    # simplified too, often more).
    while True:
        tris, flat = convex_hull(points, eps)
        if not tris:
            return None
        tris = [tuple(unique[i] for i in tri) for tri in tris]
        hv = sorted({v for tri in tris for v in tri})
        base = min(hv[0], 255)
        if len(tris) <= MAX_FACES and hv[-1] - base <= 255:
            break
        eps *= 2
        if eps > max_simplify:
            return None
    # Edges in first-use order; the first face to use an edge walks it v0->v1.
    edge_index = {}
    edges = []
    faces = []
    for tri in tris:
        refs = []
        for k in range(3):
            a, b = tri[k], tri[(k + 1) % 3]
            if (b, a) in edge_index:
                refs.append(edge_index[(b, a)])
            else:
                edge_index[(a, b)] = len(edges)
                refs.append(len(edges))
                edges.append((a - base, b - base))
        faces.append(refs)
    pos = {i: vertices[i] for i in hv}
    normals = [_unit(_cross(_sub(pos[b], pos[a]), _sub(pos[c], pos[a]))) for a, b, c in tris]
    for f, refs in enumerate(faces):
        # IVP pierce_index: a face roughly opposite this one. Retail's choice is
        # a near-minimum of the normal dot product; the global minimum is used.
        dots = [(_dot(normals[f], normals[g]), g) for g in range(len(faces)) if g != f]
        refs.append(min(dots)[1])
    return {"faces": [tuple(r) for r in faces], "edges": edges, "virtual_faces": len(faces),
            "virtual_edges": len(edges), "base": base, "flat": flat}


def pack_blob(hulls):
    if not 1 <= len(hulls) <= 2:
        raise ValueError("a packed hull blob holds one or two hulls")
    out = bytearray([len(hulls), 0, 0, 0])
    for hull in hulls:
        out += bytes([len(hull["faces"]), hull["virtual_faces"], len(hull["edges"]),
                      hull["virtual_edges"], hull["base"]])
    for hull in hulls:
        for face in hull["faces"]:
            out += bytes(face)
        for edge in hull["edges"]:
            out += bytes(edge)
    return bytes(out)


def build_blob(vertices, triangles):
    """Pack a header's hull blob. In order: one hull of all triangles; two
    hulls over the triangle halves [0, n/2) and [n/2, n), as the engine's
    two-hull queries split them; finally one hull of the 256-index vertex
    window that leaves the vertices least far outside (retail hulls also
    leave geometry outside). Returns None only for degenerate triangles."""
    hull = build_hull(vertices, triangles)
    if hull:
        return pack_blob([hull])
    half = len(triangles) // 2
    if half:
        parts = [build_hull(vertices, triangles[:half]), build_hull(vertices, triangles[half:])]
        if all(parts):
            return pack_blob(parts)
    used = sorted({v for tri in triangles for v in tri})
    best = None
    for start in range(used[0], max(used[0], used[-1] - 255) + 1, 16):
        hull = build_hull(vertices, triangles, max_simplify=float("inf"), window=start)
        if hull:
            gap = outside_distance(vertices, hull_triangles(hull), used)
            if best is None or gap < best[0]:
                best = (gap, hull)
    return pack_blob([best[1]]) if best else None


def build_lump(blobs):
    """blobs: bytes or None per TRICOLL header."""
    if len(blobs) > 0xffff:
        raise ValueError("more than 65535 TRICOLL headers")
    sizes = []
    for blob in blobs:
        if blob is not None and not 0 < len(blob) < 0xffff:
            raise ValueError("hull blob size does not fit the u16 table")
        sizes.append(0xffff if blob is None else len(blob))
    return struct.pack(f"<H{len(sizes)}H", len(sizes), *sizes) + b"".join(b for b in blobs if b is not None)


def build(headers):
    """headers: (vertices, triangles, contents) per TRICOLL header. Retail
    writes a hull exactly for SOLID, WINDOW or GRATE headers. Returns the lump.
    A solid header whose triangles are degenerate gets a null entry."""
    blobs = []
    for vertices, triangles, contents in headers:
        if isinstance(contents, (set, frozenset)):
            merged = 0
            for value in contents:
                merged |= value
            contents = merged
        if not isinstance(contents, int) or not contents & SOLID_MASK:
            blobs.append(None)
            continue
        blobs.append(build_blob(vertices, triangles))
    return build_lump(blobs)


# ---------------------------------------------------------------- BSP access

def header_contents(records):
    """Collision-grid contents per TRICOLL header index (set of values)."""
    sets, primitives, unique = records.get(87, []), records.get(89, []), records.get(91, [])
    result = {}
    words = []
    for _, count, word in sets:
        if count == 1:
            words.append(word)
        elif count > 1:
            start = (word >> 8) & 0xffff
            words.extend(p[0] for p in primitives[start:start + count])
    for word in words:
        kind, index, u = word >> 24, (word >> 8) & 0xffff, word & 0xff
        if kind == 0x40 and u < len(unique):
            result.setdefault(index, set()).add(unique[u][0])
    return result


def load_headers(path):
    from inspect_bsp import inspect
    from tricoll import triangle_indices
    from validate_records import load_raw_payload, load_records
    inv = inspect(Path(path))
    if inv["version_raw"] != 29:
        raise FormatError("PHYSICS_TRIANGLES decoding is for TF1 BSP v29")
    records = load_records(Path(path), inv)
    headers = []
    for h in records[69]:
        nv, nt, fv, ft = h[3], h[4], h[6], h[7]
        headers.append((records[3][fv:fv + nv], [triangle_indices(w[0]) for w in records[66][ft:ft + nt]]))
    return headers, records, load_raw_payload(Path(path), inv, 0x46)


def outside_distance(vertices, tris, indices):
    """Largest distance of the given vertices outside a closed hull (0 if
    all are inside). Flat hulls measure distance off the polygon plane."""
    planes = []
    for a, b, c in tris:
        n = _unit(_cross(_sub(vertices[b], vertices[a]), _sub(vertices[c], vertices[a])))
        if n != (0.0, 0.0, 0.0):
            planes.append((n, _dot(n, vertices[a])))
    worst = 0.0
    for i in indices:
        worst = max(worst, max((_dot(n, vertices[i]) - d for n, d in planes), default=0.0))
    return worst


def compare(path):
    """Field-level comparison of regenerated hulls against a retail map."""
    headers, records, data = load_headers(path)
    blobs = split_lump(data)
    contents = header_contents(records)
    stats = {"headers": len(headers), "blobs": sum(b is not None for b in blobs), "valid": 0,
             "presence_known": 0, "presence_match": 0, "compared": 0, "generated": 0,
             "vertex_set": 0, "counts": 0, "base": 0, "face_set": 0, "virtual_counts": 0,
             "pierce_same_faces": 0, "pierce_total": 0, "bytes": 0, "problems": {}}
    if len(blobs) != len(headers):
        raise FormatError("PHYSICS_TRIANGLES count differs from TRICOLL header count")
    for i, (blob, (vertices, triangles)) in enumerate(zip(blobs, headers)):
        cs = contents.get(i)
        if cs:
            stats["presence_known"] += 1
            stats["presence_match"] += (blob is not None) == any(c & SOLID_MASK for c in cs)
        if blob is None:
            continue
        problems = check_blob(blob, len(vertices))
        for p in problems:
            stats["problems"][p] = stats["problems"].get(p, 0) + 1
        if problems:
            continue
        stats["valid"] += 1
        retail = parse_blob(blob)["hulls"]
        mine = build_blob(vertices, triangles)
        stats["compared"] += 1
        if mine is None:
            continue
        stats["generated"] += 1
        stats["bytes"] += mine == blob
        ours = parse_blob(mine)["hulls"]
        if len(ours) != len(retail):
            continue
        r, o = retail[0], ours[0]
        rt, ot = hull_triangles(r), hull_triangles(o)
        used = {v for t in triangles for v in t}
        for name, tris in (("retail", rt), ("ours", ot)):
            gap = outside_distance(vertices, tris, used)
            stats[name + "_max_outside"] = max(stats.get(name + "_max_outside", 0.0), round(gap, 3))
            for limit in (0.1, 0.5):
                key = f"{name}_outside_over_{limit}"
                stats[key] = stats.get(key, 0) + (gap > limit)
        rv = {tuple(vertices[v]) for t in rt for v in t}
        ov = {tuple(vertices[v]) for t in ot for v in t}
        stats["vertex_set"] += rv == ov
        stats["counts"] += (len(r["faces"]), len(r["edges"])) == (len(o["faces"]), len(o["edges"]))
        stats["base"] += r["base"] == o["base"]
        stats["virtual_counts"] += (r["virtual_faces"], r["virtual_edges"]) == (o["virtual_faces"], o["virtual_edges"])
        canon = lambda t: min(t[k:] + t[:k] for k in range(3))
        rset, oset = {canon(t) for t in rt}, {canon(t) for t in ot}
        if rset == oset:
            stats["face_set"] += 1
            where = {canon(t): f for f, t in enumerate(ot)}
            for f, t in enumerate(rt):
                stats["pierce_total"] += 1
                stats["pierce_same_faces"] += canon(ot[o["faces"][where[canon(t)]][3]]) == canon(rt[r["faces"][f][3]])
    return stats


def write_lump(source, output):
    """Write an equivalent PHYSICS_TRIANGLES lump to a new v29 BSP."""
    headers, records, _ = load_headers(source)
    if output.exists():
        raise FileExistsError(output)
    if source.stat().st_size > 256 * 1024 * 1024:
        raise FormatError("PHYSICS_TRIANGLES writer size limit exceeded")
    inv = __import__("inspect_bsp", fromlist=["inspect"]).inspect(source)
    if inv["issues"]:
        raise FormatError("PHYSICS_TRIANGLES writer requires a clean BSP inventory")
    if any(entry["external_files"] for entry in inv["lumps"]):
        raise FormatError("PHYSICS_TRIANGLES writer refuses sidecar-bearing BSPs")
    contents = header_contents(records)
    lump = build([(vertices, triangles, contents.get(i, set())) for i, (vertices, triangles) in enumerate(headers)])
    data = bytearray(source.read_bytes())
    data.extend(bytes((-len(data)) % 4))
    offset = len(data)
    data.extend(lump)
    struct.pack_into("<4I", data, 16 + 0x46 * 16, offset, len(lump), 0, 0)
    with output.open("xb") as stream:
        stream.write(data)
    return len(lump)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("bsp", type=Path, nargs="+")
    parser.add_argument("--compare", action="store_true", help="regenerate hulls and compare fields")
    parser.add_argument("--write", type=Path, metavar="OUTPUT",
                        help="write a regenerated lump to a new v29 BSP")
    args = parser.parse_args(argv)
    failed = False
    for path in args.bsp:
        if args.write:
            if len(args.bsp) != 1:
                parser.error("--write requires exactly one BSP")
            try:
                print(json.dumps({"path": str(path), "output": str(args.write),
                                  "bytes": write_lump(path, args.write)}))
            except (FormatError, FileExistsError, ValueError) as error:
                print(json.dumps({"path": str(path), "error": str(error)}))
                failed = True
            continue
        if args.compare:
            report = compare(path)
        else:
            headers, _, data = load_headers(path)
            blobs = split_lump(data)
            problems = {}
            for i, blob in enumerate(blobs):
                if blob is not None:
                    for p in check_blob(blob, len(headers[i][0]) if i < len(headers) else None):
                        problems[p] = problems.get(p, 0) + 1
            report = {"headers": len(headers), "entries": len(blobs),
                      "blobs": sum(b is not None for b in blobs), "problems": problems}
            failed |= bool(problems) or (blobs and len(blobs) != len(headers))
        print(json.dumps({"path": str(path), **report}, indent=2))
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
