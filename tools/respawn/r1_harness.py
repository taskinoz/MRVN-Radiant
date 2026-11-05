"""Load a compiled Titanfall 1 map in R1Delta and run traces, drops and views.

R1Delta addons are loose directories mounted from <game>/r1/addons. The map is
installed as a temporary addon, a script is run after the local match reaches
Playing, and the result is read from a fresh condump. The addon and addonlist
entry are removed afterwards. Copyright (C) 2026 MRVN-Radiant contributors.
GPL-2.0-or-later.

  python tools/respawn/r1_harness.py --game "D:/Games/Titanfall" \\
      --maps BUILD_DIR --map mp_name --checks checks.json --output REPORT_DIR

checks.json: {"traces": [[x, y, z, ex, ey, ez], ...],
              "views": [[x, y, z, pitch, yaw], ...],
              "drops": [[x, y, z], ...]}   physics objects; their resting height is logged
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import uuid

ADDON_PREFIX = 'MRVN.TF1Harness.'
OWNER = '.mrvn-harness-owner.json'
MODEL = 'models/weapons/grenades/m20_f_grenade.mdl'
ADDON_LIST = re.compile(r'\s*"AddonList"\s*\{[^{}]*\}\s*', re.I | re.S)
MAP_NAME = re.compile(r'[A-Za-z0-9_]+')

SCRIPT = r'''
::MRVN_%ID%_Traces <- %TRACES%
::MRVN_%ID%_Views <- %VIEWS%
::MRVN_%ID%_Drops <- %DROPS%

function MRVN_%ID%_Log( text ) { printl( "[MRVN:%ID%] " + text ) }

function MRVN_%ID%_Attach()
{
	WaittillGameStateOrHigher( eGameState.Playing )
	while ( GetPlayerArray().len() == 0 ) wait 0.5
	wait 2
	thread MRVN_%ID%_Run( GetPlayerArray()[0] )
}

function MRVN_%ID%_Run( player )
{
	player.EndSignal( "OnDestroy" )
	MRVN_%ID%_Log( "BEGIN" )
	foreach ( i, t in MRVN_%ID%_Traces )
	{
		local result = TraceLine( Vector( t[0], t[1], t[2] ), Vector( t[3], t[4], t[5] ), null, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
		MRVN_%ID%_Log( "TRACE " + i + " fraction=" + result.fraction + " end=" + result.endPos.z + " solid=" + result.startSolid )
	}
	local dropped = []
	foreach ( i, d in MRVN_%ID%_Drops )
	{
		local prop = CreateEntity( "prop_physics" )
		prop.kv.model = "%MODEL%"
		prop.kv.minhealthdmg = 9999
		prop.SetOrigin( Vector( d[0], d[1], d[2] ) )
		DispatchSpawn( prop, false )
		prop.SetModel( "%MODEL%" )
		dropped.append( prop )
	}
	if ( dropped.len() )
		wait 4
	foreach ( i, prop in dropped )
		MRVN_%ID%_Log( "DROP " + i + " z=" + ( IsValid( prop ) ? prop.GetOrigin().z : "gone" ) )
	foreach ( i, v in MRVN_%ID%_Views )
	{
		player.SetOrigin( Vector( v[0], v[1], v[2] ) )
		player.SetAngles( Vector( v[3], v[4], 0 ) )
		player.SetVelocity( Vector( 0, 0, 0 ) )
		wait 2
		MRVN_%ID%_Log( "VIEW " + i )
		ServerCommand( "screenshot" )
		wait 2
	}
	MRVN_%ID%_Log( "DONE" )
	wait 1
	ServerCommand( "condump" )
}

thread MRVN_%ID%_Attach()
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linked(path):
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def resolve_dir(path, label):
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f'{label} is not a directory: {path}')
    return path


def sq(rows):
    return '[' + ', '.join('[' + ', '.join(f'{float(v):.3f}' for v in row) + ']' for row in rows) + ']'


def validate_checks(checks):
    checks = checks or {}
    if not isinstance(checks, dict):
        raise ValueError('checks must be a JSON object')
    result = {}
    for key, width in (('traces', 6), ('views', 5), ('drops', 3)):
        rows = checks.get(key, [])
        if not isinstance(rows, list) or any(not isinstance(row, list) or len(row) != width for row in rows):
            raise ValueError(f'checks.{key} must be a list of {width}-number lists')
        result[key] = rows
    return result


def find_app(explicit=None):
    if explicit:
        return resolve_dir(explicit, 'R1Delta app')
    root = Path(os.environ.get('LOCALAPPDATA', '')) / 'R1Delta'
    candidates = []
    for path in root.glob('app-*'):
        match = re.fullmatch(r'app-(\d+(?:\.\d+)*)', path.name)
        if match and (path / 'r1delta' / 'GameInfo.txt').is_file():
            candidates.append((tuple(int(v) for v in match.group(1).split('.')), path))
    if not candidates:
        raise ValueError('could not find %LOCALAPPDATA%/R1Delta/app-*; pass --r1delta')
    return max(candidates, key=lambda item: item[0])[1]


def find_game(explicit=None):
    if explicit:
        return resolve_dir(explicit, 'Titanfall install')
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\R1Delta') as key:
            value, _ = winreg.QueryValueEx(key, 'InstallPath')
        if value:
            return resolve_dir(value, 'Titanfall install')
    except (ImportError, FileNotFoundError, OSError):
        pass
    raise ValueError('could not read R1Delta InstallPath; pass --game')


def prepare(app, game, maps, map_name, checks, run_id=None):
    app = resolve_dir(app, 'R1Delta app')
    game = resolve_dir(game, 'Titanfall install')
    r1 = game / 'r1'
    if not (app / 'Titanfall.exe').is_file():
        raise ValueError(f'missing R1Delta launcher: {app / "Titanfall.exe"}')
    if not (r1 / 'GameInfo.txt').is_file():
        raise ValueError(f'expected the Titanfall install containing r1/: {game}')
    if not (game / 'vpk').is_dir():
        raise ValueError(f'expected Titanfall VPKs in {game / "vpk"}')
    if not MAP_NAME.fullmatch(map_name):
        raise ValueError('invalid map name')
    maps = resolve_dir(maps, 'map build')
    source = maps / 'maps' if (maps / 'maps' / f'{map_name}.bsp').is_file() else maps
    if not (source / f'{map_name}.bsp').is_file():
        raise ValueError(f'missing compiled map: {maps / (map_name + ".bsp")}')
    checks = validate_checks(checks)
    run_id = run_id or uuid.uuid4().hex
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('invalid run ID')

    addon = r1 / 'addons' / (ADDON_PREFIX + run_id)
    cfg = r1 / 'cfg' / f'mrvn_harness_{run_id}.cfg'
    listing = r1 / 'addonlist.txt'
    for path in (listing, cfg, addon, addon.parent, cfg.parent, r1):
        if linked(path):
            raise ValueError(f'refusing linked harness path: {path}')
    if addon.exists() or cfg.exists():
        raise ValueError('harness path already exists')

    listing_existed = listing.exists()
    original = listing.read_text(encoding='utf-8-sig') if listing_existed else '"AddonList"\n{\n}\n'
    if not ADDON_LIST.fullmatch(original):
        raise ValueError('unsupported addon list; refusing to rewrite it')

    addon.parent.mkdir(parents=True, exist_ok=True)
    addon.mkdir()
    (addon / OWNER).write_text(json.dumps({'run_id': run_id}), encoding='utf-8')
    try:
        target = addon / 'maps'
        target.mkdir()
        for item in source.iterdir():
            if item.suffix.lower() in ('.map', '.log', '.prt', '.srf') or item.name == OWNER:
                continue
            dest = target / item.name
            if item.is_dir():
                shutil.copytree(item, dest)
            else:
                shutil.copyfile(item, dest)

        (addon / 'addoninfo.txt').write_text(
            '"AddonInfo"\n{\n"addontitle" "MRVN TF1 Harness ' + run_id + '"\n'
            '"addonversion" "1"\n"addonauthor" "mrvn-radiant"\n'
            '"addonContent_Map" "1"\n"addonContent_Script" "1"\n}\n', encoding='utf-8')

        scripts = addon / 'scripts/vscripts'
        scripts.mkdir(parents=True)
        script_path = scripts / f'mrvn_harness_{run_id}.nut'
        script_path.write_text(
            SCRIPT.replace('%ID%', run_id)
            .replace('%TRACES%', sq(checks['traces']))
            .replace('%VIEWS%', sq(checks['views']))
            .replace('%DROPS%', sq(checks['drops']))
            .replace('%MODEL%', MODEL), encoding='utf-8')

        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            'developer 1\nsv_cheats 1\n'
            f'script IncludeFile("mrvn_harness_{run_id}")\n', encoding='utf-8')

        updated = original[:original.rfind('}')] + f'"{addon.name}" "1"\n' + original[original.rfind('}'):]
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text(updated, encoding='utf-8')

        return {
            'run_id': run_id, 'app': str(app), 'game': str(game), 'r1': str(r1),
            'addon': str(addon), 'cfg': str(cfg), 'listing': str(listing),
            'listing_existed': listing_existed, 'original_listing': original,
            'map': map_name, 'maps': str(maps), 'checks': checks,
            'prepared_at_ns': time.time_ns(),
            'addon_sha256': digest(addon / 'addoninfo.txt'),
            'script_sha256': digest(script_path),
            'cfg_sha256': digest(cfg),
        }
    except BaseException:
        shutil.rmtree(addon, ignore_errors=True)
        if cfg.exists():
            cfg.unlink()
        if listing.exists() and listing.read_text(encoding='utf-8-sig') == locals().get('updated'):
            if listing_existed:
                listing.write_text(original, encoding='utf-8')
            else:
                listing.unlink()
        raise


def cleanup(session):
    run_id = session['run_id']
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('invalid session ID')
    r1 = Path(session['r1']).resolve()
    addon = Path(session['addon']).resolve()
    cfg = Path(session['cfg']).resolve()
    if addon.parent != (r1 / 'addons').resolve() or addon.name != ADDON_PREFIX + run_id:
        raise ValueError('session addon path mismatch')
    if cfg.parent != (r1 / 'cfg').resolve() or cfg.name != f'mrvn_harness_{run_id}.cfg':
        raise ValueError('session cfg path mismatch')
    if not addon.is_dir():
        raise ValueError('session addon is missing')
    try:
        owner = json.loads((addon / OWNER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('session owner file is missing or invalid')
    if owner.get('run_id') != run_id:
        raise ValueError('session owner mismatch')
    if linked(cfg) or digest(cfg) != session['cfg_sha256']:
        raise ValueError('owned cfg changed; refusing removal')

    listing = r1 / 'addonlist.txt'
    text = listing.read_text(encoding='utf-8-sig') if listing.exists() else ''
    pattern = r'(?m)^"' + re.escape(addon.name) + r'"\s+"[01]"\s*\n?'
    updated, count = re.subn(pattern, '', text)
    if count != 1:
        raise ValueError('owned addon entry missing or ambiguous')

    shutil.rmtree(addon)
    cfg.unlink()
    if not session.get('listing_existed', True) and updated.strip() == '"AddonList"\n{\n}':
        listing.unlink()
    else:
        listing.write_text(updated, encoding='utf-8')


def collect(session, text):
    run_id = session['run_id']
    marker = f'[MRVN:{run_id}] '
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if marker + 'BEGIN' in line]
    if starts:
        text = ''.join(lines[starts[-1]:])
    events = [line.split(marker, 1)[1].rstrip('\r\n') for line in text.splitlines() if marker in line]
    issues = []
    if not starts:
        issues.append('run BEGIN boundary missing')
    if len(starts) > 1:
        issues.append('run ID reused; prepare a fresh session')
    if 'DONE' not in events:
        issues.append('run did not finish')
    for key, label in (('traces', 'TRACE'), ('drops', 'DROP'), ('views', 'VIEW')):
        for index in range(len(session['checks'].get(key, []))):
            if not any(event.startswith(f'{label} {index} ') or event == f'{label} {index}' for event in events):
                issues.append(f'{label} {index} missing')
    errors = [line for line in text.splitlines()
              if any(tag in line for tag in ('SCRIPT ERROR', 'CRASH HAS BEEN CAPTURED', 'EXCEPTION'))]
    if errors:
        issues.append('script error or crash in console dump')
    return {'events': events, 'errors': errors, 'issues': issues,
            'server_passed': not issues, 'finished': 'DONE' in events,
            'log_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def launch(session):
    env = os.environ.copy()
    env['FROM_DELTA_LAUNCHER'] = '1'
    env['__COMPAT_LAYER'] = 'NoDTToDITMouseBatch=1'
    env['ContentId'] = '1025161'
    app = Path(session['app'])
    game = Path(session['game'])
    prepend = [app / 'r1delta/bin_delta', app / 'r1delta/bin', game / 'bin/x64_retail',
               game / 'r1/bin/x64_retail']
    env['PATH'] = os.pathsep.join([str(path) for path in prepend] + [env.get('PATH', '')])
    command = [str(app / 'Titanfall.exe'), '-game', 'r1',
               '-novid', '-windowed', '-w', '1280', '-h', '720',
               '+sv_lan', '1', '+sv_cheats', '1', '+developer', '1',
               '+exec', Path(session['cfg']).stem, '+map', session['map']]
    return subprocess.Popen(command, cwd=session['game'], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=20)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def wait_for_condump(session, process, timeout):
    r1 = Path(session['r1'])
    marker = f'[MRVN:{session["run_id"]}]'
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates = []
        for path in r1.glob('condump*.txt'):
            try:
                if path.stat().st_mtime_ns > session['prepared_at_ns'] and marker in path.read_text('utf-8', 'replace'):
                    candidates.append(path)
            except OSError:
                pass
        if candidates:
            path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
            time.sleep(1)
            return path, path.read_text('utf-8', 'replace')
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.5)
    return None, ''


def screenshots(session):
    found = []
    for directory in (Path(session['r1']) / 'screenshots', Path(session['game']) / 'screenshots'):
        if not directory.is_dir():
            continue
        for path in directory.iterdir():
            if path.is_file() and path.suffix.lower() in ('.tga', '.jpg', '.png') and path.stat().st_mtime_ns > session['prepared_at_ns']:
                found.append({'path': str(path), 'sha256': digest(path)})
    return found


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--game', type=Path, help='Titanfall install containing r1/ and vpk/')
    p.add_argument('--r1delta', type=Path, help='R1Delta app-* folder (auto-detected)')
    p.add_argument('--maps', type=Path, help='Folder with the compiled .bsp and .ent files')
    p.add_argument('--map', help='Map name without .bsp')
    p.add_argument('--checks', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--session', type=Path, help='Reuse or write the staging session here')
    p.add_argument('--collect-log', type=Path, help='Parse an existing condump instead of launching')
    p.add_argument('--stage-only', action='store_true', help='Stage the addon and print the exec command')
    p.add_argument('--keep', action='store_true', help='Leave the addon and addonlist entry in place')
    p.add_argument('--timeout', type=int, default=300)
    p.add_argument('--attempts', type=int, default=2)
    args = p.parse_args(argv)
    if not 0 <= args.timeout <= 3600:
        p.error('timeout must be between 0 and 3600 seconds')
    if args.attempts < 1:
        p.error('attempts must be at least 1')

    args.output.mkdir(parents=True, exist_ok=True)
    session_path = args.session or args.output / 'r1_session.json'
    if args.session and args.session.exists():
        session = json.loads(session_path.read_text(encoding='utf-8'))
    else:
        if not (args.maps and args.map):
            p.error('--maps and --map are required for a new session')
        checks = json.loads(args.checks.read_text()) if args.checks else {}
        session = prepare(find_app(args.r1delta), find_game(args.game), args.maps, args.map, checks)
        session_path.write_text(json.dumps(session, indent=2), encoding='utf-8')

    if args.stage_only:
        print(f'staged {session["addon"]}')
        print(f'session {session_path}')
        print(f'In a local R1Delta match: exec {Path(session["cfg"]).stem}')
        return 0

    process = None
    text = ''
    path = None
    attempts = 0
    try:
        if args.collect_log:
            path = args.collect_log
            text = path.read_text('utf-8', 'replace')
        else:
            for attempt in range(args.attempts):
                attempts = attempt + 1
                session['prepared_at_ns'] = time.time_ns()
                process = launch(session)
                path, text = wait_for_condump(session, process, args.timeout)
                exit_code = process.poll()
                stop(process)
                process = None
                if text:
                    break
                reason = f'process exited with code {exit_code}' if exit_code is not None else 'timed out'
                print(f'attempt {attempt + 1}: no condump from the run ({reason})', flush=True)
        result = collect(session, text)
    finally:
        stop(process)
        if not args.keep:
            cleanup(session)

    shots = screenshots(session)
    report = {**session, **result, 'output': str(args.output),
              'log': str(path) if path else None, 'attempts': attempts,
              'screenshots': shots, 'kept': args.keep}
    if path and Path(path).exists():
        snapshot = args.output / 'r1_condump.txt'
        snapshot.write_text(text, encoding='utf-8')
        report['console_snapshot'] = str(snapshot)
    report.pop('original_listing', None)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('server_passed', 'finished', 'issues', 'events')}, indent=2))
    return 0 if result['server_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
