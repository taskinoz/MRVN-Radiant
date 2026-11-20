#!/usr/bin/env python3
"""Compile an original v29 physics fixture and emit R1Delta prop checks.

One walled floor with stations that exercise VPhysics beyond flat drops:
a shallow and a steep ramp, a half-cylinder and a dome patch, a three-barrel
stack, a thin slab hit from a long fall, barrels thrown into a wall at two
speeds, and a barrel dropped on its side. Every barrel must come to rest
(moves at most 2 units in its last 2 s) above the surface it lands on and inside the walls.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from compiler_regression import box, triangle_prism

MATERIAL = 'world/concrete/concrete_floor_01'
MODEL = 'models/containers/barrel.mdl'
HALF_X, HALF_Y, WALL = 2048, 1024, 256
# The barrel's origin is at its base: it rests at +0.5 upright and about
# +15.7 on its side (measured on this fixture in R1Delta). This band covers
# both and rejects a barrel sunk into a surface or left balanced on another.
REST = (-1, 24)
SETTLE = 2  # units moved over the last two sampled seconds


def brush(lo, hi):
    return box(lo, hi, MATERIAL).replace('compat/' + MATERIAL, MATERIAL)


def ramp(x0, x1, y0, y1, height):
    """A wedge rising from z=0 at x0 to height at x1 (two clockwise prisms)."""
    low0, low1 = (x0, y0, 0), (x0, y1, 0)
    high0, high1 = (x1, y0, height), (x1, y1, height)
    return '\n'.join(triangle_prism(tri, -16, MATERIAL) for tri in ((low0, low1, high1), (low0, high1, high0)))


def patch(rows):
    return ('{\npatchDef2\n{\n' + MATERIAL + '\n( 3 3 0 0 0 )\n(\n' + '\n'.join(
        '( ' + ' '.join(f'( {x} {y} {z} {i / 2} {j / 2} )' for j, (x, y, z) in enumerate(row)) + ' )'
        for i, row in enumerate(rows)) + '\n)\n}\n}')


def cylinder(cx, cy, radius=96, height=64, length=192):
    # A quadratic Bezier peaks at half its middle control point's height.
    return patch([[(cx + dx, cy + dy, z) for dy in (-length, 0, length)]
                  for dx, z in ((-radius, 0), (0, 2 * height), (radius, 0))])


def dome(cx, cy, radius=128, height=64):
    # Edges stay on the floor; a biquadratic patch peaks at a quarter of its
    # centre control point's height.
    return patch([[(cx + i * radius, cy + j * radius, 0 if i or j else 4 * height)
                   for j in (-1, 0, 1)] for i in (-1, 0, 1)])


def stations():
    """(drop, velocity, angles, expected z band, x band, y band, label).

    Curved patches compile as their control grid (render and collision alike,
    see RESPAWN_TRICOLL_PORTALS.md), so patch heights here are control-grid
    heights: the cylinder ridge is at 128 and the dome apex at 256."""
    inside_x, inside_y = (-HALF_X + 8, HALF_X - 8), (-HALF_Y + 8, HALF_Y - 8)
    floor = REST
    side = (0, 0, 90)  # axis along y, so it rolls along x
    return [
        ((-1560, -800, 260), (0, 0, 0), side, floor, (inside_x[0], -1900), inside_y, 'shallow ramp rolls down'),
        ((-1560, -300, 260), (0, 0, 0), side, floor, (inside_x[0], -1700), inside_y, 'steep ramp rolls down'),
        ((-770, -800, 200), (0, 0, 0), side, floor, (-704, inside_x[1]), inside_y, 'half-cylinder facet rolls off'),
        ((-140, -800, 320), (0, 0, 0), (0, 0, 0), floor, inside_x, inside_y, 'dome facet slides off'),
        ((300, -800, 40), (0, 0, 0), (0, 0, 0), (-1, 2), inside_x, inside_y, 'stack bottom'),
        ((300, -800, 100), (0, 0, 0), (0, 0, 0), (46, 52), inside_x, inside_y, 'stack middle'),
        ((300, -800, 160), (0, 0, 0), (0, 0, 0), (94, 100), inside_x, inside_y, 'stack top'),
        ((1200, -600, 2000), (0, 0, 0), (0, 0, 0), (264 + REST[0], 264 + REST[1]), (800, 1600), (-1000, -200),
         'long fall onto thin slab'),
        ((1200, 300, 40), (800, 0, 0), (0, 0, 0), floor, inside_x, inside_y, 'thrown into wall'),
        ((1200, 700, 40), (2500, 0, 0), (0, 0, 0), floor, inside_x, inside_y, 'fast throw into wall'),
        ((-800, 500, 40), (0, 0, 0), side, floor, inside_x, inside_y, 'dropped on its side'),
        ((-200, 500, 300), (0, 0, -400), (30, 20, 10), floor, inside_x, inside_y, 'thrown down tumbling'),
    ]


def prepare(remap, output):
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets/shaders'
    assets.mkdir(parents=True)
    (assets / 'physics.shader').write_text(f'textures/{MATERIAL}\n{{\n $shadertype LitBumpGeneric\n}}\n',
                                            encoding='utf-8')
    maps = output / 'maps'
    maps.mkdir()
    world = [brush((-HALF_X, -HALF_Y, -64), (HALF_X, HALF_Y, 0))]
    world += [brush((-HALF_X - 32, -HALF_Y, 0), (-HALF_X, HALF_Y, WALL)),
              brush((HALF_X, -HALF_Y, 0), (HALF_X + 32, HALF_Y, WALL)),
              brush((-HALF_X - 32, -HALF_Y - 32, 0), (HALF_X + 32, -HALF_Y, WALL)),
              brush((-HALF_X - 32, HALF_Y, 0), (HALF_X + 32, HALF_Y + 32, WALL))]
    world += [ramp(-1900, -1500, -1000, -600, 160), ramp(-1700, -1500, -500, -100, 200)]
    world += [brush((800, -1000, 256), (1600, -200, 264))]  # thin slab, floating
    world += [cylinder(-800, -800), dome(-200, -800)]
    spawns = ''.join('{\n"classname" "' + kind + f'"\n"origin" "0 900 64"\n"teamnumber" "{team}"\n'
                     '"ignoreGamemode" "1"\n"gamemode_tdm" "1"\n}\n'
                     for team in (2, 3) for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start'))
    path = maps / 'mp_tf1_physics.map'
    path.write_text('{\n"classname" "worldspawn"\n' + '\n'.join(world) + '\n}\n' + spawns +
                    '{\n"classname" "info_intermission"\n"origin" "0 900 64"\n}\n', encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath', str(output.resolve()),
               '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    rows = stations()
    checks = {'drops': [list(r[0]) for r in rows], 'drop_models': [MODEL] * len(rows),
              'drop_velocities': [list(r[1]) for r in rows], 'drop_angles': [list(r[2]) for r in rows],
              'drop_wait': 25, 'drop_samples': True,
              'labels': [r[6] for r in rows],
              'expect': {'drop_z': [[i, *r[3]] for i, r in enumerate(rows)],
                         'drop_x': [[i, *r[4]] for i, r in enumerate(rows)],
                         'drop_y': [[i, *r[5]] for i, r in enumerate(rows)],
                         'drop_settle': [[i, 0, SETTLE] for i in range(len(rows))]}}
    (output / 'checks.json').write_text(json.dumps(checks, indent=2) + '\n', encoding='utf-8')
    manifest = {'command': command, 'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(path.with_suffix('.bsp').read_bytes()).hexdigest(),
                'scope': 'Barrel VPhysics on ramps, patches, a stack, a thin slab and walls. '
                         'No crate, water, moving-brush or gameplay coverage.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    prepare(args.remap, args.output)


if __name__ == '__main__':
    main()
