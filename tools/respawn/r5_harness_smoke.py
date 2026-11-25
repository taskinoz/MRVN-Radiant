#!/usr/bin/env python3
"""Boot/load/reload R5 through HTTP and optionally probe Coliseum collision.

Original implementation, GPL-2.0-or-later. Rendering is not tested headlessly.
"""
import argparse
import json
from pathlib import Path
import re
import time

from r5_harnessctl import call


def run(args):
    report = dict(started=time.time(), render_verified=False, checks=[])
    if args.boot:
        report['boot'] = call(args.connection, 'boot', dict(mode='dedicated', playlist_file=args.playlist_file))
    request = dict(map=args.map, playlist=args.playlist, gamemode=args.gamemode, timeout=args.timeout)
    for attempt in range(2 if args.reload else 1):
        result = call(args.connection, 'load', request)
        report['checks'].append(dict(kind='reload' if attempt else 'load', result=result))
        if result.get('last_load', {}).get('state') != 'loaded':
            report['passed'] = False
            return report
    if args.coliseum_checks:
        if args.map != 'mp_mrvn_coliseum_s3':
            raise ValueError('Coliseum probes apply only to mp_mrvn_coliseum_s3')
        # Expected fractions come from independent source geometry recovery.
        probes = (
            ('CENTER', '<0,0,128>', '<0,0,-1024>', .10549986817),
            ('SOUTH', '<0,-600,128>', '<0,-600,-1024>', .1119791667),
            ('EAST', '<600,0,128>', '<600,0,-1024>', .1119791667),
            ('WEST', '<-600,0,128>', '<-600,0,-1024>', .1119791667),
            ('NORTH', '<0,600,128>', '<0,600,-1024>', .1119791667),
            ('DOME_EAST', '<0,0,400>', '<1600,0,400>', .6399973843),
            ('DOME_WEST', '<0,0,400>', '<-1600,0,400>', .6399983343),
            ('DOME_ROOF', '<0,0,128>', '<0,0,1200>', .7761176381),
        )
        for name, start, end, expected in probes:
            marker = 'MRVN_SMOKE_' + name
            command = f'script print("{marker} " + TraceLine({start},{end},null,TRACE_MASK_NPCWORLDSTATIC,TRACE_COLLISION_GROUP_NONE).fraction)'
            result = call(args.connection, 'command', dict(text=command))
            output = '\n'.join(e['text'] for e in result.get('events', []))
            match = re.search(re.escape(marker) + r'\s+([0-9.]+)', output)
            actual = float(match[1]) if match else None
            passed = result.get('acknowledged', False) and actual is not None and abs(actual-expected) < .0001
            report['checks'].append(dict(kind='collision', name=name, expected=expected, actual=actual, passed=passed))
        report['passed'] = all(c.get('passed', True) for c in report['checks'])
    else:
        report['passed'] = True
    report['finished'] = time.time()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--connection', type=Path, required=True)
    parser.add_argument('--map', required=True)
    parser.add_argument('--playlist', required=True)
    parser.add_argument('--gamemode', required=True)
    parser.add_argument('--playlist-file', default='playlists_mrvn_coliseum.txt')
    parser.add_argument('--timeout', type=int, default=45)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--boot', action='store_true')
    parser.add_argument('--reload', action='store_true')
    parser.add_argument('--coliseum-checks', action='store_true')
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, RuntimeError, ValueError) as error:
        report = dict(passed=False, render_verified=False, error=str(error))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
