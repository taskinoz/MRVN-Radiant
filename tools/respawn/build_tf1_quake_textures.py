#!/usr/bin/env python3
"""Build a textured Titanfall 1 E1M1 addon from existing LibreQuake DDS outputs."""

import json
import struct
import sys
from pathlib import Path

from build_northstar_test_mod import adapt_map


def dds_mips(path):
    data = path.read_bytes()
    if data[:4] != b"DDS ":
        raise ValueError(f"not DDS: {path}")
    width = struct.unpack_from("<I", data, 16)[0]
    height = struct.unpack_from("<I", data, 12)[0]
    mip_count = struct.unpack_from("<I", data, 28)[0]
    levels = []
    position = 148
    for level in range(mip_count):
        mip_width = max(1, width >> level)
        mip_height = max(1, height >> level)
        rgba = data[position:position + mip_width * mip_height * 4]
        position += mip_width * mip_height * 4
        if len(rgba) != mip_width * mip_height * 4:
            raise ValueError(f"truncated DDS: {path}")
        levels.append((mip_width, mip_height, rgba))
    return width, height, levels


def write_vtf(path, width, height, levels):
    # VTF 7.2, BGRA8888, minor 2 layout: small mip levels are stored first.
    ordered = list(reversed(levels))
    payload = b"".join(
        b"".join(bytes((rgba[i + 2], rgba[i + 1], rgba[i], rgba[i + 3]))
                 for i in range(0, len(rgba), 4))
        for _, _, rgba in ordered
    )
    header = bytearray(80)
    header[:4] = b"VTF\0"
    struct.pack_into("<3I", header, 4, 7, 2, 80)
    struct.pack_into("<HHIH", header, 16, width, height, 0, 1)
    struct.pack_into("<iBiBB", header, 52, 12, len(ordered), 12, 0, 0)
    struct.pack_into("<H", header, 60, 1)
    path.write_bytes(bytes(header) + payload)


def main():
    if len(sys.argv) != 5:
        raise SystemExit(
            "usage: build_tf1_quake_textures.py ORIGINAL_MAP MATERIALS_JSON DDS_DIR OUTPUT")
    original = Path(sys.argv[1]).resolve()
    materials = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    dds_dir = Path(sys.argv[3]).resolve()
    output = Path(sys.argv[4]).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "assets" / "shaders").mkdir(parents=True)
    (output / "assets" / "materials" / "world" / "quake").mkdir(parents=True)
    geometry, brushes, spawns = adapt_map(
        original.read_text(encoding="ascii"),
        materials=materials["textures"],
        sun=True,
    )
    maps = output / "maps"
    maps.mkdir()
    (maps / "mp_tf1_e1m1.map").write_text(geometry, encoding="ascii")

    textures = []
    for dds in sorted(dds_dir.glob("*_col.dds")):
        width, height, levels = dds_mips(dds)
        name = dds.stem[:-4]
        material_dir = output / "assets" / "materials" / "world" / "quake"
        write_vtf(material_dir / f"{name}.vtf", width, height, levels)
        (material_dir / f"{name}.vmt").write_text(
            'LightmappedGeneric\n{\n'
            f' "$basetexture" "world/quake/{name}"\n'
            '}\n',
            encoding="ascii",
        )
        textures.append(name)

    shader = "".join(
        f"textures/world/quake/{name}\n{{\n $shadertype LitBumpGeneric\n}}\n"
        for name in textures
    )
    shader += (
        "textures/compat/water\n{\n $shadertype Water\n $contentflag water\n}\n"
        "textures/compat/slime\n{\n $shadertype Water\n $contentflag water\n}\n"
    )
    (output / "assets" / "shaders" / "e1m1.shader").write_text(shader, encoding="ascii")
    print(json.dumps({"brushes": brushes, "spawns": spawns, "textures": len(textures)}))


if __name__ == "__main__":
    main()
