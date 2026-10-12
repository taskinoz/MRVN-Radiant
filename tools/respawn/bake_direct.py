#!/usr/bin/env python3
"""Offline direct-light/brush-shadow reference baker, not an engine atlas bake.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later. Original code.
Outputs linear sample values and a vertex-colour glTF diagnostic preview.
No GI, area/spot lights, dynamic props, albedo, probes or engine shader decode.
"""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import struct
import time

from inspect_bsp import FormatError, inspect
from lighting import encode_point_lights
from validate_records import load_records, validate


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def box_segment(bounds, start, delta):
    lo, hi = 0.0, 1.0
    for i in range(3):
        if abs(delta[i]) < 1e-12:
            if not bounds[0][i] <= start[i] <= bounds[1][i]:
                return False
        else:
            a = (bounds[0][i] - start[i]) / delta[i]
            b = (bounds[1][i] - start[i]) / delta[i]
            lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
            if lo > hi:
                return False
    return True


def convex_segment(planes, start, delta):
    lo, hi = 0.0, 1.0
    for plane in planes:
        numerator = plane[3] - dot(plane[:3], start)
        denominator = dot(plane[:3], delta)
        if abs(denominator) < 1e-12:
            if numerator < -1e-6:
                return False
        elif denominator > 0:
            hi = min(hi, numerator / denominator)
        else:
            lo = max(lo, numerator / denominator)
        if lo > hi:
            return False
    return hi > 1e-6 and lo < 1 - 1e-6


class BrushTree:
    def __init__(self, brushes):
        self.bounds = (tuple(min(b[0][0][i] for b in brushes) for i in range(3)),
                       tuple(max(b[0][1][i] for b in brushes) for i in range(3))) if brushes else None
        self.children = []
        self.brushes = brushes
        if len(brushes) > 8:
            axis = max(range(3), key=lambda i: self.bounds[1][i] - self.bounds[0][i])
            ordered = sorted(brushes, key=lambda b: b[0][0][axis] + b[0][1][axis])
            middle = len(ordered) // 2
            self.children = [BrushTree(ordered[:middle]), BrushTree(ordered[middle:])]
            self.brushes = []

    def blocked(self, start, end):
        return self._blocked(start, subtract(end, start))

    def _blocked(self, start, delta):
        if self.bounds is None or not box_segment(self.bounds, start, delta):
            return False
        if self.children:
            return any(child._blocked(start, delta) for child in self.children)
        return any(box_segment(bounds, start, delta) and convex_segment(planes, start, delta)
                   for bounds, planes in self.brushes)


def collision_brushes(records):
    result = []
    base = records[85][0][6] if records[85] else 0
    for b in records[92]:
        center, extent = b[:3], b[6:9]
        bounds = (tuple(center[i] - extent[i] for i in range(3)),
                  tuple(center[i] + extent[i] for i in range(3)))
        planes = []
        for axis in range(3):
            for sign in (1, -1):
                normal = [0.0] * 3
                normal[axis] = sign
                planes.append((*normal, sign * center[axis] + extent[axis]))
        for j in range(b[4]):
            offset = b[9] + j
            planes.append(records[1][base + offset - records[93][offset][0]])
        if any(not all(math.isfinite(v) for v in plane) or dot(plane[:3], plane[:3]) < 1e-12
               for plane in planes):
            raise FormatError("invalid collision plane in occlusion geometry")
        result.append((bounds, planes))
    return result


def evaluate(position, normal, lights, tree, ambient=0.03, bias=0.25):
    length = math.sqrt(dot(normal, normal))
    if length < 1e-8 or not all(math.isfinite(v) for v in (*position, *normal)):
        raise ValueError("invalid lighting sample")
    normal = tuple(v / length for v in normal)
    start = tuple(position[i] + normal[i] * bias for i in range(3))
    rgb, visible, blocked = [ambient] * 3, 0, 0
    for light in lights:
        delta = subtract(light["origin"], start)
        distance2 = dot(delta, delta)
        if distance2 <= 1e-12 or distance2 > light.get("radius", 512) ** 2:
            continue
        distance = math.sqrt(distance2)
        cosine = max(0.0, dot(normal, delta) / distance)
        if cosine <= 0:
            continue
        if tree.blocked(start, light["origin"]):
            blocked += 1
            continue
        visible += 1
        c, linear, quadratic = light.get("attenuation", (1, 0, 0.001))
        denominator = max(1e-12, c + linear * distance + quadratic * distance2)
        for channel in range(3):
            rgb[channel] += light["intensity"][channel] * cosine / denominator
    return tuple(rgb), visible, blocked


def quake_lights(path):
    """Experimental conversion; Quake brightness is not Respawn calibrated."""
    depth, keys, result = 0, {}, []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        line = line.strip()
        if line == "{":
            depth += 1
            if depth == 1:
                keys = {}
        elif line == "}":
            if depth == 1 and keys.get("classname") in ("light", "light_fluoro", "light_fluorospark"):
                strength = float(keys.get("light", "300"))
                color = tuple(map(float, keys.get("_color", "1 1 1").split()))
                result.append({"origin": list(map(float, keys["origin"].split())),
                               "intensity": [c * strength / 300 for c in color],
                               "radius": max(64, strength * 2), "attenuation": [1, 0, 0.0001]})
            depth -= 1
        elif depth == 1:
            match = re.fullmatch(r'"([^"\n]+)"\s+"([^"\n]*)"', line)
            if match:
                keys[match[1]] = match[2]
    if depth or not result:
        raise ValueError("incomplete MAP or no point lights")
    encode_point_lights(result)
    return result


def bake(bsp, lights, output, ambient=0.03):
    if not math.isfinite(ambient) or ambient < 0:
        raise ValueError("ambient must be finite and nonnegative")
    encode_point_lights(lights)
    inv = inspect(bsp)
    if inv["version_raw"] != 37 or validate(bsp)["issues"]:
        raise FormatError("baker requires validated v37 geometry")
    r = load_records(bsp, inv)
    if len(r[14]) != 1:
        raise FormatError("baker currently supports a single static world model only")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    tree = BrushTree(collision_brushes(r))
    started = time.monotonic()
    binary, indices, cache = bytearray(), [], {}
    samples, visible_rays, blocked_rays = [], 0, 0
    # glTF uses x,z,-y. Sample normals use the source's Z-up convention.
    for mesh in r[80]:
        kind = mesh[-1] & 0x600
        pool = {0: 72, 0x200: 73, 0x400: 71, 0x600: 74}[kind]
        sort = r[82][mesh[-2]]
        for item in r[79][mesh[0]:mesh[0] + mesh[1] * 3]:
            v = r[pool][sort[4] + item[0]]
            position, normal = r[3][v[0]], r[30][v[1]]
            key = tuple(position) + tuple(normal)
            if key not in cache:
                rgb, visible, blocked = evaluate(position, normal, lights, tree, ambient)
                visible_rays += visible
                blocked_rays += blocked
                n = len(samples)
                cache[key] = n
                samples.append((*position, *normal, *rgb, visible, blocked))
                # glTF vertex colours are linear; the viewer applies display
                # gamma. Reinhard here is diagnostic, not engine calibration.
                display = [round(255 * (value / (1 + value))) for value in rgb]
                binary.extend(struct.pack("<6f4B", position[0], position[2], -position[1],
                                          normal[0], normal[2], -normal[1], *display, 255))
            indices.append(cache[key])
    if not samples:
        raise FormatError("no triangles available to bake")
    vertex_bytes = len(binary)
    binary.extend(struct.pack("<" + "I" * len(indices), *indices))
    (root / "direct.bin").write_bytes(binary)
    points = [(s[0], s[2], -s[1]) for s in samples]
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": vertex_bytes, "byteStride": 28, "target": 34962},
             {"buffer": 0, "byteOffset": vertex_bytes, "byteLength": len(indices) * 4, "target": 34963}]
    accessors = [{"bufferView": 0, "byteOffset": 0, "componentType": 5126, "count": len(samples),
                  "type": "VEC3", "min": [min(p[i] for p in points) for i in range(3)],
                  "max": [max(p[i] for p in points) for i in range(3)]},
                 {"bufferView": 0, "byteOffset": 12, "componentType": 5126, "count": len(samples), "type": "VEC3"},
                 {"bufferView": 0, "byteOffset": 24, "componentType": 5121, "count": len(samples), "type": "VEC4", "normalized": True},
                 {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}]
    gltf = {"asset": {"version": "2.0", "generator": "MRVN-Radiant offline direct lighting reference"},
            "extensionsUsed": ["KHR_materials_unlit"], "extensionsRequired": ["KHR_materials_unlit"],
            "scene": 0, "scenes": [{"nodes": [0]}],
            "nodes": [{"mesh": 0}], "buffers": [{"uri": "direct.bin", "byteLength": len(binary)}],
            "bufferViews": views, "accessors": accessors,
            "materials": [{"extensions": {"KHR_materials_unlit": {}}, "doubleSided": True}],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1, "COLOR_0": 2},
                                          "indices": 3, "material": 0}]}]}
    (root / "direct.gltf").write_text(json.dumps(gltf, indent=2) + "\n")
    with (root / "samples.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["x", "y", "z", "nx", "ny", "nz", "linear_r", "linear_g", "linear_b", "visible", "blocked"])
        writer.writerows(samples)
    report = {"source": str(Path(bsp).resolve()), "samples": len(samples), "triangles": len(indices) // 3,
              "point_lights": len(lights), "visible_rays": visible_rays, "blocked_rays": blocked_rays,
              "ambient": ambient, "bias": 0.25, "elapsed_seconds": time.monotonic() - started,
              "engine_atlas_written": False, "engine_tested": False,
              "limitations": ["vertex samples only", "static brush occlusion only", "no GI/probes/CSM",
                              "Quake light strengths are experimental", "display tone map is not engine decoding"]}
    (root / "bake.json").write_text(json.dumps(report, indent=2) + "\n")
    (root / "lights.json").write_text(json.dumps(lights, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bsp", type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--lights", type=Path)
    source.add_argument("--quake-map", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--ambient", type=float, default=0.03)
    args = parser.parse_args()
    lights = json.loads(args.lights.read_text()) if args.lights else quake_lights(args.quake_map)
    print(json.dumps(bake(args.bsp, lights, args.output, args.ambient), indent=2))
