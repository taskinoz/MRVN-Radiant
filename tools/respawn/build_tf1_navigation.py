#!/usr/bin/env python3
"""Build an original v29 AIN through an owned R1Delta session, then package its CRC.

Requires the ARES R1 map adapter with explicit native-AIN initialization support.
This exports navigation data; fresh-load routing and release acceptance are separate.
Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

from tf1_navigation_crc import PROFILE, calculate, graph_copy, regular_file


def validate_runtime(app, game):
    fingerprints = {}
    for label, path in (
            ('r1_engine_sha256', Path(game) / 'bin/x64_retail/engine.dll'),
            ('r1_server_sha256', Path(app) / 'r1delta/bin/server.dll')):
        path = regular_file(path)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        fingerprints[label] = digest.hexdigest()
        if fingerprints[label] != PROFILE[label]:
            raise ValueError('native AIN export requires the pinned runtime profile: ' + label)
    return fingerprints


def export(harness, maps, name, output, game=None, app=None, timeout=300):
    if getattr(harness, 'AIN_BUILD_FLAG', None) != '-r1delta_build_ain_no_existing':
        raise ValueError('ARES adapter lacks explicit native AIN initialization support; update ARES')
    if not re.fullmatch(r'[A-Za-z0-9_]+', name):
        raise ValueError('invalid map name')
    maps, output = Path(maps), Path(output)
    calculated = calculate(maps / (name + '.bsp'))  # reject unsupported layouts before mutation
    if output.exists() or output.is_symlink():
        raise FileExistsError('export output must be a new directory')
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > 1800:
        raise ValueError('timeout must be between 0 and 1800 seconds')
    app, game = app or harness.find_app(), game or harness.find_game()
    fingerprints = validate_runtime(app, game)
    output.mkdir(parents=True, exist_ok=False)
    package = output / 'maps'
    (package / 'graphs').mkdir(parents=True)
    for entry in calculated['inputs']:
        source = Path(entry['path'])
        shutil.copyfile(source, package / source.name)
    # A new package starts without an AIN; the exporter cannot accidentally
    # normalize a pre-existing staged graph or overwrite a source graph.
    native = (output / 'native-built.ain').resolve()
    session = harness.prepare(app, game, package, name)
    session['build_navigation'] = True
    previous = harness.run_checks

    def build(control, checks, pid, folder, events, screenshots, *rest):
        control.console('sv_cheats 1')
        control.console('updateain "' + native.as_posix() + '"')
        deadline = time.monotonic() + min(timeout, 90)
        while not native.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError('native updateain did not export a graph')
            time.sleep(0.25)
        events.append('AIN_EXPORT bytes=' + str(native.stat().st_size))

    harness.run_checks = build
    try:
        report = harness.attempt(session, harness.validate_checks({}), output, timeout)
    finally:
        harness.run_checks = previous
        harness.cleanup(session)
    (output / 'native-report.json').write_bytes((json.dumps(report, indent=2) + '\n').encode('utf-8'))
    if not report['loaded'] or not report['finished'] or report['errors'] or not native.is_file():
        raise RuntimeError('native AIN export failed; inspect native-report.json')
    crc = graph_copy(package / (name + '.bsp'), native, package / 'graphs' / (name + '.ain'))
    harness.navigation_graph(package / (name + '.bsp'))  # bounded node/link framing preflight
    result = {'map': name, 'verification': 'native export and offline CRC; fresh-load route acceptance required',
              'runtime_fingerprints': fingerprints,
              'native_graph_sha256': hashlib.sha256(native.read_bytes()).hexdigest(), 'crc': crc}
    (output / 'manifest.json').write_bytes((json.dumps(result, indent=2) + '\n').encode('utf-8'))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ares', required=True, type=Path, help='ARES checkout directory')
    parser.add_argument('--maps', required=True, type=Path)
    parser.add_argument('--map', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--game', type=Path)
    parser.add_argument('--r1delta', type=Path)
    parser.add_argument('--timeout', type=float, default=300)
    args = parser.parse_args()
    adapter = (args.ares / 'harnesses/adapters').resolve(strict=True)
    if not (adapter / 'r1_harness.py').is_file():
        parser.error('--ares does not contain the R1 map adapter')
    sys.path.insert(0, str(adapter))
    harness = importlib.import_module('r1_harness')
    result = export(harness, args.maps, args.map, args.output, args.game, args.r1delta, args.timeout)
    print(json.dumps({'map': result['map'], 'entity_crc': result['crc']['entity_crc'],
                      'verification': result['verification']}, indent=2))


if __name__ == '__main__':
    main()
