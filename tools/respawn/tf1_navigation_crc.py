#!/usr/bin/env python3
"""Offline v29 AIN CRC calculation for embedded authored maps, not AI certification.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original implementation from local native evidence; see RESPAWN_TF1_PHASE2.md.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import zlib

from entity_text import parse_entities, parse_partition
from inspect_bsp import FormatError, inspect, digest_region

MAX_ENTITY_BYTES = 64 * 1024 * 1024
MAX_GRAPH_BYTES = 64 * 1024 * 1024
PROFILE = {
    'r1_engine_sha256': '0214a40436eca77f160d12763ab8f392a8ce2268bfe0a973188e426ae4c0263c',
    'r1_server_sha256': '50faad928e0715a51ad624d0a3eb8f00f7ffad9e66258dc95c960f9d11ff41e4',
    'tfo_engine_sha256': '39e2a1c83b7bea3fa1a2f98ecc6cde3016e3567a1bc89cf8926d8a613dc62ad1',
    'tfo_server_sha256': '8dabdd4f46218bdd72bd9c4ea53d24178c7974ec4277f6872f671ac1fe99dd7b',
}


def raw_crc(data, value=0xffffffff):
    """Native CRC32_ProcessBuffer state, without the final XOR."""
    return zlib.crc32(data, value ^ 0xffffffff) ^ 0xffffffff


def regular_file(path, limit=None):
    path = Path(path)
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400 or not path.is_file():
        raise FormatError(f'refusing linked or non-file input: {path.name}')
    if limit is not None and info.st_size > limit:
        raise FormatError(f'input exceeds size bound: {path.name}')
    return path


def navigation_spans(data):
    """Return raw simple quoted entity spans selected by the native class filter.

    Restrict selected records instead of guessing native escape/truncation behavior.
    Other entities still receive the shared strict KeyValues syntax validation.
    """
    if len(data) > MAX_ENTITY_BYTES:
        raise FormatError('entity text exceeds size bound')
    text = data.decode('latin1')  # one character per byte preserves source offsets
    entities = parse_entities(text)
    # Syntax has already been checked. Quoted strings and comments hide braces.
    tokens = list(re.finditer(r'//[^\n]*(?:\n|$)|"(?:\\[\\"]|[^"])*"|[{}]', text))
    blocks, opening, end = [], None, None
    for token in tokens:
        value = token[0]
        if value.startswith('//'):
            continue
        if value == '{':
            opening, end = token.end(), token.end()
        elif value == '}':
            blocks.append((opening, end))
            opening = None
        else:
            end = token.end()
    if len(blocks) != len(entities):
        raise FormatError('entity span framing differs from parsed records')
    result = []
    for pairs, (begin, end) in zip(entities, blocks):
        classes = [v for k, v in pairs if k.casefold() == 'classname']
        if len(classes) > 1:
            raise FormatError('duplicate classname is unsupported for navigation CRC')
        if not classes:
            continue
        cls = classes[0]
        if not (cls.startswith('info_node') or cls in ('info_hint', 'traverse', 'trigger_indoor_area')):
            continue
        if any(k != 'classname' and k.casefold() == 'classname' for k, _ in pairs):
            raise FormatError('noncanonical classname key is unsupported for navigation CRC')
        span = data[begin:end]
        if b'\\' in span or any(len(k.encode('latin1')) >= 2048 or len(v.encode('latin1')) >= 2048 for k, v in pairs):
            raise FormatError('escaped or oversized navigation entity tokens are unsupported')
        result.append((cls, span))
    return result


def calculate(bsp):
    bsp = regular_file(bsp)
    inventory = inspect(bsp)
    if inventory['version_raw'] != 29 or inventory['byte_order'] != 'little':
        raise FormatError('navigation CRC requires little-endian BSP v29')
    if any(row['severity'] == 'error' for row in inventory['issues']):
        raise FormatError('BSP directory validation failed')
    lumps = inventory['lumps']
    if any(row['external_files'] or row['fourcc'] for row in lumps):
        raise FormatError('external BSP lump overrides and compressed lumps are unsupported')
    value = 0xffffffff
    inputs = [{'path': str(bsp.resolve())}]
    with bsp.open('rb') as stream:
        inputs[0]['sha256'] = digest_region(stream, 0, inventory['size'])
        for entry in sorted(lumps, key=lambda row: row['offset']):
            if entry['index'] in (0, 24) or not entry['length']:
                continue
            stream.seek(entry['offset'])
            remaining = entry['length']
            while remaining:
                data = stream.read(min(remaining, 1024 * 1024))
                if not data:
                    raise FormatError('BSP truncated during CRC calculation')
                value = raw_crc(data, value)
                remaining -= len(data)
        def payload(index):
            entry = lumps[index]
            if entry['length'] > MAX_ENTITY_BYTES:
                raise FormatError('entity lump exceeds size bound')
            stream.seek(entry['offset'])
            return stream.read(entry['length'])
        embedded, declaration = payload(0), payload(24)
    bodies = [('embedded', embedded)]
    declaration = declaration.rstrip(b'\0')
    if declaration:
        try:
            names = declaration.decode('ascii').split()
        except UnicodeDecodeError as exc:
            raise FormatError('invalid entity partition declaration') from exc
        if (not names or names[0] != '01*' or len(set(n.casefold() for n in names[1:])) != len(names)-1 or
                any(not re.fullmatch(r'[A-Za-z0-9_]+', n) for n in names[1:])):
            raise FormatError('unsupported entity partition declaration')
        for name in names[1:]:
            path = regular_file(bsp.with_name(bsp.stem + '_' + name + '.ent'), MAX_ENTITY_BYTES)
            data = path.read_bytes()
            parse_partition(data)
            bodies.append((name, data.partition(b'\n')[2]))
            inputs.append({'path': str(path.resolve()), 'sha256': hashlib.sha256(data).hexdigest()})
    base = value
    counts = {}
    for name, body in bodies:
        for cls, span in navigation_spans(body):
            value = raw_crc(span, value)
            counts[cls] = counts.get(cls, 0) + 1
    return {'scope': 'embedded uncompressed v29 and simple quoted navigation entities in declared ENTITIES01 partitions',
            'verification': 'offline calculation; native acceptance and graph semantics are separate',
            'profile': PROFILE, 'revision': inventory['revision'], 'map_crc': base,
            'entity_crc': value, 'navigation_entities': counts, 'inputs': inputs}


def graph_copy(bsp, graph, output=None):
    report = calculate(bsp)
    graph = regular_file(graph, MAX_GRAPH_BYTES)
    data = graph.read_bytes()
    if len(data) < 24:
        raise FormatError('truncated AIN header')
    version, revision, crc, nodes = struct.unpack_from('<4I', data)
    if version != 54 or revision != report['revision'] or not 1 <= nodes <= 32767:
        raise FormatError('AIN version, map revision or node count mismatch')
    if 16 + 68 * nodes + 8 > len(data):
        raise FormatError('truncated AIN nodes')
    report['graph'] = {'path': str(graph.resolve()), 'sha256': hashlib.sha256(data).hexdigest(),
                       'file_crc': crc, 'crc_matches': crc == report['entity_crc'],
                       'framing': 'header/node size only; use native adapter for fuller preflight'}
    if output is not None:
        output = Path(output)
        patched = data[:8] + struct.pack('<I', report['entity_crc']) + data[12:]
        # Exclusive creation: never replace the source or an existing graph.
        with output.open('xb') as stream:
            stream.write(patched)
        report['output_graph'] = {'path': str(output.resolve()), 'sha256': hashlib.sha256(patched).hexdigest()}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bsp', required=True, type=Path)
    parser.add_argument('--graph', type=Path)
    parser.add_argument('--output-graph', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output_graph and not args.graph:
        parser.error('--output-graph requires --graph')
    report = graph_copy(args.bsp, args.graph, args.output_graph) if args.graph else calculate(args.bsp)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
    else:
        print(text, end='')
    return int(bool(args.graph and not args.output_graph and not report['graph']['crc_matches']))


if __name__ == '__main__':
    sys.exit(main())
