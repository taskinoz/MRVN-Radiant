#!/usr/bin/env python3
"""Package a compiled Apex v47 BSP for R5Reloaded and optionally install it.

Original implementation, GPL-2.0-or-later. Python 3.10+, standard library only.

The package holds what a native load needs and nothing game-derived:

* ``maps/LEVEL.bsp`` plus all five entity partitions (missing ones are
  written as empty ``ENTITIES02`` partitions, which the engine accepts);
* ``vpk/{english,}client_`` and ``{english,}server_`` archives, because the
  dedicated server mounts the server archive and the client mounts its own;
* ``platform/scripts/levels/LEVEL.rson``, its settings ``.kv`` and a tiny
  server level script that prints a marker and keeps players inside the
  compiled bounds.

``--install`` copies the package into a game directory. It only accepts
``mp_mrvn_`` levels, refuses to replace a file it did not install earlier,
and records every installed path in ``mrvn_installed_LEVEL.json`` so that
``--uninstall`` removes exactly those files.
"""
import argparse
import hashlib
import json
import re
import shutil
import struct
from pathlib import Path

from pack_vpk import pack_files

PARTITIONS = ("env", "fx", "script", "snd", "spawn")
DEFAULT_PAKS = ("common_flowstate_small", "flowstate_all_loot")


def level_name(value):
    if not re.fullmatch(r"mp_mrvn_[a-z0-9_]{1,48}", value):
        raise ValueError("level must look like mp_mrvn_NAME (lowercase)")
    return value


def bsp_bounds(bsp):
    """World model AABB from MODELS lump 0x0E (first 24 bytes of model 0)."""
    with bsp.open("rb") as stream:
        header = stream.read(16 + 128 * 16)
        if header[:4] != b"rBSP" or struct.unpack_from("<H", header, 4)[0] != 47:
            raise ValueError(f"{bsp} is not an Apex rBSP v47")
        offset, length = struct.unpack_from("<II", header, 16 + 14 * 16)
        if length < 24:
            return (-4096.0,) * 3, (4096.0,) * 3
        stream.seek(offset)
        values = struct.unpack("<6f", stream.read(24))
    return values[:3], values[3:]


def level_script(level, mins, maxs, spawn):
    pad = 512
    lo = [m - pad for m in mins]
    hi = [m + pad for m in maxs]
    return f"""global function CodeCallback_MapInit

void function CodeCallback_MapInit()
{{
    print( "MRVN_LEVEL_INIT {level}" )
    thread MRVN_KeepPlayersInBounds()
}}

void function MRVN_KeepPlayersInBounds()
{{
    FlagWait( "EntitiesDidLoad" )
    while ( true )
    {{
        foreach ( entity player in GetPlayerArray() )
        {{
            vector p = player.GetOrigin()
            if ( IsAlive( player ) && ( p.x < {lo[0]:.1f} || p.x > {hi[0]:.1f} || p.y < {lo[1]:.1f} || p.y > {hi[1]:.1f} || p.z < {lo[2]:.1f} || p.z > {hi[2]:.1f} ) )
            {{
                player.SetOrigin( <{spawn[0]:.1f},{spawn[1]:.1f},{spawn[2]:.1f}> )
                print( "MRVN_LEVEL_PLAYER_RESET" )
            }}
        }}
        wait 0.5
    }}
}}
"""


def first_spawn(spawn_ent):
    """Origin of the first info_player_start in a spawn partition."""
    if not spawn_ent.is_file():
        return None
    text = spawn_ent.read_text(errors="replace")
    for block in re.findall(r"\{[^{}]*\}", text):
        if '"info_player_start"' in block:
            match = re.search(r'"origin"\s+"([^"]+)"', block)
            if match:
                values = [float(v) for v in match[1].split()]
                if len(values) == 3:
                    return values
    return None


def build_package(bsp, output, level, paks=DEFAULT_PAKS):
    level = level_name(level)
    bsp = bsp.resolve()
    if output.exists():
        raise FileExistsError(f"{output} already exists; choose a new folder")
    maps = output / "maps"
    maps.mkdir(parents=True)
    source_stem = bsp.stem
    shutil.copyfile(bsp, maps / f"{level}.bsp")
    for extra in sorted(bsp.parent.glob(f"{source_stem}.bsp.*.bsp_lump")):
        shutil.copyfile(extra, maps / extra.name.replace(source_stem, level, 1))
    for part in PARTITIONS:
        source = bsp.with_name(f"{source_stem}_{part}.ent")
        target = maps / f"{level}_{part}.ent"
        if source.is_file():
            shutil.copyfile(source, target)
        else:
            target.write_bytes(b"ENTITIES02 num_models=1\n\0")
    files = {f"maps/{p.name}": p.read_bytes() for p in sorted(maps.iterdir())}
    pack_files(files, output / "vpk", f"client_{level}.bsp.pak000")
    pack_files(files, output / "vpk", f"server_{level}.bsp.pak000")

    mins, maxs = bsp_bounds(maps / f"{level}.bsp")
    spawn = first_spawn(maps / f"{level}_spawn.ent") or [(a + b) / 2 for a, b in zip(mins, maxs)]
    levels = output / "platform/scripts/levels"
    (levels / "settings").mkdir(parents=True)
    script = f"mp/levels/_{level}.nut"
    (levels / f"{level}.rson").write_text(
        f'When: "SERVER"\nScripts:\n[\n {script}\n]\nWhen: "CLIENT"\nScripts:\n[\n]\n'
        'When: "SERVER || CLIENT"\nScripts:\n[\n]\n')
    pak_list = " ".join(f'"{p}" "1"' for p in paks)
    (levels / "settings" / f"{level}.kv").write_text(f'"LevelSet"\n{{\n "PakList" {{ {pak_list} }}\n}}\n')
    vscripts = output / "platform/scripts/vscripts" / script
    vscripts.parent.mkdir(parents=True)
    vscripts.write_text(level_script(level, mins, maxs, spawn))

    manifest = dict(level=level, source_bsp=str(bsp),
                    source_sha256=hashlib.sha256(bsp.read_bytes()).hexdigest(),
                    files=sorted(str(p.relative_to(output)).replace("\\", "/")
                                 for p in output.rglob("*") if p.is_file()))
    (output / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def install(package, game):
    manifest = json.loads((package / "package.json").read_text())
    level = level_name(manifest["level"])
    record = game / f"mrvn_installed_{level}.json"
    previous = set(json.loads(record.read_text())["files"]) if record.is_file() else set()
    installed = []
    for relative in manifest["files"]:
        if level not in relative:
            raise ValueError(f"refusing to install a file without the level name: {relative}")
        target = game / relative
        if target.exists() and relative not in previous:
            raise FileExistsError(f"{target} exists and was not installed by this tool")
    for relative in manifest["files"]:
        target = game / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()  # never write through a hardlink
        shutil.copyfile(package / relative, target)
        installed.append(relative)
    for stale in sorted(previous - set(installed)):
        (game / stale).unlink(missing_ok=True)
    record.write_text(json.dumps(dict(level=level, files=installed), indent=2) + "\n")
    return installed


def uninstall(game, level):
    level = level_name(level)
    record = game / f"mrvn_installed_{level}.json"
    if not record.is_file():
        raise FileNotFoundError(f"no install record for {level}")
    files = json.loads(record.read_text())["files"]
    for relative in files:
        (game / relative).unlink(missing_ok=True)
    record.unlink()
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bsp", type=Path, help="compiled BSP; sibling NAME_*.ent partitions are included")
    parser.add_argument("--level", required=True, help="installed level name, mp_mrvn_*")
    parser.add_argument("--output", type=Path, help="new package folder")
    parser.add_argument("--pak", action="append", help="level PakList entry (repeatable)")
    parser.add_argument("--game", type=Path, help="R5Reloaded folder for --install/--uninstall")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    args = parser.parse_args()
    result = {}
    if args.uninstall:
        result["removed"] = uninstall(args.game, args.level)
    if args.bsp:
        result["package"] = build_package(args.bsp, args.output, args.level, tuple(args.pak or DEFAULT_PAKS))
    if args.install:
        result["installed"] = install(args.output, args.game)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
