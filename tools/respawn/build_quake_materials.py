#!/usr/bin/env python3
"""Build a Titanfall 2 RPak of world materials for a Quake map's textures.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.

Each Quake texture is replaced by a LibreQuake texture (BSD-3-Clause; id
Software's originals are not used): an exact name match, LibreQuake's renamed
form (+ -> plus_, * -> star_, optional _fbr suffix), or a recorded
same-family substitute. Images become mipped sRGB DDS files. Materials clone
a native Titanfall 2 world material (shader set, uber buffer, depth passes and
colpass) from a decompressed RPak, replacing its albedo and using flat
normal/gloss/spec maps. RePak (r-ex) builds the RPak; its output is checked.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib

from rpak import RPak

# Single-layer world material (albedo/normal/gloss/spec in slots 0-3). Blend
# materials (_bm) also sample a second albedo from slot 23 and a mask from 22.
TEMPLATE = "world/dev/dev_gray_512"
PAK_NAME = "quake_textures"

# Quake textures that are not drawn: (shader name, remap shader body)
TOOLS = {
    "clip": ("tools/toolsplayerclip", "$compileflag nodraw\n $contentflag playerclip"),
    "trigger": ("tools/toolstrigger", "$compileflag nodraw"),
}
SKY = ("tools/toolsskybox", "$compileflag sky\n $compileflag nodraw\n $surfaceflag sky")

# Same-family LibreQuake substitutes for id textures LibreQuake does not ship.
SUBSTITUTES = [
    (r"^\+\dslip$|^slip1$|^slipbotsd$", "plus_0slipbot"),
    (r"^sliptopsd$", "plus_0sliptop"),
    (r"^slipside$", "t_trim1a"),
    (r"^sliplite$|^tlight\d+$", "t_lit01_fbr"),
    (r"^tech01_\d+$", "t_tech01"),
    (r"^tech04_\d+$", "tech04_1"),
    (r"^tech07_\d+$", "t_tech02"),
    (r"^tech09_\d+$", "t_tech03"),
    (r"^tech10_\d+$", "tech10_3"),
    (r"^tech11_\d+$", "t_tech04"),
    (r"^twall1_\d+$", "t_wall1a"),
    (r"^twall2_\d+$", "twall2_3"),
    (r"^twall3_\d+$", "t_wall3a"),
    (r"^twall5_\d+$", "t_wall2a"),
    (r"^sfloor\d+_\d+$", "t_flor1a"),
    (r"^ground1_\d+$", "ground_1"),
    (r"^ecop1_\d+$", "ecop1_4"),
    (r"^basebutn\d*$", "plus_abasebtn"),
    (r"^switch_\d+$", "butmet"),
    (r"^key01_\d+$", "plus_0_gkey"),
    (r"^\+\dplanet$", "plus_0planet_a_fbr"),
]
DEFAULT_SUBSTITUTE = "t_wall1a"


def map_textures(text):
    """Texture names used by brush faces in classic Quake MAP syntax."""
    return sorted(set(re.findall(r"\)\s+(\S+)\s+-?[\d.]+\s+-?[\d.]+\s+-?[\d.]+\s+-?[\d.]+\s+-?[\d.]+", text)))


def material_name(texture):
    """Titanfall material name for a Quake texture."""
    safe = re.sub(r"[^a-z0-9_]", "_", texture.lower().replace("+", "plus").replace("*", "star"))
    return f"world/quake/{safe}"


def resolve(texture, library):
    """Pick a LibreQuake image for a Quake texture: (stem, method)."""
    name = texture.lower()
    renamed = name.replace("+", "plus_").replace("*", "star_")
    for candidate, method in ((name, "exact"), (renamed, "renamed"), (renamed + "_fbr", "renamed")):
        if candidate in library:
            return candidate, method
    for pattern, substitute in SUBSTITUTES:
        if re.match(pattern, name) and substitute in library:
            return substitute, "substitute"
    return DEFAULT_SUBSTITUTE, "default"


def read_png(path):
    """Decode an 8-bit non-interlaced PNG (RGB, RGBA or palette) to RGBA rows."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, palette, alpha = 8, bytearray(), None, b""
    while pos < len(data):
        length, kind = struct.unpack_from(">I4s", data, pos)
        chunk = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"PLTE":
            palette = chunk
        elif kind == b"tRNS":
            alpha = chunk
        elif kind == b"IDAT":
            idat += chunk
    channels = {2: 3, 3: 1, 6: 4}.get(colour)
    if depth != 8 or interlace or channels is None:
        raise ValueError(f"{path}: unsupported PNG (depth {depth}, colour {colour}, interlace {interlace})")
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    previous = bytearray(stride)
    rgba = bytearray()
    for y in range(height):
        kind = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            corner = previous[i - channels] if i >= channels else 0
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                p = left + up - corner
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - corner)
                line[i] = (line[i] + (left if pa <= pb and pa <= pc else up if pb <= pc else corner)) & 255
            elif kind:
                raise ValueError(f"{path}: invalid PNG filter {kind}")
        previous = line
        for x in range(width):
            if channels == 4:
                rgba += line[x * 4:x * 4 + 4]
            elif channels == 3:
                rgba += line[x * 3:x * 3 + 3] + b"\xff"
            else:
                index = line[x]
                rgba += palette[index * 3:index * 3 + 3] + bytes([alpha[index] if index < len(alpha) else 255])
    return width, height, bytes(rgba)


def mip_chain(width, height, rgba, limit=13):
    """Box-filtered mips down to 1x1 (at most `limit` levels)."""
    levels = [(width, height, rgba)]
    while (width > 1 or height > 1) and len(levels) < limit:
        w, h = max(1, width // 2), max(1, height // 2)
        out = bytearray(w * h * 4)
        for y in range(h):
            for x in range(w):
                for c in range(4):
                    total = 0
                    for dy in (0, 1):
                        for dx in (0, 1):
                            sx, sy = min(width - 1, x * 2 + dx), min(height - 1, y * 2 + dy)
                            total += rgba[(sy * width + sx) * 4 + c]
                    out[(y * w + x) * 4 + c] = (total + 2) // 4
        width, height, rgba = w, h, bytes(out)
        levels.append((width, height, rgba))
    return levels


def write_dds(path, levels, srgb):
    """Uncompressed RGBA8 DDS with a DX10 header (DXGI 29 sRGB / 28 linear)."""
    width, height, _ = levels[0]
    header = struct.pack("<4sI", b"DDS ", 124)
    header += struct.pack("<6I", 0x1 | 0x2 | 0x4 | 0x8 | 0x1000 | 0x20000, height, width, width * 4, 0, len(levels))
    header += bytes(44)
    header += struct.pack("<2I4s5I", 32, 0x4, b"DX10", 0, 0, 0, 0, 0)
    header += struct.pack("<5I", 0x1000 | 0x400000 | 0x8, 0, 0, 0, 0)
    header += struct.pack("<5I", 29 if srgb else 28, 3, 0, 1, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + b"".join(level[2] for level in levels))


def solid(colour, size=4):
    return mip_chain(size, size, bytes(colour) * (size * size))


def build(map_text, library_dir, template_pak, repak, output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    library = {}
    for png in sorted(library_dir.rglob("*.png")):
        library.setdefault(png.stem.lower(), png)
    template = RPak(template_pak)
    materials = {name: asset for asset, name in template.materials()}
    if TEMPLATE not in materials or TEMPLATE + "_colpass" not in materials:
        raise ValueError(f"{template_pak} has no {TEMPLATE} material")
    primary_spec, primary_uber = template.material(materials[TEMPLATE])
    colpass_spec, colpass_uber = template.material(materials[TEMPLATE + "_colpass"])

    assets = output / "project/assets"
    files, entries, shaders = [], {}, {}

    def texture(path, levels, srgb):
        write_dds(assets / Path(path).with_suffix(".dds"), levels, srgb)
        files.append({"_type": "txtr", "_path": path, "$disableStreaming": True})

    # Flat maps: the world shader decodes normal RG as RG * 2.867661 - 1.439453
    # (0.502 is flat); gloss red gives roughness 1 - gloss; spec RGB is F0.
    texture("texture/quake/flat_normal.rpak", solid((128, 128, 255, 255)), False)
    texture("texture/quake/matte_gloss.rpak", solid((64, 64, 64, 255)), False)
    texture("texture/quake/dielectric_spec.rpak", solid((10, 10, 10, 255)), False)

    for name in map_textures(map_text):
        key = name.lower()
        if key in TOOLS or key.startswith("sky"):
            shader, body = SKY if key.startswith("sky") else TOOLS[key]
            entries[name] = {"shader": shader, "method": "tool"}
            shaders[shader] = body
            continue
        if key.startswith("*"):
            entries[name] = {"shader": None, "method": "liquid, not compiled"}
            continue
        stem, method = resolve(name, library)
        png = library[stem]
        width, height, rgba = read_png(png)
        world = material_name(name)
        albedo = f"texture/quake/{world.rsplit('/', 1)[1]}_col.rpak"
        texture(albedo, mip_chain(width, height, rgba), True)
        image = output / "images/textures" / (world + ".png")
        image.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(png, image)  # gives remap the texture dimensions for UVs
        primary_path, colpass_path = f"material/{world}_wld.rpak", f"material/{world}_colpass_wld.rpak"
        for path, spec, uber in ((colpass_path, colpass_spec, colpass_uber), (primary_path, primary_spec, primary_uber)):
            new = copy.deepcopy(spec)
            # RePak's JSON uses eight render targets; v12 keeps the first four.
            new["blendStates"] = spec["blendStates"] + ["0x0"] * 4
            new["name"] = world + ("_colpass" if path == colpass_path else "")
            new["width"], new["height"] = width, height
            slots = new["$textures"]
            slots["0"] = albedo
            for slot, flat in (("1", "flat_normal"), ("2", "matte_gloss"), ("3", "dielectric_spec")):
                for index in (slot, str(int(slot) + 23)):  # 24-26 repeat 1-3 in the template
                    if index in slots:
                        slots[index] = f"texture/quake/{flat}.rpak"
            if path == primary_path:
                new["$colpassMaterial"] = colpass_path
            target = assets / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.with_suffix(".json").write_text(json.dumps(new, indent=2), encoding="utf-8")
            target.with_suffix(".uber").write_bytes(uber)
            files.append({"_type": "matl", "_path": path})
        entries[name] = {"shader": world, "method": method, "source": f"{png.parent.name}/{png.name}",
                         "width": width, "height": height}
        shaders[world] = "$shadertype LitBumpGeneric"

    project = output / "project"
    manifest = {"version": 7, "name": PAK_NAME, "keepDevOnly": True, "assetsDir": str(assets),
                "outputDir": str(project / "build"), "compressLevel": 0, "hasDynamicLibrary": False,
                "files": files}
    (project / "build.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with (output / "repak.log").open("wb") as log:
        subprocess.run([str(repak.resolve()), str(project / "build.json")], stdout=log,
                       stderr=subprocess.STDOUT, check=True, cwd=project)
    pak_path = project / "build" / f"{PAK_NAME}.rpak"
    built = RPak(pak_path)
    built_materials = {name: asset["guid"] for asset, name in built.materials()}
    wanted = {e["shader"] for e in entries.values() if e["method"] not in ("tool", "liquid, not compiled")}
    missing = sorted(wanted - set(built_materials))
    if missing:
        raise ValueError(f"RePak output lacks materials: {missing}")
    known = {a["guid"] for a in built.assets} | {a["guid"] for a in template.assets}
    unresolved = set()
    for asset, _ in built.materials():
        spec, uber = built.material(asset)
        if len(uber) != len(primary_uber):
            raise ValueError("unexpected uber buffer size in built material")
        refs = list(spec["$textures"].values()) + [spec[k] for k in (
            "$depthShadowMaterial", "$depthPrepassMaterial", "$depthVSMMaterial", "$colpassMaterial")]
        unresolved |= {r for r in refs if int(r, 16) and int(r, 16) not in known}
    # The shader set lives in common.rpak, which the game always loads.
    report = {
        "pak": str(pak_path), "template": TEMPLATE, "template_pak": str(template_pak),
        "materials": built_materials and {n: f"0x{g:X}" for n, g in sorted(built_materials.items())},
        "textures": entries, "unresolved_references": sorted(unresolved),
        "counts": {m: sum(e["method"] == m for e in entries.values())
                   for m in sorted({e["method"] for e in entries.values()})},
    }
    if unresolved:
        raise ValueError(f"materials reference assets outside the built and template paks: {sorted(unresolved)}")
    (output / "shaders.json").write_text(json.dumps(shaders, indent=2), encoding="utf-8")
    (output / "materials.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path, help="Quake .map whose textures to convert")
    parser.add_argument("--textures", required=True, type=Path, help="LibreQuake texture-wads directory")
    parser.add_argument("--template-pak", required=True, type=Path,
                        help="decompressed mp_coliseum.rpak (e.g. rpak_ddecomp output)")
    parser.add_argument("--repak", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--license", type=Path, help="texture licence to ship with the pak (LibreQuake docs/COPYING)")
    args = parser.parse_args()
    report = build(args.map.read_text(encoding="ascii"), args.textures, args.template_pak, args.repak, args.output)
    if args.license:
        shutil.copyfile(args.license, args.output / "LICENSE-textures.txt")
    print(json.dumps({"pak": report["pak"], "counts": report["counts"], "materials": len(report["materials"])}, indent=2))


if __name__ == "__main__":
    main()
