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
    (root / "results.json").write_text(json.dumps(reports, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
