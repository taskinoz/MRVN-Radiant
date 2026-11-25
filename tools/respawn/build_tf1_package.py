#!/usr/bin/env python3
"""Package a compiled Titanfall 1 map as a Titanfall Online mod and an R1Delta addon.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later. Original code.

The layouts are the ones the native harnesses load:

  tfo/<Name>/mod.json, tfo/<Name>/mod/maps/<map>.bsp (+ .bsp_lump, .ent, graphs/<map>.ain)
  r1delta/<Name>/maps/<map>.bsp (+ the same files); list <Name> in r1/addonlist.txt
  vpk/client_<map>.bsp.pak000_*.vpk   optional shader-only map VPK (pack_tf1_shaders.py)
                                      the directory may be englishclient_<map>...

The compiled level must pass validate_records.py (records, entity partitions and
sidecars). Every material named by the BSP and every static-prop model is listed
in manifest.json as shipped, base game or missing. With --base-vpk (the game's
vpk/ folder) "base game" means present in englishclient_mp_common, the only map
VPK a custom map mounts; anything else must be shipped (most TF1 world materials
live in per-map VPKs). Without it, unshipped names are "base game (unverified)".
--asset-source collects the VMTs and VTFs of materials that are neither shipped
nor in mp_common from a loose tree (tf1_assets.py) and ships them. --strict
fails when anything is missing. No game files are bundled unless you supply
them; check you may redistribute what you put in --assets or --asset-source.

  python tools/respawn/build_tf1_package.py --maps BUILD/maps --map mp_name \
      --name Author.MapName --version 1.0.0 --output NEW_DIR [--assets DIR] [--shader-vpk DIR]
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zipfile

from inspect_bsp import FormatError, inspect
from lighting import payload
from tf1_assets import material_files, vpk_names

NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}')
MAP = re.compile(r'mp_[A-Za-z0-9_]{1,60}')
VERSION = re.compile(r'\d+\.\d+\.\d+')
ASSET_ROOTS = ('materials', 'models', 'sound', 'scripts', 'resource', 'particles', 'cfg')
GRAPH_LIMIT = 64 * 1024 * 1024


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def texture_names(bsp, inventory):
    """Material names from TEXTURE_DATA_STRING_DATA (lump 43)."""
    data, _ = payload(bsp, inventory, 43)
    return sorted({name.decode('latin1').replace('\\', '/').lower()
                   for name in data.split(b'\0') if name})


def prop_models(bsp, inventory):
    """Static-prop model paths from a v29 GAME_LUMP 'sprp' dictionary."""
    data, _ = payload(bsp, inventory, 35)
    if not data:
        return []
    entry = inventory['lumps'][35]
    if len(data) < 4:
        raise FormatError('truncated GAME_LUMP')
    count = struct.unpack_from('<I', data, 0)[0]
    if count > 64 or 4 + count * 16 > len(data):
        raise FormatError('invalid GAME_LUMP directory')
    models = []
    for i in range(count):
        ident, _, offset, length = struct.unpack_from('<4sIII', data, 4 + i * 16)
        if ident not in (b'prps', b'sprp'):
            continue
        # Offsets are absolute in the file; translate them into this payload.
        local = offset - entry['offset'] if entry['offset'] <= offset < entry['offset'] + len(data) else offset
        if local < 0 or local + 4 > len(data) or length > len(data):
            raise FormatError('sprp entry outside GAME_LUMP')
        paths = struct.unpack_from('<I', data, local)[0]
        if paths > 65536 or local + 4 + paths * 128 > len(data):
            raise FormatError('invalid sprp model dictionary')
        for p in range(paths):
            raw = data[local + 4 + p * 128:local + 4 + (p + 1) * 128].split(b'\0', 1)[0]
            if raw:
                models.append(raw.decode('latin1').replace('\\', '/').lower())
    return sorted(set(models))


def level_files(maps, map_name):
    bsp = maps / f'{map_name}.bsp'
    if not bsp.is_file() or linked(bsp):
        raise ValueError(f'missing compiled map: {bsp}')
    files = []
    for item in sorted(maps.iterdir()):
        if not item.is_file() or not item.name.lower().startswith(map_name.lower()):
            continue
        if linked(item):
            raise ValueError(f'linked map file: {item}')
        rest = item.name[len(map_name):]
        if rest == '.bsp' or rest.endswith('.bsp_lump') or (rest.startswith('_') and rest.endswith('.ent')):
            files.append(item)
    graph = maps / 'graphs' / f'{map_name}.ain'
    if graph.exists():
        if linked(graph) or not graph.is_file() or graph.stat().st_size > GRAPH_LIMIT:
            raise ValueError(f'unusable navigation graph: {graph}')
    else:
        graph = None
    return bsp, files, graph


def asset_files(assets):
    if assets is None:
        return {}
    if linked(assets) or not assets.is_dir():
        raise ValueError('--assets must be a real directory')
    found = {}
    for path in sorted(assets.rglob('*')):
        if linked(path):
            raise ValueError(f'linked asset: {path}')
        if path.is_dir():
            continue
        relative = path.relative_to(assets).as_posix()
        if relative.split('/', 1)[0].lower() not in ASSET_ROOTS:
            raise ValueError(f'asset outside {", ".join(ASSET_ROOTS)}: {relative}')
        found[relative] = path
    return found


def shader_vpks(folder, map_name):
    """Accept the VPK pair written by pack_tf1_shaders.py.

    pack_vpk.pack_files() writes englishclient_<map>.bsp.pak000_dir.vpk and
    client_<map>.bsp.pak000_000.vpk. Older fixtures renamed the directory to
    client_<map>...; both directory forms are valid. External blocks must keep
    the unprefixed client_<map>... name.
    """
    if folder is None:
        return []
    if linked(folder) or not folder.is_dir():
        raise ValueError('--shader-vpk must be a real directory')
    vpks = sorted(p for p in folder.iterdir() if p.suffix.lower() == '.vpk')
    prefix = f'client_{map_name}.bsp.pak000_'.lower()
    dir_prefix = 'english' + prefix
    directories = []
    for path in vpks:
        name = path.name.lower()
        if linked(path):
            raise ValueError(f'linked shader VPK: {path}')
        if name.endswith('_dir.vpk'):
            if not name.startswith((prefix, dir_prefix)):
                raise ValueError(f'expected only {prefix}*.vpk files in --shader-vpk')
            directories.append(path)
        elif not name.startswith(prefix):
            raise ValueError(f'expected only {prefix}*.vpk files in --shader-vpk')
    if not vpks:
        raise ValueError(f'expected only {prefix}*.vpk files in --shader-vpk')
    if len(directories) != 1:
        raise ValueError('shader VPK set needs exactly one _dir.vpk')
    return vpks


def dependencies(textures, models, shipped, base=None):
    """'shipped', 'base game' (in mp_common), 'missing', or without a base
    listing 'base game (unverified)', per material and model."""
    lower = {name.lower() for name in shipped}

    def status(path):
        if path in lower:
            return 'shipped'
        if base is None:
            return 'base game (unverified)'
        return 'base game' if path in base else 'missing'
    materials = {t: status(f'materials/{t}.vmt') for t in textures}
    props = {m: status(m) for m in models}
    return {'materials': materials, 'models': props}


def base_listing(folder):
    if folder is None:
        return None
    directory = Path(folder) / 'englishclient_mp_common.bsp.pak000_dir.vpk'
    if linked(Path(folder)) or not directory.is_file():
        raise ValueError(f'--base-vpk needs {directory.name} in the game vpk folder')
    return vpk_names(directory)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def zip_tree(root, archive):
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
        for path in sorted(root.rglob('*')):
            if path.is_file():
                out.write(path, path.relative_to(root.parent).as_posix())


def package(maps, map_name, name, version, output, description='', assets=None, shader_vpk=None,
            strict=False, validator=None, base_vpk=None, asset_source=None):
    if not MAP.fullmatch(map_name) or not NAME.fullmatch(name) or not VERSION.fullmatch(version):
        raise ValueError('expected an mp_ map name, a simple package name and an x.y.z version')
    if linked(maps) or not maps.is_dir():
        raise ValueError('--maps must be a real directory')
    bsp, files, graph = level_files(maps, map_name)
    inventory = inspect(bsp)
    if inventory['version_raw'] != 29:
        raise ValueError('TF1 packages need a v29 BSP')
    if validator is None:
        from validate_records import validate as validator
    issues = validator(bsp)['issues']
    if issues:
        raise ValueError(f'compiled map fails record validation: {issues[:5]}')
    shipped = asset_files(assets)
    vpks = shader_vpks(shader_vpk, map_name)
    base = base_listing(base_vpk)
    textures = texture_names(bsp, inventory)
    collected = []
    if asset_source is not None:
        lower = {name.lower() for name in shipped}
        wanted = [t for t in textures if f'materials/{t}.vmt' not in lower and
                  (base is None or f'materials/{t}.vmt' not in base)]
        found = material_files(asset_source, wanted)
        for relative, path in found['files'].items():
            if relative.lower() not in lower:
                shipped[relative] = path
                collected.append(relative)
    deps = dependencies(textures, prop_models(bsp, inventory), shipped, base)
    missing = sorted(k for group in deps.values() for k, v in group.items() if v == 'missing')
    unverified = sorted(k for group in deps.values() for k, v in group.items() if v.endswith('(unverified)'))
    if strict and (missing or unverified):
        raise ValueError(f'--strict: not shipped or in mp_common: {(missing + unverified)[:10]}')

    output.mkdir(parents=True, exist_ok=False)
    tfo = output / 'tfo' / name
    r1 = output / 'r1delta' / name
    for level_root in (tfo / 'mod' / 'maps', r1 / 'maps'):
        level_root.mkdir(parents=True)
        for item in files:
            shutil.copyfile(item, level_root / item.name)
        if graph is not None:
            (level_root / 'graphs').mkdir()
            shutil.copyfile(graph, level_root / 'graphs' / graph.name)
    for relative, source in shipped.items():
        for root in (tfo / 'mod', r1):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    (tfo / 'mod.json').write_text(json.dumps({
        'Name': name, 'Description': description or f'Titanfall 1 map {map_name}', 'Version': version,
        'LoadPriority': 50, 'RequiredOnClient': True}, indent=1) + '\n', encoding='utf-8')
    if vpks:
        (output / 'vpk').mkdir()
        for vpk in vpks:
            shutil.copyfile(vpk, output / 'vpk' / vpk.name)
    (output / 'INSTALL.md').write_text(install_text(name, map_name, bool(vpks), missing + unverified),
                                       encoding='utf-8')

    manifest = {'map': map_name, 'name': name, 'version': version, 'bsp_version': 29,
                'navigation_graph': graph is not None, 'dependencies': deps,
                'missing': missing, 'unverified': unverified, 'collected_from_asset_source': sorted(collected),
                'files': {}}
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'][path.relative_to(output).as_posix()] = sha256(path)
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    zip_tree(tfo, output / f'{name}-{version}-tfo.zip')
    zip_tree(r1, output / f'{name}-{version}-r1delta.zip')
    return manifest


def install_text(name, map_name, vpk, missing):
    lines = [f'# {name}', '',
             '## Titanfall Online (TFORevive)', '',
             f'Copy `tfo/{name}` into `Titanfall Online/Mods/` and enable it in the launcher',
             '(or add it to `Mods/enabledmods.json`).', '',
             '## R1Delta', '',
             f'Copy `r1delta/{name}` into `r1/addons/` and add it to `r1/addonlist.txt`:', '',
             '```', '"AddonList"', '{', f'\t"{name}"\t"1"', '}', '```', '',
             f'Load it with `map {map_name}`.', '']
    if vpk:
        lines += ['## Shader VPK', '',
                  'The map uses Water shaders loaded from a map VPK. Copy the files in `vpk/`',
                  'into the game\'s `vpk/` folder. Loose shader caches do not load.', '']
    if missing:
        lines += ['## Base-game dependencies', '',
                  f'{len(missing)} materials/models are expected from the base game; see',
                  '`manifest.json` (`not_shipped`).', '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--maps', type=Path, required=True, help='folder with <map>.bsp, sidecars and optional graphs/')
    p.add_argument('--map', required=True)
    p.add_argument('--name', required=True, help='package folder name, e.g. Author.MapName')
    p.add_argument('--version', required=True)
    p.add_argument('--description', default='')
    p.add_argument('--assets', type=Path, help='materials/, models/, sound/ ... to ship with the map')
    p.add_argument('--shader-vpk', type=Path, help='output folder of pack_tf1_shaders.py')
    p.add_argument('--base-vpk', type=Path, help="the game's vpk/ folder, to check what mp_common provides")
    p.add_argument('--asset-source', type=Path,
                   help='loose tree to collect unshipped, non-mp_common materials from (VMT + VTFs)')
    p.add_argument('--strict', action='store_true', help='fail if any material/model is missing or unverified')
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    manifest = package(args.maps, args.map, args.name, args.version, args.output, args.description,
                       args.assets, args.shader_vpk, args.strict, base_vpk=args.base_vpk,
                       asset_source=args.asset_source)
    print(json.dumps({k: manifest[k] for k in ('map', 'name', 'version', 'navigation_graph', 'missing', 'unverified',
                                               'collected_from_asset_source')}, indent=2))


if __name__ == '__main__':
    main()
