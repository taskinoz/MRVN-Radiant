#!/usr/bin/env python3
"""Write cutout and translucent Titanfall 2 world-material templates for RePak.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.

Reads a decompressed copy of retail ``mp_coliseum.rpak`` (v7; see
``docs/respawn/RESPAWN_MATERIAL_TEMPLATES.md`` for decompressing one) and writes
RePak JSON + uber-buffer pairs that the map converters clone for every texture:

  cutout_wld, cutout_colpass_wld          alpha-tested world material
  cutout_shadow_wld, cutout_prepass_wld,  its alpha-tested depth passes; without
  cutout_vsm_wld                          them holes draw as solid quads
  translucent_wld                         alpha-blended world material, no depth passes

Both come from Coliseum because the converted maps alias their level pak to
``mp_coliseum.rpak``, so the shader sets they name are resident in game:
``uberCutSamp2222_wld`` / ``uberDepthCut_wld`` / ``uberDepthVsmCut_wld`` from the
decal sheet ``world/mcor/kodai_ind_decals_01``, and ``uberVcolaoVcolaTransSamp2222_wld``
from ``world/decal/blood_splat_01``. Their decal-only flags are replaced by the
values retail uses for ordinary world cutouts (Crash Site's thaw foliage) and
glass (``aquarium_interior_glass_01``): no depth bias, depth writes for cutouts.
The game files are only read; nothing from them is written except flags,
shader-set GUIDs and the 224-byte uber buffers.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rpak import RPak  # noqa: E402

CUTOUT = 'world/mcor/kodai_ind_decals_01'
TRANSLUCENT = 'world/decal/blood_splat_01'
# Flag overrides: decal bias (rasterizer 0x10) and decal glue bit 0x10 removed,
# depth writes (0x17) restored, as on retail non-decal world cutouts.
OVERRIDES = {
    'cutout_wld': {'glueFlags': '0x72000001', 'depthStencilFlags': '0x17', 'rasterizerFlags': '0x6'},
    'cutout_colpass_wld': {'glueFlags': '0x72000001', 'depthStencilFlags': '0x5', 'rasterizerFlags': '0x6'},
    'cutout_shadow_wld': {'glueFlags': '0x10200090', 'depthStencilFlags': '0x17', 'rasterizerFlags': '0x26'},
    'cutout_prepass_wld': {'glueFlags': '0x10200090', 'depthStencilFlags': '0x17', 'rasterizerFlags': '0x6'},
    'cutout_vsm_wld': {'glueFlags': '0x10200090', 'depthStencilFlags': '0x17', 'rasterizerFlags': '0x2'},
    'translucent_wld': {'rasterizerFlags': '0x6'},
}
SOURCES = {
    'cutout_wld': CUTOUT, 'cutout_colpass_wld': CUTOUT + '_colpass',
    'cutout_shadow_wld': 'depth/' + CUTOUT + '_shadow', 'cutout_prepass_wld': 'depth/' + CUTOUT + '_prepass',
    'cutout_vsm_wld': 'depth/' + CUTOUT + '_vsm', 'translucent_wld': TRANSLUCENT,
}


def templates(pak):
    found = {}
    for asset, name in pak.materials():
        found.setdefault(name, asset)
    out = {}
    for key, source in SOURCES.items():
        if source not in found:
            raise ValueError(f'{source} not found; pass a decompressed mp_coliseum.rpak')
        spec, uber = pak.material(found[source])
        spec['blendStates'] = spec['blendStates'] + ['0x0'] * (8 - len(spec['blendStates']))
        spec.update(OVERRIDES[key])
        spec['name'] = 'template/' + key
        # Converters fill these in per texture.
        spec['$textures'] = {}
        for field in ('$depthShadowMaterial', '$depthPrepassMaterial', '$depthVSMMaterial', '$colpassMaterial'):
            spec[field] = '0x0'
        out[key] = (spec, uber)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('pak', type=Path, help='decompressed mp_coliseum.rpak')
    p.add_argument('--output', type=Path, required=True, help='directory for the template files')
    args = p.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    for key, (spec, uber) in templates(RPak(args.pak)).items():
        (args.output / f'{key}.json').write_text(json.dumps(spec, indent=2))
        (args.output / f'{key}.uber').write_bytes(uber)
        print(key, spec['shaderSet'])


if __name__ == '__main__':
    main()
