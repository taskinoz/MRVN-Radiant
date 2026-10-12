#!/usr/bin/env python3
"""Compile original regression geometry with an explicitly supplied remap binary.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No game assets required. Outputs and logs remain in a new working directory.
"""
import argparse
import json
from pathlib import Path
import struct
import subprocess

from inspect_bsp import inspect
from validate_records import load_records, validate


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


def entity(**keys):
    return "{\n" + "".join(f'"{k}" "{v}"\n' for k, v in keys.items()) + "}\n"


# A floor with a roof over its x<0 half. The sun travels down at 60 degrees
# towards +x+y, so the roof's shadow reaches past its edge to about x=+84.
LIT_FIXTURE = (
    '{\n"classname" "worldspawn"\n'
    + box((-512, -512, -16), (512, 512, 0), "bump") + "\n"
    + box((-512, -512, 256), (0, 512, 272), "bump") + "\n}\n"
    + entity(classname="light_environment", origin="0 0 512", pitch="-60", angles="60 30 0",
             _light="255 240 220 600", _ambient="150 180 255 100")
    + entity(classname="light_spot", origin="0 384 200", pitch="-90", angles="90 0 0",
             _light="255 255 255 400", _distance="400", _cone="45", _inner_cone="20")
    + entity(classname="light", origin="256 -256 64", _light="255 200 150 200", _distance="256")
    + entity(classname="light", origin="-256 0 64", _light="255 255 255 255", _distance="256", realtime="0")
)


def tangent_checks(bsp):
    """Bump-lit tangents follow retail: unit, along +dP/du, bit 31 = mirrored."""
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
            n, tangent = normals[bump[a][1]], normals[word & 0x7fffffff]
            if second or abs(dot(tangent, tangent) - 1) > 1e-3 or abs(dot(tangent, n)) > 1e-3:
                raise RuntimeError("tangent is not a unit vector perpendicular to the normal")
            if dot(tangent, du) <= 0 or (dot(cross(n, tangent), dv) < 0) != bool(word >> 31):
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
    # Hardware indices: sun 0, spot 1, realtime point 2, static point 3.
    if probe_near(256, -256, 64)[16] == 0 or 2 not in probe_near(256, -256, 64)[20:24]:
        raise RuntimeError("probe beside the realtime point light has no link to it")
    if probe_near(-300, 0, 64)[15] != 0 or probe_near(400, 0, 64)[15] != 8192:
        raise RuntimeError("probe sun visibility does not follow the roof")
    if any(3 in p[20:24] for p in probes):
        raise RuntimeError("static light was linked from a probe")
    if [(l[13], l[22]) for l in lights] != [(5, 0), (3, 24), (2, 28), (1, 28), (1, 4)]:
        raise RuntimeError(f"world light order/flags: {[(l[13], l[22]) for l in lights]}")
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

    # Hardware indices: sun 0, spot 1, realtime point 2, static point 3.
    for x, expected in ((-256, 0), (64, 0), (256, 255), (448, 255)):
        if realtime(x, 0).get(0) != expected:
            raise RuntimeError(f"sun mask at x={x}: {realtime(x, 0)} (expected {expected})")
    if realtime(256, -256).get(2) != 255:
        raise RuntimeError(f"realtime point light missing below it: {realtime(256, -256)}")
    if realtime(0, 384).get(1) is None:
        raise RuntimeError(f"spotlight missing below it: {realtime(0, 384)}")
    if any(3 in realtime(x, 0) for x in (-256, -128)):
        raise RuntimeError("static light was given an RTL slot")
    if not sky_a(-256, 0) > sky_a(-256, -448) + 0.05:
        raise RuntimeError(f"static light not baked into SKY A: {sky_a(-256, 0)} vs {sky_a(-256, -448)}")
    if not sky_a(400, 0) > sky_a(-448, 400) > 0:
        raise RuntimeError("roof does not reduce sky ambient")


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
             "overlap_extra": "UnlitGeneric", "overlap": "UnlitGeneric"}
    (shaders / "compat.shader").write_text("\n".join(
        f"textures/compat/{name}\n{{\n $shadertype {kind}\n}}"
        for name, kind in types.items()) + '\ntextures/compat/sky\n{\n $shadertype LitBumpGeneric\n $compileflag sky\n $surfaceflag sky\n}\n', encoding="utf-8")
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
            tangent_checks(bsp)
            records = load_records(bsp, inventory)
            if not records[92][0][4] or records[92][1][4] or not records[92][1][9]:
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
        if game == "titanfall2":
            lit_path = folder / "lit.map"
            lit_path.write_text(LIT_FIXTURE, encoding="utf-8")
            with (folder / "lit.log").open("wb") as log:
                subprocess.run(command[:-1] + [str(lit_path)], stdout=log, stderr=subprocess.STDOUT, check=True)
            lit_report = validate(lit_path.with_suffix(".bsp"))
            if lit_report["issues"]:
                raise RuntimeError(f"lit fixture: {lit_report['issues']}")
            lit_fixture_checks(lit_path.with_suffix(".bsp"))
            reports.append({"game": game, "fixture": "lit", "issues": []})
    (root / "results.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
