#!/usr/bin/env python3
"""Build an experimental Quake E1M1 Northstar geometry-test mod.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Requires the GPL Quake map source and its COPYING file; see documentation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

from pack_vpk import pack_files
from validate_records import validate

LEVEL = "mp_quake_e1m1"
MOD = "MRVN.QuakeE1M1Test"
MATERIAL = "world/concrete/concrete_plates_plain_wet_bm"
WALL_MATERIAL = "world/boomtown/boomtown_wall_gapconcrete_01"


def adapt_map(text, stats=None):
    """Handle original line-oriented Quake MAP syntax, rejecting other syntax."""
    depth, brushes, current, spawns, keys = 0, [], [], [], {}
    entity_brushes, discarded = [], {}
    liquid = False
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line == "{":
            depth += 1
            if depth == 1:
                keys = {}
                entity_brushes = []
            elif depth == 2:
                current = ["{"]
                liquid = False
            else:
                raise ValueError("unsupported nested MAP structure")
        elif line == "}":
            if depth == 2:
                entity_brushes.append(("\n".join(current + ["}"]), liquid))
            elif depth == 1:
                classname = keys.get("classname", "")
                # Only static wall geometry is safe to flatten into worldspawn.
                for brush, is_liquid in entity_brushes:
                    if classname in ("worldspawn", "func_wall") and not is_liquid:
                        brushes.append(brush)
                    else:
                        reason = "liquid" if is_liquid else classname
                        discarded[reason] = discarded.get(reason, 0) + 1
                if classname in ("info_player_start", "info_player_deathmatch"):
                    spawns.append((keys["origin"], keys.get("angle", "0")))
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced MAP braces")
        elif depth == 1:
            match = re.fullmatch(r'"([^"\n]+)"\s+"([^"\n]*)"', line)
            if not match:
                raise ValueError(f"unsupported entity key: {line}")
            keys[match[1]] = match[2]
        elif depth == 2:
            match = re.fullmatch(r'(\([^()]+\)\s+\([^()]+\)\s+\([^()]+\))\s+(\S+)\s+(.+)', line)
            if not match:
                raise ValueError(f"unsupported brush face: {line}")
            liquid |= match[2].startswith("*")
            points = [tuple(map(float, p.split())) for p in re.findall(r'\(([^()]+)\)', match[1])]
            a = [points[0][i] - points[1][i] for i in range(3)]
            b = [points[2][i] - points[1][i] for i in range(3)]
            normal_z = a[0] * b[1] - a[1] * b[0]
            material = MATERIAL if normal_z > 0 else WALL_MATERIAL
            current.append(f"{match[1]} {material} {match[3]}")
        else:
            raise ValueError("content outside entity")
    if depth or not brushes or not spawns:
        raise ValueError("incomplete MAP or missing geometry/spawns")
    if stats is not None:
        stats["discarded_brushes"] = discarded
    # Door openings remain open; trigger/liquid volumes never become solid.
    output = '{\n"classname" "worldspawn"\n'
    output += "\n".join(brushes) + "\n}\n"
    for origin, yaw in spawns:
        for team in (2, 3):
            for suffix in ("", "_start"):
                output += ('{\n"classname" "info_spawnpoint_human' + suffix + '"\n'
                           f'"origin" "{origin}"\n"angles" "0 {yaw} 0"\n'
                           f'"teamnumber" "{team}"\n"ignoreGamemode" "1"\n'
                           '"gamemode_tdm" "1"\n}\n')
    # Client menu scenes instantiate their own environment model. Keep the
    # anchors remote from gameplay, rather than showing that model in corridors.
    for name, origin, yaw in (("menu_scene_ref", "8192 8192 0", -90),
                              ("menu_camera_target", "8192 7936 40", 90)):
        output += ('{\n"classname" "info_target_clientside"\n'
                   f'"script_name" "{name}"\n"origin" "{origin}"\n'
                   f'"angles" "0 {yaw} 0"\n"scale" "1"\n}}\n')
    return output, len(brushes), len(spawns) * 4


def remove_foreign_lighting(path):
    """Remove hard-coded unrelated-map world lights/CSM; no bake is claimed.

    Maps baked by remap (they carry RTL data, lump 0x69) keep their lights:
    their lightmaps and probes reference those world lights."""
    data = bytearray(path.read_bytes())
    if data[:8] != b"rBSP%\0\0\0":
        raise ValueError("expected Titanfall 2 v37 BSP")
    if struct.unpack_from("<4I", data, 16 + 0x69 * 16)[1]:
        return {}
    removed = {}
    for index in (54, 99, 100):
        header = 16 + index * 16
        offset, length, version, fourcc = struct.unpack_from("<4I", data, header)
        removed[str(index)] = length
        struct.pack_into("<4I", data, header, 0, 0, version, fourcc)
    path.write_bytes(data)
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, type=Path)
    parser.add_argument("--copying", required=True, type=Path)
    parser.add_argument("--remap", required=True, type=Path)
    parser.add_argument("--tf2vpk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    original = args.map.read_text(encoding="ascii")
    license_bytes = args.copying.read_bytes()
    conversion = {}
    geometry, brush_count, spawn_count = adapt_map(original, conversion)
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    work = root / "compile"
    shaders = work / "assets/shaders"
    shaders.mkdir(parents=True)
    (shaders / "test.shader").write_text("\n".join(
        f"textures/{name}\n{{\n $shadertype LitBumpGeneric\n}}\n"
        for name in (MATERIAL, WALL_MATERIAL)), encoding="ascii")
    source = work / (LEVEL + ".map")
    source.write_text(geometry, encoding="ascii")
    with (root / "build.log").open("wb") as log:
        subprocess.run([str(args.remap.resolve()), "-game", "titanfall2", "-fs_basepath",
                        str(work), "-bsp", str(source)], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    bsp = source.with_suffix(".bsp")
    conversion["removed_placeholder_lighting_bytes"] = remove_foreign_lighting(bsp)
    report = validate(bsp)
    if report["issues"]:
        raise ValueError(report["issues"])
    mod = root / MOD
    mod.mkdir()
    (mod / "mod.json").write_text(json.dumps({
        "Name": MOD, "Description": "Experimental E1M1 compiler geometry test; load mp_quake_e1m1 locally.",
        "Version": "0.2.1", "LoadPriority": 100, "RequiredOnClient": True,
        "Scripts": [{"Path": f"mp/levels/{LEVEL}.nut",
                     "RunOn": f"SERVER && MP && MAP_{LEVEL}"}],
    }, indent=2) + "\n")
    level_script = mod / f"mod/scripts/vscripts/mp/levels/{LEVEL}.nut"
    level_script.parent.mkdir(parents=True)
    level_script.write_text('global function CodeCallback_MapInit\n\nvoid function CodeCallback_MapInit()\n{\n'
                            '\tClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )\n'
                            '\tClassicMP_ForceDisableEpilogue( true )\n'
                            '\tprint( "MRVN E1M1 experimental geometry test loaded" )\n}\n')
    cfg = mod / "mod/cfg/mrvn_quake_e1m1.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('sv_cheats 1\nmp_gamemode tdm\nmap mp_quake_e1m1\n')
    (mod / "paks").mkdir()
    (mod / "paks/rpak.json").write_text(json.dumps({"Aliases": {
        f"{LEVEL}.rpak": "mp_coliseum.rpak",
        f"{LEVEL}_loadscreen.rpak": "mp_coliseum_loadscreen.rpak",
    }}, indent=2) + "\n")
    files = {f"maps/{bsp.name}": bsp.read_bytes()}
    for partition in ("env", "fx", "script", "snd", "spawn"):
        path = work / f"{LEVEL}_{partition}.ent"
        files[f"maps/{path.name}"] = path.read_bytes() if path.exists() else b"ENTITIES01\n\x00"
    # Northstar RefreshMapList discovers mod/maps/*.bsp, but does not inspect
    # mod VPKs. Keep identical loose members for discovery and filesystem access.
    for path, payload in files.items():
        loose = mod / "mod" / path
        loose.parent.mkdir(parents=True, exist_ok=True)
        loose.write_bytes(payload)
    directory, _ = pack_files(files, mod / "vpk", f"client_{LEVEL}.bsp.pak000")
    tool = str(args.tf2vpk.resolve())
    with (root / "vpk-verification.log").open("wb") as log:
        subprocess.run([tool, "list", str(directory), "-t", "-l"], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
    for path, payload in files.items():
        actual = subprocess.run([tool, "get", str(directory), path], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=True).stdout
        if actual != payload:
            raise ValueError(f"independent VPK round-trip failed: {path}")
        if (mod / "mod" / path).read_bytes() != actual:
            raise ValueError(f"loose/VPK members differ: {path}")
    source_bundle = mod / "source"
    source_bundle.mkdir()
    (source_bundle / "e1m1-original.map").write_text(original, encoding="ascii")
    shutil.copyfile(source, source_bundle / source.name)
    (mod / "COPYING").write_bytes(license_bytes)
    documentation = Path(__file__).resolve().parents[2] / "docs/RESPAWN_NORTHSTAR_TEST.md"
    shutil.copyfile(documentation, mod / "README.md")
    shutil.copyfile(documentation.with_name("RESPAWN_SURFACE_CRASH.md"), mod / "RESPAWN_SURFACE_CRASH.md")
    shutil.copyfile(documentation.with_name("RESPAWN_SOURCES.md"), mod / "SOURCES.md")
    for name in ("build_northstar_test_mod.py", "pack_vpk.py", "validate_records.py", "inspect_bsp.py"):
        shutil.copyfile(Path(__file__).with_name(name), source_bundle / name)
    shutil.copyfile(shaders / "test.shader", source_bundle / "test.shader")
    report.update({"brushes_adapted": brush_count, "pilot_spawn_entities": spawn_count,
                   "conversion": conversion, "baked_lighting": False,
                   "level": LEVEL, "ingame_tested": False,
                   "vpk_round_trip": "all members byte-identical via pg9182/tf2vpk",
                   "files": {p: {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}
                             for p, b in files.items()}})
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(root / "verification.json", mod / "verification.json")
    with zipfile.ZipFile(root / (MOD + ".zip"), "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(mod.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(root))
    print(json.dumps({"mod": str(mod), "zip": str(root / (MOD + ".zip")),
                      "brushes": brush_count, "spawns": spawn_count}, indent=2))


if __name__ == "__main__":
    main()
