#!/usr/bin/env python3
"""Compile Apex fixture maps and check them in a native R5Reloaded (S3) game.

Original implementation, GPL-2.0-or-later. Python 3.10+, standard library only.

The fixture is a dev-textured room with a block, a sloped ramp, a trigger and
lights, plus optional static props. Each check compares an engine trace with
geometry computed from the fixture itself, so no game data is needed to know
the expected answer. Steps:

1. write the fixture .map and compile it with ``--remap``;
2. package and install it with stage_r5_map.py (``mp_mrvn_regress_*`` only);
3. through a running r5_harness.py controller, load the level, run line and
   hull traces and entity queries, and write a JSON report;
4. uninstall the level again.

    python tools/respawn/r5_harness.py --game R5R --state-dir .local/h &
    python tools/respawn/apex_native_regression.py --remap install/Release/remap.exe \\
        --game R5R --connection .local/h/connection.json --work-dir .local/apex-regress

``--assets`` adds a folder (with shaders/ and models/) to the compile; with an
editor copy of ``mdl/containers/barrel.rmdl`` the fixture also places three
barrels and checks their collision (see cast_to_obj.py).
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r5_harnessctl import call  # noqa: E402
import stage_r5_map  # noqa: E402

DEV = "world/dev/dev_gray_512"
TRIGGER = "tools/toolstrigger"
BARREL = "mdl/containers/barrel.rmdl"
# Same as the MRVN resource pack: triggers are nodraw; the engine reads their
# collision from the entity's serialized *coll keys.
TOOLS_SHADER = """textures/tools/toolstrigger
{
    $compileflag nodraw
}
"""


def face(a, b, c, material):
    """One brush side through a, b, c (Radiant order: normal = (c-a) x (b-a))."""
    return f"( {a[0]} {a[1]} {a[2]} ) ( {b[0]} {b[1]} {b[2]} ) ( {c[0]} {c[1]} {c[2]} ) {material} 0 0 0 0.5 0.5 0 0 0"


def box(x0, y0, z0, x1, y1, z1, material=DEV):
    sides = [((x0, 0, 0), (x0, 1, 0), (x0, 0, 1)), ((x1, 0, 0), (x1, 0, 1), (x1, 1, 0)),
             ((0, y0, 0), (0, y0, 1), (1, y0, 0)), ((0, y1, 0), (1, y1, 0), (0, y1, 1)),
             ((0, 0, z0), (1, 0, z0), (0, 1, z0)), ((0, 0, z1), (0, 1, z1), (1, 0, z1))]
    return "{\n" + "\n".join(face(*s, material) for s in sides) + "\n}"


def ramp(x0, y0, x1, y1, height, material=DEV):
    """Wedge rising along +x from z=0 at x0 to z=height at x1."""
    sides = [((x0, y0, 0), (x1, y0, 0), (x0, y1, 0)), ((x1, y0, 0), (x1, y0, height), (x1, y1, 0)),
             ((x0, y0, 0), (x0, y0, height), (x1, y0, 0)), ((x0, y1, 0), (x1, y1, 0), (x0, y1, height)),
             ((x0, y0, 0), (x0, y1, 0), (x1, y0, height))]
    return "{\n" + "\n".join(face(*s, material) for s in sides) + "\n}"


def entity(classname, body="", **keys):
    lines = [f'"classname" "{classname}"'] + [f'"{k}" "{v}"' for k, v in keys.items()]
    return "{\n" + "\n".join(lines) + ("\n" + body if body else "") + "\n}"


ROOM, WALL, HEIGHT = 1024, 64, 512
BARRELS = ((400, 0, 0), (400, 300, 30), (600, -300, 60))


def fixture(with_props):
    world = [box(-ROOM, -ROOM, -WALL, ROOM, ROOM, 0), box(-ROOM, -ROOM, HEIGHT, ROOM, ROOM, HEIGHT + WALL),
             box(-ROOM - WALL, -ROOM, 0, -ROOM, ROOM, HEIGHT), box(ROOM, -ROOM, 0, ROOM + WALL, ROOM, HEIGHT),
             box(-ROOM, -ROOM - WALL, 0, ROOM, -ROOM, HEIGHT), box(-ROOM, ROOM, 0, ROOM, ROOM + WALL, HEIGHT),
             box(-128, -128, 0, 128, 128, 128), ramp(-900, -900, -500, -500, 200)]
    ents = [entity("worldspawn", "\n".join(world)),
            entity("info_player_start", origin="-512 0 16", angles="0 0 0"),
            entity("light_environment", angles="-60 45 0", _light="255 250 240 300", _ambient="60 70 90 40"),
            entity("light", origin="300 -600 300", _light="255 120 60 600", _quadratic_attn="1"),
            entity("light_spot", origin="-600 600 450", angles="-90 0 0", _light="80 160 255 900",
                   _quadratic_attn="1", _cone="35", _inner_cone="20"),
            entity("trigger_multiple", box(-900, 600, 0, -600, 900, 200, TRIGGER),
                   targetname="mrvn_regress_trigger", spawnflags="1"),
            # A solid brush entity with retail S3 keys. Retail keeps func_brush in
            # _script.ent with no *coll keys: its collision is the BSP model's.
            entity("func_brush", box(300, 600, 0, 400, 700, 160), targetname="mrvn_regress_brush",
                   solidity="2", solidbsp="0", spawnflags="2", startdisabled="0", triangle_collision="1",
                   disableshadows="0", invert_exclusion="0", splitNavmesh="1", useNonLocalWorldLights="0",
                   bakedSunFraction="-1.0")]
    if with_props:
        ents += [entity("prop_static", model=BARREL, origin=f"{x} {y} 0", angles=f"0 {yaw} 0", solid="6")
                 for x, y, yaw in BARRELS]
    return "\n".join(ents) + "\n"


def checks(with_props):
    """(name, kind, start, end, expected fraction, tolerance) from fixture geometry.

    Hulls are 32x32x72 boxes from z=0 at the start point. The engine stops a
    trace about 1/32 unit short of a surface, hence the 0.05-unit tolerance
    expressed per trace length below.
    """
    out = [
        ("floor", "line", (-512, 0, 256), (-512, 0, -256), 256 / 512),
        ("ceiling", "line", (-512, 0, 256), (-512, 0, 768), 256 / 512),
        ("ceiling_hull", "hull", (-512, 0, 256), (-512, 0, 768), (HEIGHT - 72 - 256) / 512),
        ("block_side", "line", (-512, 0, 64), (1536, 0, 64), (512 - 128) / 2048),
        ("block_side_hull", "hull", (-512, 0, 64), (1536, 0, 64), (512 - 128 - 16) / 2048),
        ("block_top", "line", (0, 0, 256), (0, 0, -256), 128 / 512),
        ("north_wall", "line", (-512, 0, 256), (-512, 2048, 256), ROOM / 2048),
        ("north_wall_hull", "hull", (-512, 0, 256), (-512, 2048, 256), (ROOM - 16) / 2048),
        ("ramp_middle", "line", (-700, -700, 400), (-700, -700, -10), (400 - 100) / 410),
        ("ramp_high", "line", (-550, -700, 400), (-550, -700, -10), (400 - 175) / 410),
        ("trigger_nonsolid", "line", (-750, 500, 100), (-750, 1000, 100), 1.0),
        ("func_brush_side", "line", (350, 300, 64), (350, 1000, 64), (600 - 300) / 700),
        ("func_brush_top", "line", (350, 650, 400), (350, 650, -10), (400 - 160) / 410),
        ("func_brush_hull", "hull", (100, 650, 64), (700, 650, 64), (300 - 16 - 100) / 600),
    ]
    if with_props:
        out += [("barrel_side", "line", (400, -200, 24), (400, 200, 24), (200 - 15.27) / 400),
                ("barrel_top", "line", (400, 0, 200), (400, 0, -10), (200 - 47.70) / 210)]
    return out


def query(connection, name, expression):
    result = call(connection, "command", dict(text=f'script print("MRVN_REGRESS_{name} " + {expression})', timeout=10))
    text = "\n".join(e["text"] for e in result.get("events", []))
    match = re.search(rf"MRVN_REGRESS_{name} (.*)", text)
    return match[1].strip() if match else None


def vec(v):
    return "<" + ",".join(str(c) for c in v) + ">"


def trace_expression(kind, start, end):
    if kind == "hull":
        return (f"TraceHull({vec(start)},{vec(end)},<-16,-16,0>,<16,16,72>,null,"
                "TRACE_MASK_PLAYERSOLID,TRACE_COLLISION_GROUP_NONE).fraction")
    return f"TraceLine({vec(start)},{vec(end)},null,TRACE_MASK_PLAYERSOLID,TRACE_COLLISION_GROUP_NONE).fraction"


def run(args):
    work = args.work_dir.resolve()
    if work.exists():
        raise FileExistsError(f"{work} exists; choose a new work folder")
    work.mkdir(parents=True)
    base = work / "base"
    (base / "assets/shaders").mkdir(parents=True)
    (base / "assets/shaders/regress_tools.shader").write_text(TOOLS_SHADER)
    with_props = False
    if args.assets:
        shutil.copytree(args.assets, base / "assets", dirs_exist_ok=True)
        with_props = (base / "assets/models" / BARREL.replace(".rmdl", ".obj")).is_file()
    level = "mp_mrvn_regress_" + args.suffix
    source = work / f"{level}.map"
    source.write_text(fixture(with_props), encoding="utf-8")
    report = dict(level=level, with_props=with_props, remap=str(args.remap), checks=[], started=time.time())
    with (work / "build.log").open("wb") as log:
        subprocess.run([str(args.remap.resolve()), "-v", "-game", "apexlegends", "-fs_basepath", str(base),
                        "-bsp", str(source)], stdout=log, stderr=subprocess.STDOUT, check=True)
    report["bsp_bytes"] = source.with_suffix(".bsp").stat().st_size
    package = work / "package"
    stage_r5_map.build_package(source.with_suffix(".bsp"), package, level)
    stage_r5_map.install(package, args.game)
    try:
        # A rendered client ignores launchplaylist while in a map, so always
        # use a dedicated server for these checks.
        state = call(args.connection, "state")
        if state.get("running") and state.get("mode") != "dedicated":
            call(args.connection, "stop", {})
            state = call(args.connection, "state")
        if not state.get("running"):
            call(args.connection, "boot", dict(mode="dedicated", playlist_file=args.playlist_file, timeout=90))
        loaded = call(args.connection, "load", dict(map=level, playlist=args.playlist, gamemode=args.gamemode, timeout=90))
        report["load"] = loaded.get("last_load")
        if report["load"].get("state") != "loaded":
            report["passed"] = False
            return report
        for name, kind, start, end, expected in checks(with_props):
            raw = query(args.connection, name, trace_expression(kind, start, end))
            actual = float(raw) if raw and re.fullmatch(r"[-0-9.e]+", raw) else None
            length = sum((a - b) ** 2 for a, b in zip(start, end)) ** 0.5
            tolerance = 0.05 / length + 1e-4
            report["checks"].append(dict(name=name, kind=kind, expected=round(expected, 6), actual=actual,
                                         passed=actual is not None and abs(actual - expected) <= tolerance))
        trigger = query(args.connection, "trigger", 'GetEntArrayByClass_Expensive("trigger_multiple").len() + " " + '
                        'GetEntArrayByClass_Expensive("trigger_multiple")[0].GetBoundingMaxs()')
        report["checks"].append(dict(name="trigger_entity", expected="1 <150, 150, 100>", actual=trigger,
                                     passed=bool(trigger) and trigger.startswith("1 <150, 150, 100")))
        brush = query(args.connection, "brush", 'GetEntArrayByClass_Expensive("func_brush").len() + " " + '
                      'GetEntArrayByClass_Expensive("func_brush")[0].GetBoundingMaxs()')
        # A brush entity keeps origin 0, so its bounds are the model's world bounds
        # (the box maxima 400, 700, 160 plus about one unit).
        numbers = [float(v) for v in re.findall(r"-?[0-9.]+", brush or "")]
        report["checks"].append(dict(name="func_brush_entity", expected="1 <400, 700, 160> (+-1.5)", actual=brush,
                                     passed=len(numbers) == 4 and numbers[0] == 1 and all(
                                         abs(a - b) <= 1.5 for a, b in zip(numbers[1:], (400, 700, 160)))))
        report["passed"] = all(c["passed"] for c in report["checks"])
    finally:
        if not args.keep_installed:
            stage_r5_map.uninstall(args.game, level)
        report["finished"] = time.time()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--remap", type=Path, required=True)
    parser.add_argument("--game", type=Path, required=True, help="R5Reloaded folder")
    parser.add_argument("--connection", type=Path, required=True, help="r5_harness.py connection.json")
    parser.add_argument("--work-dir", type=Path, required=True, help="new folder for sources and reports")
    parser.add_argument("--assets", type=Path, help="extra compiler assets (shaders/, models/)")
    parser.add_argument("--suffix", default="fixture", help="level name suffix (lowercase)")
    parser.add_argument("--playlist-file", default="playlists_mrvn_coliseum.txt")
    parser.add_argument("--playlist", default="mrvn_coliseum")
    parser.add_argument("--gamemode", default="tdm")
    parser.add_argument("--keep-installed", action="store_true")
    args = parser.parse_args()
    report = run(args)
    (args.work_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for check in report["checks"]:
        print(f'{"PASS" if check["passed"] else "FAIL"} {check["name"]}: expected {check["expected"]} actual {check["actual"]}')
    print("passed" if report.get("passed") else "FAILED", report.get("load", {}).get("state"))
    raise SystemExit(0 if report.get("passed") else 1)


if __name__ == "__main__":
    main()
