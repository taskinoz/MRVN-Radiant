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
import stbsp
from validate_records import validate

LEVEL = "mp_quake_e1m1"
# The menu stage sits far above the play space, at retail Coliseum's own anchor:
# at z=0 next to E1M1, menu pilot/Titan shadows appeared on gameplay floors.
MENU_SCENE = (-11776.0, 11856.0, 12736.0)
# Retail Coliseum's menu_scene_ref; its menu rig is laid out around this point
# with the same anchor orientation as ours (scene yaw -90, camera 256 units -Y).
COLISEUM_MENU_SCENE = (-11776.0, 11856.0, 12736.0)
MENU_RIG_KEYS_DROPPED = ("link_guid", "link_to_guid_0", "framerate")


def box_volume(half):
    keys = {}
    for i, (normal, d) in enumerate((("-1 0 0", half), ("1 0 0", half), ("0 -1 0", half),
                                     ("0 1 0", half), ("0 0 -1", half), ("0 0 1", half))):
        keys[f"*trigger_brush_0_plane_{i}"] = f"{normal} {d}"
    keys["*trigger_bounds_mins"] = f"{-half} {-half} {-half}"
    keys["*trigger_bounds_maxs"] = f"{half} {half} {half}"
    return keys


SKY_VISTA = "models/vistas/grave_se.mdl"


def sky_rig(env_text):
    """Coliseum's gameplay 3D skybox: its skybox_cam_level sky_camera and, at the
    camera origin, the grave_se vista as a non-solid, shadowless static prop
    (as retail places it). The MDL is staged from the user's Coliseum VPK."""
    for block in re.findall(r"\{[^{}]*\}", env_text):
        keys = dict(re.findall(r'"([^"]+)" "([^"]*)"', block))
        if keys.get("classname") == "sky_camera" and keys.get("targetname") == "skybox_cam_level":
            vista = {"classname": "prop_static", "model": SKY_VISTA, "origin": keys["origin"],
                     "angles": "0 90 0", "solid": "0", "flags": "84", "_cullradius": "16384"}
            return [keys, vista]
    raise ValueError("sky source has no skybox_cam_level sky_camera")


def box_brush(lo, hi, material):
    """Axial brush in classic MAP syntax (face winding as remap expects)."""
    (lx, ly, lz), (hx, hy, hz) = lo, hi
    faces = [((hx, hy, lz), (lx, hy, lz), (lx, ly, lz)), ((lx, ly, hz), (lx, hy, hz), (hx, hy, hz)),
             ((lx, ly, hz), (hx, ly, hz), (hx, ly, lz)), ((hx, ly, hz), (hx, hy, hz), (hx, hy, lz)),
             ((hx, hy, hz), (lx, hy, hz), (lx, hy, lz)), ((lx, hy, hz), (lx, ly, hz), (lx, ly, lz))]
    return "{\n" + "\n".join(" ".join("( %g %g %g )" % p for p in f) + f" {material} 0 0 0 1 1 0 0 0"
                             for f in faces) + "\n}"


def enclosure(lo, hi, material, margin=512, thickness=64):
    """Closed shell of sky brushes around the map, as retail maps enclose
    themselves in a TOOLS\\TOOLSSKYBOX box: the camera never sees the void,
    hitscan traces into the void hit it, and leaks are sealed."""
    lo = [v - margin for v in lo]
    hi = [v + margin for v in hi]
    t = thickness
    return [
        box_brush((lo[0] - t, lo[1] - t, lo[2] - t), (hi[0] + t, hi[1] + t, lo[2]), material),  # floor
        box_brush((lo[0] - t, lo[1] - t, hi[2]), (hi[0] + t, hi[1] + t, hi[2] + t), material),  # ceiling
        box_brush((lo[0] - t, lo[1] - t, lo[2]), (lo[0], hi[1] + t, hi[2]), material),          # -x
        box_brush((hi[0], lo[1] - t, lo[2]), (hi[0] + t, hi[1] + t, hi[2]), material),          # +x
        box_brush((lo[0], lo[1] - t, lo[2]), (hi[0], lo[1], hi[2]), material),                  # -y
        box_brush((lo[0], hi[1], lo[2]), (hi[0], hi[1] + t, hi[2]), material),                  # +y
    ]


def menu_rig(env_text=None):
    """Lighting for the pilot/Titan menu stage at MENU_SCENE: light environment 1,
    its light_environment_volume and spotlights. With a retail Coliseum _env.ent,
    its menu rig is translated onto MENU_SCENE; otherwise a small authored rig."""
    def at(x, y, z):
        return f"{MENU_SCENE[0] + x:g} {MENU_SCENE[1] + y:g} {MENU_SCENE[2] + z:g}"
    if env_text is None:
        return [
            {"classname": "light_environment", "lightEnvironmentIndex": "*1", "origin": at(0, 0, 256),
             "pitch": "-51", "angles": "51 122 0", "_light": "255 255 255 765", "_ambient": "255 255 255 51",
             "targetname": "light_environment_1"},
            {"classname": "light_environment_volume", "lightEnvironmentIndex": "*1", "origin": at(0, 0, 0),
             **box_volume(3072)},
            # Key light from the camera's left, rim light from behind the stage.
            {"classname": "light_spot", "origin": at(-140, -220, 200), "pitch": "-35", "angles": "35 58 0",
             "_light": "255 236 214 255", "_zero_percent_distance": "500", "_fifty_percent_distance": "350",
             "_cone": "50", "_inner_cone": "30", "realtime": "1", "shadow": "0"},
            {"classname": "light_spot", "origin": at(60, 220, 180), "pitch": "-30", "angles": "30 -105 0",
             "_light": "160 210 255 200", "_zero_percent_distance": "450", "_fifty_percent_distance": "300",
             "_cone": "45", "_inner_cone": "25", "realtime": "1", "shadow": "0"},
        ]
    offset = [MENU_SCENE[i] - COLISEUM_MENU_SCENE[i] for i in range(3)]
    rig = []
    for block in re.findall(r"\{[^{}]*\}", env_text):
        keys = dict(re.findall(r'"([^"]+)" "([^"]*)"', block))
        origin = [float(v) for v in keys.get("origin", "0 0 0").split()]
        near = all(abs(origin[i] - COLISEUM_MENU_SCENE[i]) < 4096 for i in range(3))
        if not near or not keys.get("classname", "").startswith("light"):
            continue
        keys = {k: v for k, v in keys.items() if k not in MENU_RIG_KEYS_DROPPED}
        keys["origin"] = " ".join(f"{origin[i] + offset[i]:g}" for i in range(3))
        rig.append(keys)
    if not any(k.get("classname") == "light_environment_volume" for k in rig):
        raise ValueError("menu rig source has no light_environment_volume near Coliseum's menu stage")
    return rig
MOD = "MRVN.QuakeE1M1Test"
MATERIAL = "world/concrete/concrete_plates_plain_wet_bm"
WALL_MATERIAL = "world/boomtown/boomtown_wall_gapconcrete_01"


def adapt_map(text, stats=None, materials=None, sun=False, menu=None, sky=None, shell=None):
    """Handle original line-oriented Quake MAP syntax, rejecting other syntax.

    With `materials` (build_quake_materials textures entries) each face keeps
    its own converted material; otherwise floors and walls get two Coliseum
    materials. Light entities pass through so remap can bake them."""
    depth, brushes, current, spawns, keys, lights = 0, [], [], [], {}, []
    lo, hi = [1e30] * 3, [-1e30] * 3
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
                if classname.startswith("light") and "origin" in keys:
                    lights.append(dict(keys))
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
            for point in points:
                lo = [min(a, b) for a, b in zip(lo, point)]
                hi = [max(a, b) for a, b in zip(hi, point)]
            a = [points[0][i] - points[1][i] for i in range(3)]
            b = [points[2][i] - points[1][i] for i in range(3)]
            normal_z = a[0] * b[1] - a[1] * b[0]
            if materials is not None:
                material = (materials.get(match[2]) or {}).get("shader") or WALL_MATERIAL
            else:
                material = MATERIAL if normal_z > 0 else WALL_MATERIAL
            current.append(f"{match[1]} {material} {match[3]}")
        else:
            raise ValueError("content outside entity")
    if depth or not brushes or not spawns:
        raise ValueError("incomplete MAP or missing geometry/spawns")
    if stats is not None:
        stats["discarded_brushes"] = discarded
    # Door openings remain open; trigger/liquid volumes never become solid.
    if shell:
        brushes = brushes + enclosure(lo, hi, shell)
    output = '{\n"classname" "worldspawn"\n'
    output += "\n".join(brushes) + "\n}\n"
    for light in lights:
        output += "{\n" + "".join(f'"{k}" "{v}"\n' for k, v in light.items()) + "}\n"
    if sun:
        output += ('{\n"classname" "light_environment"\n"lightEnvironmentIndex" "*0"\n"origin" "0 0 0"\n'
                   '"pitch" "-60"\n"angles" "60 45 0"\n"_light" "255 240 220 500"\n'
                   '"_ambient" "150 170 255 80"\n"targetname" "light_environment_1"\n}\n')
    for keys in (menu or []) + (sky or []):
        output += "{\n" + "".join(f'"{k}" "{v}"\n' for k, v in keys.items()) + "}\n"
    if stats is not None:
        stats["light_entities"] = len(lights) + int(sun)
        stats["menu_rig_entities"] = len(menu or [])
    for origin, yaw in spawns:
        for team in (2, 3):
            for suffix in ("", "_start"):
                output += ('{\n"classname" "info_spawnpoint_human' + suffix + '"\n'
                           f'"origin" "{origin}"\n"angles" "0 {yaw} 0"\n'
                           f'"teamnumber" "{team}"\n"ignoreGamemode" "1"\n'
                           '"gamemode_tdm" "1"\n}\n')
    # Client menu scenes instantiate their own environment model. Keep the
    # anchors remote from gameplay, rather than showing that model in corridors.
    for name, origin, yaw in (("menu_scene_ref", "{:g} {:g} {:g}".format(*MENU_SCENE), -90),
                              ("menu_camera_target", "{:g} {:g} {:g}".format(
                                  MENU_SCENE[0], MENU_SCENE[1] - 256, MENU_SCENE[2] + 40), 90)):
        output += ('{\n"classname" "info_target_clientside"\n'
                   f'"script_name" "{name}"\n"origin" "{origin}"\n'
                   f'"angles" "0 {yaw} 0"\n"scale" "1"\n}}\n')
    return output, len(brushes), len(spawns) * 4


def bsp_lumps(path, *indices):
    data = path.read_bytes()
    out = []
    for index in indices:
        offset, length, _, _ = struct.unpack_from("<4I", data, 16 + index * 16)
        out.append(data[offset:offset + length])
    return out


def bsp_material_names(path):
    """Material names in TEXTURE_DATA, with forward slashes."""
    textures, strings, table = bsp_lumps(path, 0x02, 0x2B, 0x2C)
    offsets = [v[0] for v in struct.iter_unpack("<I", table)]
    names = set()
    for record in struct.iter_unpack("<3f6i", textures):
        start = offsets[record[3]]
        names.add(strings[start:strings.index(0, start)].decode("ascii").replace("\\", "/"))
    return sorted(names)


def bsp_bounds(path):
    (vertices,) = bsp_lumps(path, 0x03)
    xs = [v[0] for v in struct.iter_unpack("<3f", vertices)]
    ys = [v[1] for v in struct.iter_unpack("<3f", vertices)]
    return (min(xs), min(ys)), (max(xs), max(ys))


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
    parser.add_argument("--materials", type=Path,
                        help="build_quake_materials output; keeps each Quake texture as its own material")
    parser.add_argument("--sun", action="store_true", help="add a light_environment (sun and sky ambient)")
    parser.add_argument("--no-enclosure", action="store_true",
                        help="do not wrap the map in a sky-brush shell (retail maps are enclosed)")
    parser.add_argument("--sky", type=Path,
                        help="retail mp_coliseum_env.ent: add its 3D skybox camera and grave_se vista "
                             "(the model is extracted from --sky-vpk)")
    parser.add_argument("--sky-vpk", type=Path,
                        default=Path("C:/Games/Titanfall2/vpk/englishclient_mp_coliseum.bsp.pak000_dir.vpk"))
    parser.add_argument("--menu-rig", type=Path,
                        help="retail mp_coliseum_env.ent whose menu-stage lights are moved to this map's menu stage; "
                             "without it a small authored rig is used")
    args = parser.parse_args()
    materials = None
    if args.materials:
        materials = json.loads((args.materials / "materials.json").read_text(encoding="utf-8"))
    original = args.map.read_text(encoding="ascii")
    license_bytes = args.copying.read_bytes()
    conversion = {}
    menu = menu_rig(args.menu_rig.read_text(encoding="latin-1") if args.menu_rig else None)
    sky = sky_rig(args.sky.read_text(encoding="latin-1")) if args.sky else None
    shell = None
    if materials and not args.no_enclosure:
        shell = next((e["shader"] for n, e in materials["textures"].items()
                      if n.lower().startswith("sky") and e.get("shader")), None)
    geometry, brush_count, spawn_count = adapt_map(
        original, conversion, materials["textures"] if materials else None, args.sun, menu, sky, shell)
    conversion["enclosure"] = shell or "none"
    conversion["menu_rig"] = str(args.menu_rig) if args.menu_rig else "authored"
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    work = root / "compile"
    shaders = work / "assets/shaders"
    shaders.mkdir(parents=True)
    shader_bodies = {name: "$shadertype LitBumpGeneric" for name in (MATERIAL, WALL_MATERIAL)}
    if materials:
        shader_bodies.update(json.loads((args.materials / "shaders.json").read_text(encoding="utf-8")))
        # Texture images give remap the dimensions it needs for UV scale.
        shutil.copytree(args.materials / "images/textures", work / "assets/textures")
    (shaders / "test.shader").write_text("\n".join(
        f"textures/{name}\n{{\n {body}\n}}\n" for name, body in shader_bodies.items()), encoding="ascii")
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
        "Name": MOD, "Description": "Experimental E1M1 compiler test with baked lighting and LibreQuake textures; load mp_quake_e1m1 locally.",
        "Version": "0.3.0", "LoadPriority": 100, "RequiredOnClient": True,
        "Scripts": [{"Path": f"mp/levels/{LEVEL}.nut",
                     "RunOn": f"SERVER && MP && MAP_{LEVEL}"}],
    }, indent=2) + "\n")
    level_script = mod / f"mod/scripts/vscripts/mp/levels/{LEVEL}.nut"
    level_script.parent.mkdir(parents=True)
    level_script.write_text('global function CodeCallback_MapInit\n\nvoid function CodeCallback_MapInit()\n{\n'
                            '\tClassicMP_SetLevelIntro( ClassicMP_DefaultNoIntro_Setup, ClassicMP_DefaultNoIntro_GetLength() )\n'
                            '\tClassicMP_ForceDisableEpilogue( true )\n'
                            '\t// No navmesh or Titan drop space: replacement Titans would fail to find a\n'
                            '\t// spawn point (_replacement_titans_drop.gnut, empty array).\n'
                            '\tRiff_ForceTitanAvailability( eTitanAvailability.Never )\n'
                            '\tprint( "MRVN E1M1 experimental geometry test loaded" )\n}\n')
    cfg = mod / "mod/cfg/mrvn_quake_e1m1.cfg"
    cfg.parent.mkdir(parents=True)
    cfg.write_text('sv_cheats 1\nmp_gamemode tdm\nmap mp_quake_e1m1\n')
    (mod / "paks").mkdir()
    pak_config = {"Aliases": {
        f"{LEVEL}.rpak": "mp_coliseum.rpak",
        f"{LEVEL}_loadscreen.rpak": "mp_coliseum_loadscreen.rpak",
    }}
    files = {f"maps/{bsp.name}": bsp.read_bytes()}
    if materials:
        pak = Path(materials["pak"])
        shutil.copyfile(pak, mod / "paks" / pak.name)
        # Loaded after the aliased Coliseum pak, whose shaders and depth passes it uses.
        pak_config["Postload"] = {pak.name: "mp_coliseum.rpak"}
        catalogue = work / f"{LEVEL}.stbsp"
        names = bsp_material_names(bsp)
        guids = {name: int(guid, 16) for name, guid in materials["materials"].items()}
        mins, maxs = bsp_bounds(bsp)
        stbsp.write(catalogue, [(n, guids[n]) for n in names if n in guids], mins, maxs)
        if len(stbsp.read(catalogue)["materials"]) != sum(n in guids for n in names):
            raise ValueError("STBSP round trip lost materials")
        files[f"maps/{catalogue.name}"] = catalogue.read_bytes()
        conversion["textures"] = materials["counts"]
        conversion["stbsp_materials"] = sum(n in guids for n in names)
        licence = args.materials / "LICENSE-textures.txt"
        if licence.exists():
            shutil.copyfile(licence, mod / "LICENSE-textures.txt")
        shutil.copyfile(args.materials / "materials.json", mod / "materials.json")
    (mod / "paks/rpak.json").write_text(json.dumps(pak_config, indent=2) + "\n")
    for partition in ("env", "fx", "script", "snd", "spawn"):
        path = work / f"{LEVEL}_{partition}.ent"
        files[f"maps/{path.name}"] = path.read_bytes() if path.exists() else b"ENTITIES01\n\x00"
    # Northstar RefreshMapList discovers mod/maps/*.bsp, but does not inspect
    # mod VPKs. Keep identical loose members for discovery and filesystem access.
    if sky:
        # Aliasing Coliseum's RPak supplies the vista's GPU assets but does not
        # mount Coliseum's VPK, so the MDL itself ships loose with the mod.
        vista = subprocess.run([str(args.tf2vpk.resolve()), "get", str(args.sky_vpk), SKY_VISTA],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        if not vista.startswith(b"IDST"):
            raise ValueError(f"{SKY_VISTA} from {args.sky_vpk} is not an MDL")
        (mod / "mod" / SKY_VISTA).parent.mkdir(parents=True, exist_ok=True)
        (mod / "mod" / SKY_VISTA).write_bytes(vista)
        conversion["sky"] = {"camera": sky[0]["origin"], "vista": SKY_VISTA, "source": str(args.sky_vpk)}
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
    shutil.copyfile(documentation.with_name("RESPAWN_SOURCES.md"), mod / "SOURCES.md")
    for name in ("build_northstar_test_mod.py", "pack_vpk.py", "validate_records.py", "inspect_bsp.py"):
        shutil.copyfile(Path(__file__).with_name(name), source_bundle / name)
    shutil.copyfile(shaders / "test.shader", source_bundle / "test.shader")
    report.update({"brushes_adapted": brush_count, "pilot_spawn_entities": spawn_count,
                   "conversion": conversion,
                   "baked_lighting": not conversion["removed_placeholder_lighting_bytes"],
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
