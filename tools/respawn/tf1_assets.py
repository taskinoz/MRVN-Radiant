#!/usr/bin/env python3
"""Collect the loose files a set of TF1 materials needs from an asset tree.

For each material name (as stored in a BSP's texture table) this finds
materials/<name>.vmt, follows `patch` materials to their `include`, and adds
every texture parameter value that exists as materials/<value>.vtf. It does
not decode shaders, proxies or conditional blocks; names it cannot find are
reported as missing rather than guessed.

  python tools/respawn/tf1_assets.py --source ASSET_TREE --output NEW_DIR NAME [NAME ...]

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from source_engine import parse_vmt  # noqa: E402

# Parameters that hold a texture path in TF1/Source VMTs and are not files.
NON_FILES = {'env_cubemap', '_rt_fullframefb', '_rt_waterreflection', '_rt_waterrefraction'}


def clean(value):
    return value.replace('\\', '/').strip('/').lower().removeprefix('materials/')


def find(source, relative):
    """Case-insensitive lookup of a relative path under source."""
    path = source
    for part in relative.split('/'):
        if not path.is_dir():
            return None
        exact = path / part
        if exact.exists():
            path = exact
            continue
        match = next((p for p in path.iterdir() if p.name.lower() == part.lower()), None)
        if match is None:
            return None
        path = match
    return path if path.is_file() else None


def material_files(source, names, depth_limit=4):
    """{'files': {relative path: absolute path}, 'missing': [material names]}."""
    source = Path(source)
    files, missing = {}, []

    def visit(name, depth):
        relative = 'materials/' + clean(name).removesuffix('.vmt') + '.vmt'
        if relative in files:
            return True
        path = find(source, relative)
        if path is None:
            return False
        files[relative] = path
        shader, values = parse_vmt(path.read_text(encoding='latin-1'))
        if shader == 'patch' and 'include' in values and depth < depth_limit:
            visit(values['include'], depth + 1)
        for key, value in values.items():
            if not key.startswith('$') or not isinstance(value, str) or clean(value) in NON_FILES:
                continue
            texture = 'materials/' + clean(value).removesuffix('.vtf') + '.vtf'
            if (found := find(source, texture)) is not None:
                files[texture] = found
        return True

    for name in names:
        if not visit(name, 0):
            missing.append(name)
    return {'files': files, 'missing': missing}


def vpk_names(directory):
    """Lower-case member paths of a Respawn VPK 2.3 directory file (the
    layout pack_vpk.py writes: per entry a CRC, preload and archive words,
    then 30-byte parts each followed by a 0xffff-terminated u16)."""
    data = Path(directory).read_bytes()
    signature, major, minor, size, _ = struct.unpack_from('<IHHII', data)
    if signature != 0x55aa1234 or (major, minor) != (2, 3) or 16 + size > len(data):
        raise ValueError(f'not a Respawn VPK 2.3 directory: {directory}')
    cursor, end, names = 16, 16 + size, set()

    def string():
        nonlocal cursor
        stop = data.index(bytes(1), cursor, end)
        value = data[cursor:stop].decode('latin-1')
        cursor = stop + 1
        return value
    while (extension := string()):
        while (parent := string()):
            while (stem := string()):
                _, preload, _ = struct.unpack_from('<IHH', data, cursor)
                cursor += 8
                while True:
                    cursor += 30
                    (marker,) = struct.unpack_from('<H', data, cursor)
                    cursor += 2
                    if marker == 0xffff:
                        break
                cursor += preload
                folder = '' if parent.strip() == '' else parent.strip('/') + '/'
                names.add((folder + stem + '.' + extension).replace(chr(92), '/').lower())
    return names


def copy_files(found, output):
    output = Path(output)
    for relative, path in sorted(found['files'].items()):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('names', nargs='+')
    args = parser.parse_args()
    found = material_files(args.source, args.names)
    copy_files(found, args.output)
    print(json.dumps({'files': sorted(found['files']), 'missing': found['missing']}, indent=2))
    return 1 if found['missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
