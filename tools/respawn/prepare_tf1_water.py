#!/usr/bin/env python3
"""Compile an original v29 water room and shared TFO/R1 camera checks.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
References retail material names; includes no retail assets.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from compiler_regression import box
from inspect_bsp import inspect
from portals import locate_cell
from validate_records import load_records, validate


def prepare(remap, output, diagnostic_texture=None, basin=False, flooded=False):
    if basin and flooded:
        raise ValueError("basin and flooded layouts are mutually exclusive")
    if diagnostic_texture is not None and diagnostic_texture.read_bytes()[:4] != b'VTF\0':
        raise ValueError('diagnostic texture must be a locally supplied VTF')
    output.mkdir(parents=True, exist_ok=False)
    assets = output / 'assets/shaders'
    assets.mkdir(parents=True)
    floor = 'world/concrete/concrete_floor_01'
    water = 'world/water/water_mp_angelcity_cheap'
    beneath = 'world/water/water_floating_village_beneath'
    if diagnostic_texture is not None:
        # Keep the compiler water profiles and cell geometry; substitute only
        # uniquely named runtime materials to prove staging/surface visibility.
        water, beneath = 'ares_water/top', 'ares_water/bottom'
        materials = output / 'material-files/materials/ares_water'
        materials.mkdir(parents=True)
        shutil.copyfile(diagnostic_texture, materials / 'noise.vtf')
        for name, color in (('top', '1 0 1'), ('bottom', '0 1 1')):
            (materials / (name + '.vmt')).write_text(
                'UnlitGeneric\n{\n $basetexture "ares_water/noise"\n $color "[' + color + ']"\n}\n',
                encoding='utf-8')
    (assets / 'water.shader').write_text(''.join(
        f'textures/{name}\n{{\n $shadertype {kind}\n}}\n'
        for name, kind in ((floor, 'LitBumpGeneric'), (water, 'Water'),
                           (beneath, 'WaterBeneath'))), encoding='utf-8')
    shapes = [((-1024, -1024, -32), (1024, 1024, 0)),
              ((-1024, -1024, 512), (1024, 1024, 544)),
              ((-1056, -1056, 0), (-1024, 1056, 512)),
              ((1024, -1056, 0), (1056, 1056, 512)),
              ((-1024, -1056, 0), (1024, -1024, 512)),
              ((-1024, 1024, 0), (1024, 1056, 512))]
    if basin:
        # Keep water side exits behind solid banks, as in a contained pool.
        # The original open-sided volume remains available as an edge control.
        shapes += [((-528, -528, 0), (-512, 528, 128)),
                   ((0, -528, 0), (16, 528, 128)),
                   ((-512, -528, 0), (0, -512, 128)),
                   ((-512, 512, 0), (0, 528, 128))]
    water_min = (-1024, -1024, 0) if flooded else (-512, -512, 0)
    water_max = (1024, 1024, 128) if flooded else (0, 512, 128)
    patch_x = (1024, 0, -1024) if flooded else (0, -256, -512)
    patch_y = (-1024, 0, 1024) if flooded else (-512, 0, 512)
    geometry = '\n'.join(box(lo, hi, floor).replace('compat/' + floor, floor)
                         for lo, hi in shapes)
    geometry += '\n' + box(water_min, water_max, water).replace('compat/' + water, water)
    geometry += '\n{\npatchDef2\n{\n' + beneath + '\n( 3 3 0 0 0 )\n(\n' + '\n'.join(
        '( ' + ' '.join(f'( {x} {y} 128 {i / 2} {j / 2} )'
                        for j, y in enumerate(patch_y)) + ' )'
        for i, x in enumerate(patch_x)) + '\n)\n}\n}'
    source = '{\n"classname" "worldspawn"\n"_viewportals" "1"\n' + \
             '"_remap_lightmap_pagesize" "256"\n' + geometry + '\n}\n'
    spawn_origin = '512 0 192' if flooded else '512 0 64'
    source += ''.join('{\n"classname" "' + kind + f'"\n"origin" "{spawn_origin}"\n' +
                      f'"teamnumber" "{team}"\n"ignoreGamemode" "1"\n"gamemode_tdm" "1"\n}}\n'
                      for team in (2, 3)
                      for kind in ('info_spawnpoint_human', 'info_spawnpoint_human_start'))
    source += '{\n"classname" "light"\n"origin" "0 0 384"\n"light" "1000"\n"_color" "1 1 1"\n}\n'
    maps = output / 'maps'
    maps.mkdir()
    path = maps / 'mp_tf1_water.map'
    path.write_text(source, encoding='utf-8')
    command = [str(remap.resolve()), '-game', 'titanfallonline', '-fs_basepath',
               str(output.resolve()), '-bsp', str(path.resolve())]
    with (output / 'compile.log').open('wb') as log:
        subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
    bsp = path.with_suffix('.bsp')
    report = validate(bsp)
    (output / 'static.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if report['issues']:
        raise RuntimeError(report['issues'])
    records = load_records(bsp, inspect(bsp))
    cells = []
    cell_probes = [((-256, 0, 64), True), ((-256, 0, 192), False),
                   ((256, 0, 64), flooded)]
    if flooded:
        cell_probes.append(((256, 0, 192), False))
    for point, wet in cell_probes:
        cell = locate_cell(records, point)
        water_index = records[107][cell][3]
        if (water_index >= 0) != wet:
            raise RuntimeError(f'incorrect wet/dry cell at {point}')
        cells.append({'point': point, 'cell': cell, 'water': water_index})
    checks = {'traces': [[-256, 0, 256, -256, 0, -32], [256, 0, 256, 256, 0, -32]],
              'expect': {'trace_z': [[0, 0, .1], [1, 0, .1]]},
              'views': [[-256, -320, 192, 20, 90], [-256, -320, 16, 0, 90], [256, -320, 192 if flooded else 16, 0, 90]]}
    (output / 'checks.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    buoyancy = {'traces': checks['traces'], 'drops': [[-256, 0, 192], [256, 0, 192]],
                'drop_models': ['models/containers/box_large_cardboard.mdl'] * 2,
                'drop_wait': 12, 'drop_samples': True, 'drop_sequential': True,
                'expect': {'trace_z': checks['expect']['trace_z'],
                           'drop_z': [[0, 64, 160], [1, 0, 32]]}}
    if not flooded:
        (output / 'buoyancy-checks.json').write_text(json.dumps(buoyancy, indent=2), encoding='utf-8')
    manifest = {'command': command, 'cells': cells, 'solid_banks': basin,
                'layout': 'flooded' if flooded else 'basin' if basin else 'open',
                'water_bounds': [water_min, water_max],
                'runtime_surface_shader': 'UnlitGeneric diagnostic' if diagnostic_texture else 'retail Water',
                'remap_sha256': hashlib.sha256(remap.read_bytes()).hexdigest(),
                'bsp_sha256': hashlib.sha256(bsp.read_bytes()).hexdigest(),
                'scope': 'Rectangular water room, explicit reversed underside, three views and two floor rays. '
                         'Non-flooded layouts also emit wet/dry cardboard buoyancy checks; no broad buoyancy, '
                         'navigation or gameplay acceptance. Materials/models must be supplied locally.'}
    (output / 'build.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--diagnostic-texture', type=Path,
                        help='Local VTF for magenta/cyan UnlitGeneric surface controls; not Water shader acceptance')
    layouts = parser.add_mutually_exclusive_group()
    layouts.add_argument('--flooded', action='store_true',
                         help='Extend water to all room walls; no dry-floor or paired buoyancy control')
    layouts.add_argument('--basin', action='store_true',
                        help='Enclose the water sides with solid banks; default keeps the exposed-edge control')
    args = parser.parse_args()
    prepare(args.remap, args.output, args.diagnostic_texture, args.basin, args.flooded)
