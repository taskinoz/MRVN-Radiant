#!/usr/bin/env python3
"""Package explicitly supplied shader caches for an authored TF1 map.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No shader extraction, conversion or retail assets included.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from pack_vpk import pack_files


def package(source, output, map_name):
    if not re.fullmatch(r'mp_[A-Za-z0-9_]+', map_name):
        raise ValueError('expected an mp_ map name')
    if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
        raise ValueError('linked shader root')
    if not source.is_dir():
        raise ValueError('shader source must be a directory')
    files = {}
    for path in sorted(source.rglob('*')):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise ValueError('linked shader member')
        if path.is_dir():
            continue
        relative = path.relative_to(source).as_posix()
        if not re.fullmatch(r'shaders/fxc/[A-Za-z0-9_]+\.vcs', relative):
            raise ValueError(f'expected only shaders/fxc/*.vcs files: {relative}')
        files[relative] = path.read_bytes()
    if not files:
        raise ValueError('empty shader tree')
    # Exclusive output directory prevents overwriting an existing map package.
    output.mkdir(parents=True, exist_ok=False)
    directory, archive = pack_files(files, output, 'client_' + map_name + '.bsp.pak000')
    manifest = {
        'map': map_name, 'members': {name: hashlib.sha256(data).hexdigest()
                                    for name, data in files.items()},
        'archives': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (directory, archive)},
        'scope': 'Shader-only VPK. Materials, textures, models and gameplay sidecars '
                 'must be supplied separately. Native validation covers Water in one R1 map.'}
    (output / 'shader-package.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Explicit tree containing only shaders/fxc/*.vcs')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map', required=True)
    args = parser.parse_args()
    package(args.source, args.output, args.map)
