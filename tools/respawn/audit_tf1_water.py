#!/usr/bin/env python3
"""Audit explicitly supplied TF1 Water materials and known file dependencies.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
No asset extraction or redistribution. This is not a complete VMT interpreter.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

TEXTURES = {'$basetexture', '$normalmap', '$bumpmap', '$detail', '$envmap',
            '$flowmap', '$flow_noise_texture', '$refracttexture', '$reflecttexture', '%tooltexture'}
NON_FILE_PARAMETERS = {'$forceenvmap', '$lightmap', '$lightmapwaterfog',
                       '$envmaptint', '$envmapcontrast', '$envmapsaturation', '$envmapfresnel'}
SHADERS = ('water_ps40.vcs', 'water_vs40.vcs')
TOKEN = re.compile(r'\s+|//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"|[{}]|[^\s{}"]+', re.S)


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def resource_name(value):
    value = value.replace('\\', '/')
    if (not re.fullmatch(r'[A-Za-z0-9_./-]+', value) or
            any(part in ('', '.', '..') for part in value.split('/'))):
        raise ValueError(f'unsupported resource path: {value!r}')
    return value.lower()


def file_in(root, relative):
    path = root
    for part in relative.split('/'):
        path /= part
        if linked(path):
            raise ValueError(f'linked resource: {relative}')
    return path


def parse_water(text):
    """Read simple Water KeyValues, preserving repeated keys and nested blocks.

    Patch/include directives, conditions and other shaders fail explicitly.
    Nested proxy values are parsed but never mistaken for texture resources.
    """
    tokens, position = [], 0
    for match in TOKEN.finditer(text):
        if match.start() != position:
            raise ValueError('invalid VMT token')
        position = match.end()
        token = match.group()
        if token.isspace() or token.startswith(('//', '/*')):
            continue
        if token.startswith('"'):
            # KeyValues path separators are often backslashes; only unescape
            # escaped quotes and escaped backslashes, not Python escapes.
            token = re.sub(r'\\(["\\])', r'\1', token[1:-1])
        tokens.append(token)
    if position != len(text):
        raise ValueError('unterminated VMT string')
    index = 0

    def block(depth=0):
        nonlocal index
        if depth > 32 or index >= len(tokens) or tokens[index] != '{':
            raise ValueError('invalid or excessively nested VMT block')
        index += 1
        entries = []
        while index < len(tokens) and tokens[index] != '}':
            key = tokens[index]
            index += 1
            if (key == '{' or key.startswith(('[', '#')) or
                    key.lower() in {'include', 'insert', 'replace'} or index >= len(tokens)):
                raise ValueError('unsupported VMT condition/directive or missing value')
            if tokens[index] == '{':
                value = block(depth + 1)
            else:
                value = tokens[index]
                index += 1
                if value == '}' or value.startswith('#'):
                    raise ValueError('unsupported VMT condition/directive or missing value')
            entries.append((key.lower(), value))
        if index >= len(tokens):
            raise ValueError('unterminated VMT block')
        index += 1
        return entries

    if not tokens or tokens[0].lower() != 'water':
        raise ValueError('only direct Water materials are supported')
    index = 1
    entries = block()
    if index != len(tokens):
        raise ValueError('trailing VMT tokens or unsupported condition')
    return entries


def audit(source, shader_source, materials):
    for root in (source, shader_source):
        if linked(root) or not root.is_dir():
            raise ValueError('expected unlinked explicit material and shader source directories')
    source, shader_source = source.resolve(), shader_source.resolve()
    result = {'materials': [], 'files': {}, 'runtime_resources': [], 'issues': [],
              'scope': 'Known direct Water VMT dependencies only. Patch/includes, conditions, '
                       'other shaders, proxies other than TextureScroll/WaterLOD and unknown '
                       'texture/material parameters are unsupported. VTF headers and nonempty '
                       'caches are checked, not decoded. Supply caches '
                       'to pack_tf1_shaders.py: loose cache presence does not prove VPK mounting '
                       'or rendering. This does not certify a complete map package.'}

    def record(root, relative, kind):
        path = file_in(root, relative)
        if not path.is_file():
            result['issues'].append(f'missing {kind}: {relative}')
            return None
        size = path.stat().st_size
        if size == 0 or size > 256 * 1024 * 1024:
            result['issues'].append(f'empty or oversized {kind}: {relative}')
            return None
        # Hash without loading texture payloads into memory.
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            prefix = stream.read(4)
            digest.update(prefix)
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if kind == 'texture' and prefix != b'VTF\0':
            result['issues'].append(f'invalid VTF header: {relative}')
        result['files'][relative] = {'kind': kind, 'bytes': size, 'sha256': digest.hexdigest()}
        return path

    pending = [resource_name(name).removesuffix('.vmt') for name in materials]
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        seen.add(name)
        if len(seen) > 4096:
            raise ValueError('too many bottom-material dependencies')
        path = record(source, f'materials/{name}.vmt', 'material')
        if path is None:
            continue
        if path.stat().st_size > 1024 * 1024:
            result['issues'].append(f'oversized VMT: {name}')
            continue
        try:
            entries = parse_water(path.read_text(encoding='utf-8-sig'))
            result['materials'].append(name)
            for key, value in entries:
                if key == 'proxies' and isinstance(value, list):
                    for proxy, parameters in value:
                        if (proxy not in {'texturescroll', 'waterlod'} or
                                not isinstance(parameters, list) or
                                any(isinstance(v, list) for _, v in parameters)):
                            result['issues'].append(f'unsupported proxy: {name} {proxy}')
                    continue
                if key == '$bottommaterial' and isinstance(value, str):
                    pending.append(resource_name(value).removesuffix('.vmt'))
                elif key in TEXTURES and isinstance(value, str):
                    if value.lower().startswith('_rt_') or (key == '$envmap' and value.lower() == 'env_cubemap'):
                        result['runtime_resources'].append({'material': name, 'parameter': key, 'value': value})
                        continue
                    texture = resource_name(value).removesuffix('.vtf')
                    relative = f'materials/{texture}.vtf'
                    # Native HDR cubemaps may have no non-HDR companion.
                    hdr = f'materials/{texture}.hdr.vtf'
                    if key == '$envmap' and not file_in(source, relative).is_file() and file_in(source, hdr).is_file():
                        relative = hdr
                    record(source, relative, 'texture')
                elif key in TEXTURES or key == '$bottommaterial' or isinstance(value, list):
                    result['issues'].append(f'unsupported dependency/block: {name} {key}')
                elif key not in NON_FILE_PARAMETERS and any(part in key for part in ('texture', 'material', 'map')):
                    result['issues'].append(f'unknown dependency parameter: {name} {key}')
        except (ValueError, UnicodeError) as exc:
            result['issues'].append(f'{name}: {exc}')
    for shader in SHADERS:
        record(shader_source, f'shaders/fxc/{shader}', 'shader cache')
    result['materials'].sort()
    result['runtime_resources'].sort(key=lambda item: (item['material'], item['parameter']))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Explicit tree containing materials/')
    parser.add_argument('--shader-source', type=Path, required=True, help='Explicit tree containing shaders/fxc/')
    parser.add_argument('--material', action='append', required=True, help='Water material name; repeat for multiple roots')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.source, args.shader_source, args.material)
    args.output.write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    return int(bool(report['issues']))


if __name__ == '__main__':
    raise SystemExit(main())
