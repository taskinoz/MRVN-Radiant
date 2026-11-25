#!/usr/bin/env python3
"""Original Respawn lighting research, inspection and authored-light tools.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Schema facts credited in docs/respawn/RESPAWN_LIGHTING.md; no upstream code imported.
RGBA exports expose stored bytes, not a proven shader decode or bake.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

from inspect_bsp import FormatError, HEADER_SIZE, inspect
from validate_records import load_records
from validate_records import validate

WORLD_FORMATS = {1: "12f3i7f3i", 2: "12f3i7f3i2f", 3: "12f3i7f3i3f"}


def payload(path, inventory, index, limit=256 * 1024 * 1024):
    entry = inventory["lumps"][index]
    external = next((e for e in entry["external_files"] if e["variant"] == "default"), None)
    size = external["size"] if external else entry["length"]
    if size > limit or entry["fourcc"]:
        raise FormatError(f"lump {index}: oversized or encoded payload")
    if external:
        data = Path(external["path"]).read_bytes()
    elif size:
        if entry["offset"] < HEADER_SIZE or entry["offset"] + size > inventory["size"]:
            raise FormatError(f"lump {index}: invalid embedded range")
        with Path(path).open("rb") as stream:
            stream.seek(entry["offset"])
            data = stream.read(size)
    else:
        data = b""
    if len(data) != size:
        raise FormatError(f"lump {index}: truncated payload")
    return data, "default_external" if external else "internal"


def records(data, fmt, label):
    stride = struct.calcsize("<" + fmt)
    if len(data) % stride:
        raise FormatError(f"{label}: partial {stride}-byte record")
    return list(struct.iter_unpack("<" + fmt, data))


def png_rgba(width, height, data):
    if width <= 0 or height <= 0 or len(data) != width * height * 4:
        raise ValueError("RGBA image size mismatch")
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value))
    scan = b"".join(b"\0" + data[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(scan)) + chunk(b"IEND", b""))


def inspect_lighting(path, export=None, embedded=False):
    inv = inspect(path)
    if embedded:
        for entry in inv["lumps"]:
            entry["external_files"] = []
    version = inv["version_raw"]
    if version not in (29, 37) or inv["byte_order"] != "little":
        raise FormatError("typed lighting inspection currently supports little-endian v29/v37 only")
    headers, _ = payload(path, inv, 83)
    if headers and inv["lumps"][83]["version"] != 1:
        raise FormatError("unsupported LIGHTMAP_HEADERS record version")
    headers = records(headers, "I2H", "lightmap headers")
    if any(not w or not h or w > 16384 or h > 16384 for _, w, h in headers):
        raise FormatError("invalid atlas dimensions")
    texels = sum(w * h for _, w, h in headers)
    world, _ = payload(path, inv, 54)
    world_version = inv["lumps"][54]["version"]
    if world and world_version not in WORLD_FORMATS:
        raise FormatError(f"unsupported world-light version {world_version}")
    lights = records(world, WORLD_FORMATS.get(world_version, WORLD_FORMATS[1]), "world lights")
    issues = []
    decoded = []
    for n, r in enumerate(lights):
        numeric = (*r[:12], *r[15:22], *r[25:])
        if not all(math.isfinite(v) for v in numeric):
            issues.append(f"world light {n}: nonfinite float")
        decoded.append({"origin": r[:3], "intensity": r[3:6], "normal": r[6:9],
                        "shadow_offset": r[9:12], "viscluster": r[12], "type": r[13],
                        "style": r[14], "spot_cosines": r[15:17], "exponent": r[17],
                        "radius": r[18], "attenuation": r[19:22], "flags": r[22],
                        "texture_data": r[23], "parent": r[24], "unknown_tail": r[25:]})
    report = {"path": str(Path(path).resolve()), "bsp_version": version,
              "payload_mode": "embedded" if embedded else "effective_default",
              "headers": [{"type": t, "width": w, "height": h} for t, w, h in headers],
              "texels": texels, "world_light_version": world_version,
              "world_lights": decoded, "light_types": dict(Counter(r[13] for r in lights)),
              "issues": issues, "atlases": [], "engine_decode_verified": False}
    if export:
        export = Path(export)
        export.mkdir(parents=True, exist_ok=False)
    for lump, kind in ((98, "sky"), (105, "rtl")):
        data, storage = payload(path, inv, lump)
        # Observed stored plane layouts; channel meanings are unresolved.
        planes = 2 if lump == 98 or version == 37 else 1
        half = lump == 105 and version == 37 and storage == "internal"
        if half and any(w % 2 or h % 2 for _, w, h in headers):
            raise FormatError("internal R2 RTL half-plane requires even dimensions")
        expected = sum(w * h * planes * 4 + ((w // 2) * (h // 2) * 4 if half else 0)
                       for _, w, h in headers)
        report[kind] = {"bytes": len(data), "expected_bytes": expected, "storage": storage,
                        "bytes_per_header_texel": len(data) / texels if texels else None,
                        "layout_matches": len(data) == expected}
        if len(data) != expected:
            issues.append(f"{kind}: expected {expected} plane bytes, found {len(data)}")
            continue
        cursor = 0
        for page, (_, w, h) in enumerate(headers):
            layout = [(chr(65 + n), w, h) for n in range(planes)]
            if half:
                layout.append(("C", w // 2, h // 2))
            for name, width, height in layout:
                size = width * height * 4
                pixels = data[cursor:cursor + size]
                entry = {"lump": lump, "page": page, "plane": name, "width": width,
                         "height": height, "offset": cursor, "bytes": size,
                         "sha256": hashlib.sha256(pixels).hexdigest(),
                         "channel_ranges": [[min(pixels[c::4], default=0), max(pixels[c::4], default=0)]
                                            for c in range(4)]}
                if export:
                    (export / f"{kind}-{page:04d}-{name}.rgba").write_bytes(pixels)
                    # A raw alpha channel may make the bytes invisible. Emit an
                    # opaque RGB preview and separate alpha grayscale preview.
                    opaque = bytearray(pixels)
                    opaque[3::4] = bytes([255]) * (width * height)
                    (export / f"{kind}-{page:04d}-{name}-rgb.png").write_bytes(png_rgba(width, height, opaque))
                    alpha = b"".join(bytes((v, v, v, 255)) for v in pixels[3::4])
                    (export / f"{kind}-{page:04d}-{name}-alpha.png").write_bytes(png_rgba(width, height, alpha))
                report["atlases"].append(entry)
                cursor += size
    selected = load_records(path, inv)
    sorts = selected[82]
    report["material_lightmap_indices"] = dict(Counter(s[1] for s in sorts))
    for n, sort in enumerate(sorts):
        if sort[1] < -1 or sort[1] >= len(headers):
            issues.append(f"material sort {n}: atlas reference out of range")
    for pool in (72, 73):
        values = [v for r in selected[pool] for v in r[8:10]]
        report[f"pool_{pool}_uv"] = {"count": len(values) // 2,
                                     "min": min(values, default=0), "max": max(values, default=0),
                                     "nonfinite": sum(not math.isfinite(v) for v in values)}
    if export:
        (export / "lighting.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def encode_point_lights(lights):
    """Explicit R2/v3 experimental records, not a brightness calibration."""
    output = bytearray()
    if len(lights) > 16352:
        raise ValueError("world-light count exceeds documented R2 limit")
    for light in lights:
        origin, intensity = tuple(light["origin"]), tuple(light["intensity"])
        attenuation = tuple(light.get("attenuation", (1, 0, 0.001)))
        radius = light.get("radius", 512)
        if (len(origin) != 3 or len(intensity) != 3 or len(attenuation) != 3 or
                not all(math.isfinite(x) for x in (*origin, *intensity, *attenuation, radius)) or
                any(x < 0 for x in (*intensity, *attenuation)) or radius <= 0 or
                not any(x > 0 for x in attenuation)):
            raise ValueError("invalid point-light parameters")
        values = (*origin, *intensity, 0, 0, 0, 0, 0, 0, -1, 1, 0,
                  0, 0, 1, radius, *attenuation, 0, -1, -1, 0, 0.005, 1)
        output.extend(struct.pack("<" + WORLD_FORMATS[3], *values))
    return bytes(output)


def append_lumps(source, output, replacements):
    """Preserve existing offsets (including absolute GAME_LUMP offsets)."""
    source, output = Path(source), Path(output)
    inv = inspect(source)
    if inv["version_raw"] != 37 or inv["byte_order"] != "little" or inv["issues"]:
        raise FormatError("writer requires a valid little-endian v37 BSP")
    if any(e["external_files"] for e in inv["lumps"]):
        raise FormatError("writer refuses sidecar-bearing BSPs; use a self-contained compiler output")
    if source.stat().st_size > 256 * 1024 * 1024:
        raise FormatError("writer size limit exceeded")
    if output.exists():
        raise FileExistsError(output)
    data = bytearray(source.read_bytes())
    for index, (version, contents) in replacements.items():
        if not 0 <= index < 128 or len(contents) > 256 * 1024 * 1024:
            raise ValueError("invalid replacement lump")
        data.extend(bytes((-len(data)) % 4))
        offset = len(data) if contents else 0
        data.extend(contents)
        struct.pack_into("<4I", data, 16 + index * 16, offset, len(contents), version, 0)
    with output.open("xb") as stream:
        stream.write(data)


def write_atlas_probe(source, output, plane, rgba, size=64):
    """Wire a uniform controlled plane to lit meshes for shader experiments.

    Every lit vertex samples the centre. This is deliberately NOT an unwrap or
    a bake; it separates shader-plane decoding from spatial atlas packing.
    """
    if plane not in ("sky-a", "sky-b", "rtl-a", "rtl-b", "rtl-c"):
        raise ValueError("unknown probe plane")
    if size < 2 or size > 1024 or size % 2 or len(rgba) != 4 or any(
            not isinstance(c, int) or not 0 <= c <= 255 for c in rgba):
        raise ValueError("invalid probe dimensions or byte colour")
    inv = inspect(source)
    if inv["version_raw"] != 37 or validate(source)["issues"]:
        raise FormatError("probe requires validated v37 BSP")
    r = load_records(source, inv)
    lit = {m[-2] for m in r[80] if m[-1] & 0x600 < 0x400}
    unlit = {m[-2] for m in r[80] if m[-1] & 0x600 >= 0x400}
    if not lit or lit & unlit:
        raise FormatError("probe requires lit geometry with separate lit/unlit material sorts")
    if any(r[82][i][1] != -1 for i in lit):
        raise FormatError("probe refuses already atlas-bound geometry; use unbaked compiler output")
    sorts = bytearray(payload(source, inv, 82)[0])
    for index in lit:
        struct.pack_into("<h", sorts, index * 12 + 2, 0)
    replacements = {82: (0, sorts), 83: (1, struct.pack("<I2H", 1, size, size)),
                    122: (0, struct.pack("<63h", *([-1] * 63)))}
    for pool, stride, version in ((72, 36, 1), (73, 44, 1)):
        data = bytearray(payload(source, inv, pool)[0])
        for offset in range(0, len(data), stride):
            struct.pack_into("<4f", data, offset + 20, 0.5, 0.5, 0, 0)
        replacements[pool] = (version, data)
    pixel = bytes(rgba)
    images = {name: (pixel if name == plane else b"\0" * 4) * (size * size)
              for name in ("sky-a", "sky-b", "rtl-a", "rtl-b")}
    images["rtl-c"] = (pixel if plane == "rtl-c" else b"\0" * 4) * ((size // 2) ** 2)
    replacements[98] = (0, images["sky-a"] + images["sky-b"])
    replacements[105] = (0, images["rtl-a"] + images["rtl-b"] + images["rtl-c"])
    append_lumps(source, output, replacements)
    return {"plane": plane, "rgba_bytes": list(rgba), "size": size,
            "lit_material_sorts": len(lit), "atlas_index": 0,
            "spatial_unwrap": False, "engine_decode_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("inspect")
    read.add_argument("bsp", type=Path)
    read.add_argument("--export", type=Path)
    read.add_argument("--json", type=Path)
    read.add_argument("--embedded", action="store_true", help="ignore default sidecar overrides for comparison")
    write = commands.add_parser("write-lights")
    write.add_argument("bsp", type=Path)
    write.add_argument("lights", type=Path, help="JSON list of explicit point-light parameters")
    write.add_argument("output", type=Path)
    probe = commands.add_parser("write-atlas-probe")
    probe.add_argument("bsp", type=Path)
    probe.add_argument("output", type=Path)
    probe.add_argument("--plane", choices=("sky-a", "sky-b", "rtl-a", "rtl-b", "rtl-c"), required=True)
    probe.add_argument("--rgba", type=int, nargs=4, default=[255, 0, 0, 255])
    probe.add_argument("--size", type=int, default=64)
    args = parser.parse_args()
    if args.command == "inspect":
        report = inspect_lighting(args.bsp, args.export, args.embedded)
        text = json.dumps(report, indent=2) + "\n"
        if args.json:
            with args.json.open("x") as stream:
                stream.write(text)
        else:
            print(text)
    elif args.command == "write-lights":
        lights = json.loads(args.lights.read_text())
        append_lumps(args.bsp, args.output, {54: (3, encode_point_lights(lights)), 55: (3, b"")})
        print(f"Wrote {len(lights)} experimental point lights to {args.output}; engine test required")
    else:
        print(json.dumps(write_atlas_probe(args.bsp, args.output, args.plane, args.rgba, args.size), indent=2))


if __name__ == "__main__":
    main()
