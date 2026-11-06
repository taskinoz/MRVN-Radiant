"""Load a Titanfall 1 map in R1Delta and run traces, hulls, drops and views.

R1Delta ships a JSON-RPC (MCP) control server, enabled with -usemcp and
started with +mcp_start_http PORT on 127.0.0.1. The harness launches R1Delta as
its own launcher does, loads the map through that server, and runs server
Squirrel directly, reading printed results back without console dumps. A
compiled map is mounted as a temporary owned addon in <game>/r1/addons; omit
--maps to test a retail map. Copyright (C) 2026 MRVN-Radiant contributors.
GPL-2.0-or-later.

  python tools/respawn/r1_harness.py --maps BUILD_DIR --map mp_name \\
      --checks checks.json --output REPORT_DIR

checks.json uses the TFO harness schema (tools/respawn/tfo_harness.py):
  traces [[x,y,z,ex,ey,ez]], hulls [[x,y,z,ex,ey,ez,minx,miny,minz,maxx,maxy,maxz]],
  views [[x,y,z,pitch,yaw]], drops [[x,y,z]], drop_models, drop_wait,
  drop_samples, expect {trace_z, hull_z, drop_z}. Events and report.json match
  that harness, so results from both engines compare line for line.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tfo_harness import capture_window, expectation_errors, height_expectations  # noqa: E402

ADDON_PREFIX = 'MRVN.TF1Harness.'
OWNER = '.mrvn-harness-owner.json'
# Barrels spawn as physics props in R1Delta; crate.mdl and projectile_rocket.mdl do not.
DEFAULT_MODEL = 'models/containers/barrel.mdl'
ADDON_LIST = re.compile(r'\s*"AddonList"\s*\{[^{}]*\}\s*', re.I | re.S)
MAP_NAME = re.compile(r'[A-Za-z0-9_]+')
MODEL_NAME = re.compile(r'models/[A-Za-z0-9_/-]+\.mdl')
MODEL_EXTENSIONS = {'.mdl', '.vvd', '.vvc', '.vtx', '.phy', '.ani', '.vcs'}
PROTOCOL = '2025-06-18'
BATCH = 120  # rows per Squirrel call; R1Delta captures at most 500 output lines


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def linked(path):
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def resolve_dir(path, label):
    path = Path(path).resolve(strict=True)
    if not path.is_dir():
        raise ValueError(f'{label} is not a directory: {path}')
    return path


def finite_rows(rows, width, label):
    if not isinstance(rows, list) or any(
            not isinstance(row, list) or len(row) != width or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in row) for row in rows):
        raise ValueError(f'checks.{label} must be a list of {width}-number lists')
    return rows


def validate_checks(checks):
    checks = checks or {}
    if not isinstance(checks, dict):
        raise ValueError('checks must be a JSON object')
    result = {key: finite_rows(checks.get(key, []), width, key)
              for key, width in (('traces', 6), ('hulls', 12), ('views', 5), ('drops', 3))}
    if any(row[6 + i] > row[9 + i] for row in result['hulls'] for i in range(3)):
        raise ValueError('hull mins must not exceed maxs')
    models = checks.get('drop_models', [])
    if (not isinstance(models, list) or (models and len(models) != len(result['drops'])) or
            any(not isinstance(m, str) or not MODEL_NAME.fullmatch(m) or '..' in m.split('/') for m in models)):
        raise ValueError('drop_models must match drops and contain models/... .mdl paths')
    wait = checks.get('drop_wait', 4)
    if type(wait) not in (int, float) or not math.isfinite(wait) or not 0 < wait <= 120:
        raise ValueError('drop_wait must be a positive duration of at most 120 seconds')
    result.update(drop_models=models, drop_wait=float(wait), drop_samples=checks.get('drop_samples', False) is True,
                  expect=checks.get('expect', {}))
    height_expectations(result['expect'])  # reject malformed expectations before launching
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


def model_files(source, models):
    """Loose files of each drop model (.mdl and its .vvd/.vtx/.phy/... siblings)
    from a model tree such as Titanfall Online's assets_dump."""
    source = resolve_dir(source, 'model files')
    found = []
    for model in sorted(set(models)):
        stem = source / model[:-len('.mdl')]
        files = sorted(p for p in stem.parent.glob(stem.name + '.*')
                       if p.is_file() and p.suffix.lower() in MODEL_EXTENSIONS and not linked(p))
        if not any(p.suffix.lower() == '.mdl' for p in files):
            raise ValueError(f'{model} is not in {source}')
        found += [(p, Path(model).parent / p.name) for p in files]
    return found


def prepare(app, game, maps, map_name, models=None, run_id=None, model_source=None):
    """Stage an owned addon with the compiled map (maps=None: a retail map) and,
    when models is not None, a level-init precache script for drop models.

    R1Delta ignores PrecacheModel after level load, and a prop_physics with an
    unprecached model removes itself on spawn. With developer > 0, _mapspawn.nut
    includes test/myscript during level init on any map, so the harness stages
    that script (and launches with +developer 1). Per-map level scripts in an
    addon were not loaded.

    TF1 keeps most model render data in per-map VPKs (mp_common has only some
    .mdl/.phy files), and a custom map mounts no map VPK. Its models then load
    with empty keyvalues, so prop_physics finds no prop_data and deletes itself
    ("no propdata ... DELETED", server.dll 0x1c3c54). model_source copies each
    drop model's loose files into the addon."""
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
    run_id = run_id or uuid.uuid4().hex
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('invalid run ID')
    session = {'run_id': run_id, 'app': str(app), 'game': str(game), 'r1': str(r1), 'map': map_name, 'addon': None}
    if maps is None and models is None:
        return session
    staged = model_files(model_source, set(models or ()) | {DEFAULT_MODEL}) if model_source and models is not None else []
    source = None
    if maps is not None:
        maps = resolve_dir(maps, 'map build')
        source = maps / 'maps' if (maps / 'maps' / f'{map_name}.bsp').is_file() else maps
        if not (source / f'{map_name}.bsp').is_file():
            raise ValueError(f'missing compiled map: {maps / (map_name + ".bsp")}')
    hook = 'scripts/vscripts/test/myscript.nut'
    if models is not None:
        owners = [app / 'r1delta' / hook] + list((r1 / 'addons').glob('*/' + hook))
        if any(path.exists() for path in owners):
            raise ValueError(f'another {hook} exists; refusing to shadow it: {[str(p) for p in owners if p.exists()]}')

    addon = r1 / 'addons' / (ADDON_PREFIX + run_id)
    listing = r1 / 'addonlist.txt'
    for path in (listing, addon, addon.parent, r1):
        if linked(path):
            raise ValueError(f'refusing linked harness path: {path}')
    if addon.exists():
        raise ValueError('harness path already exists')
    listing_existed = listing.exists()
    original = listing.read_text(encoding='utf-8-sig') if listing_existed else '"AddonList"\n{\n}\n'
    if not ADDON_LIST.fullmatch(original):
        raise ValueError('unsupported addon list; refusing to rewrite it')

    addon.parent.mkdir(parents=True, exist_ok=True)
    addon.mkdir()
    (addon / OWNER).write_text(json.dumps({'run_id': run_id}), encoding='utf-8')
    updated = None
    try:
        if source is not None:
            target = addon / 'maps'
            target.mkdir()
            for item in source.iterdir():
                # Only the level itself: .bsp, its .bsp_lump files and .ent sidecars.
                if item.is_file() and item.name.startswith(map_name) and (
                        item.suffix.lower() in ('.bsp', '.ent', '.bsp_lump') or '.bsp.' in item.name):
                    shutil.copyfile(item, target / item.name)
        for item, relative in staged:
            (addon / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item, addon / relative)
        if models is not None:
            script = addon / hook
            script.parent.mkdir(parents=True)
            script.write_text(f'// MRVN harness {run_id}: precache drop models at level init\n' +
                              ''.join(f'PrecacheModel( "{m}" )\n' for m in sorted(set(models) | {DEFAULT_MODEL})) +
                              '::MRVN_PrecacheHook <- true\nprintl( "[MRVN] PRECACHE HOOK" )\n',
                              encoding='utf-8')
        (addon / 'addoninfo.txt').write_text(
            '"AddonInfo"\n{\n"addontitle" "MRVN TF1 Harness ' + run_id + '"\n'
            '"addonversion" "1"\n"addonauthor" "mrvn-radiant"\n'
            f'"addonContent_Map" "{int(source is not None)}"\n"addonContent_Script" "{int(models is not None)}"\n}}\n',
            encoding='utf-8')
        updated = original[:original.rfind('}')] + f'"{addon.name}" "1"\n' + original[original.rfind('}'):]
        listing.parent.mkdir(parents=True, exist_ok=True)
        listing.write_text(updated, encoding='utf-8')
    except BaseException:
        shutil.rmtree(addon, ignore_errors=True)
        if updated is not None and listing.exists() and listing.read_text(encoding='utf-8-sig') == updated:
            if listing_existed:
                listing.write_text(original, encoding='utf-8')
            else:
                listing.unlink()
        raise
    session.update(addon=str(addon), listing=str(listing), listing_existed=listing_existed,
                   addon_sha256=digest(addon / 'addoninfo.txt'))
    return session


def cleanup(session):
    """Remove only the addon and addon-list entry this session created."""
    if not session.get('addon'):
        return
    run_id = session['run_id']
    if not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('invalid session ID')
    r1 = Path(session['r1']).resolve()
    addon = Path(session['addon']).resolve()
    if addon.parent != (r1 / 'addons').resolve() or addon.name != ADDON_PREFIX + run_id:
        raise ValueError('session addon path mismatch')
    if not addon.is_dir():
        raise ValueError('session addon is missing')
    try:
        owner = json.loads((addon / OWNER).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        raise ValueError('session owner file is missing or invalid')
    if owner.get('run_id') != run_id or digest(addon / 'addoninfo.txt') != session['addon_sha256']:
        raise ValueError('session owner mismatch; refusing removal')
    listing = r1 / 'addonlist.txt'
    text = listing.read_text(encoding='utf-8-sig') if listing.exists() else ''
    updated, count = re.subn(r'(?m)^[ \t]*"' + re.escape(addon.name) + r'"\s+"[01]"\s*\n?', '', text)
    if count != 1:
        raise ValueError('owned addon entry missing or ambiguous')
    shutil.rmtree(addon)
    if not session.get('listing_existed', True) and updated.strip() == '"AddonList"\n{\n}':
        listing.unlink()
    else:
        listing.write_text(updated, encoding='utf-8')


class Control:
    """Minimal client for R1Delta's MCP HTTP server."""

    def __init__(self, port):
        self.url = f'http://127.0.0.1:{port}'
        self.session = None
        self.ident = 0

    def healthy(self):
        try:
            with urllib.request.urlopen(self.url + '/health', timeout=2) as reply:
                return json.loads(reply.read()).get('status') == 'ok'
        except (OSError, ValueError):
            return False

    def post(self, message, timeout=90):
        headers = {'Content-Type': 'application/json', 'MCP-Protocol-Version': PROTOCOL}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        request = urllib.request.Request(self.url + '/', json.dumps(message).encode(), headers)
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            body = reply.read()
            return reply.headers.get('Mcp-Session-Id'), json.loads(body) if body else {}

    def initialize(self):
        session, reply = self.post({'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {
            'protocolVersion': PROTOCOL, 'capabilities': {}, 'clientInfo': {'name': 'mrvn-r1-harness', 'version': '1'}}})
        if 'result' not in reply:
            raise RuntimeError(f'MCP initialize failed: {reply}')
        self.session = session
        self.post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})

    def call(self, name, arguments, timeout=90):
        self.ident += 1
        _, reply = self.post({'jsonrpc': '2.0', 'id': self.ident, 'method': 'tools/call',
                              'params': {'name': name, 'arguments': arguments}}, timeout)
        if 'result' not in reply:
            raise RuntimeError(f'MCP {name} failed: {reply.get("error", reply)}')
        return reply['result']

    def state(self):
        return self.call('get_game_state', {}).get('structuredContent', {})

    def console(self, command):
        self.call('execute_console_command', {'command': command, 'capture_output': False})

    def squirrel(self, script, attempts=4):
        """Run server Squirrel; return its [MRVN] lines, raising on script errors.

        R1Delta gives a script 2 s to reach the engine thread (the first call
        after a map load always misses that) but still runs it later, so
        retried scripts must be idempotent."""
        for number in range(attempts):
            try:
                result = self.call('execute_squirrel', {'context': 'server', 'script': script})
                break
            except RuntimeError as error:
                if 'Timed out waiting for VM task' not in str(error) or number == attempts - 1:
                    raise
                time.sleep(1)
        text = ''.join(part.get('text', '') for part in result.get('content', []))
        if result.get('isError'):
            raise RuntimeError('Squirrel error: ' + text[-600:])
        return [line.split('[MRVN] ', 1)[1].strip() for line in text.splitlines() if '[MRVN] ' in line]


def vec(values):
    return 'Vector( ' + ', '.join(f'{float(v):.4f}' for v in values) + ' )'


def trace_script(rows, first, hull):
    lines = ['local player = GetPlayerArray().len() ? GetPlayerArray()[0] : null']
    for i, t in enumerate(rows, first):
        call = (f'TraceHull( {vec(t[:3])}, {vec(t[3:6])}, {vec(t[6:9])}, {vec(t[9:12])}, player, '
                if hull else f'TraceLine( {vec(t[:3])}, {vec(t[3:6])}, player, ')
        kind = 'HULL' if hull else 'TRACE'
        lines.append(f'{{ local r = {call}TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE ); '
                     f'printl( "[MRVN] {kind} {i} fraction=" + r.fraction + " end=" + r.endPos.z + '
                     f'" solid=" + r.startSolid + " normal=" + r.surfaceNormal ) }}')
    return '\n'.join(lines)


def run_checks(control, checks, pid, output, events, screenshots):
    for key, hull in (('traces', False), ('hulls', True)):
        rows = checks[key]
        for first in range(0, len(rows), BATCH):
            events += control.squirrel(trace_script(rows[first:first + BATCH], first, hull))
    drops = checks['drops']
    if drops:
        models = checks['drop_models'] or [DEFAULT_MODEL] * len(drops)
        token = uuid.uuid4().hex
        # Guarded by a token: a timed-out call still runs later, so a retry
        # must not spawn a second set.
        spawn = [f'if ( !( "MRVN_DropToken" in getroottable() ) || ::MRVN_DropToken != "{token}" ) {{',
                 f'::MRVN_DropToken <- "{token}"', '::MRVN_Drops <- []']
        for model in sorted(set(models)):
            spawn.append(f'PrecacheModel( "{model}" )')
        for d, model in zip(drops, models):
            spawn.append(f'{{ local p = CreateEntity( "prop_physics" ); p.kv.model = "{model}"; p.kv.minhealthdmg = 9999; '
                         f'p.SetOrigin( {vec(d)} ); DispatchSpawn( p, false ); ::MRVN_Drops.append( p ) }}')
        spawn.append('}')
        spawn.append('foreach ( i, p in ::MRVN_Drops ) printl( "[MRVN] SPAWNED " + i + " valid=" + IsValid( p ) )')
        spawned = control.squirrel('\n'.join(spawn))
        events += spawned
        invalid = [line.split()[1] for line in spawned if line.endswith('valid=false')]
        if invalid:
            names = sorted({models[int(i)] for i in invalid})
            raise RuntimeError(f'drops {invalid} did not spawn as physics props in R1Delta (models {names}); '
                               'on a compiled map, stage the model files with --model-files')
        report = ('foreach ( i, p in ::MRVN_Drops ) { if ( IsValid( p ) ) printl( "[MRVN] %s " + i + %s" origin=" + '
                  'p.GetOrigin() + " velocity=" + p.GetVelocity() ); else printl( "[MRVN] %s " + i + " z=gone" ) }')
        start = time.monotonic()
        while checks['drop_samples'] and time.monotonic() - start < checks['drop_wait']:
            t = round(time.monotonic() - start, 2)
            events += control.squirrel(report % ('SAMPLE', f'" t={t}" + ', 'SAMPLE'))
            time.sleep(0.2)
        time.sleep(max(0.0, checks['drop_wait'] - (time.monotonic() - start)))
        events += control.squirrel(report % ('DROP', '" z=" + p.GetOrigin().z + ', 'DROP'))
    for i, v in enumerate(checks['views']):
        control.squirrel(f'local p = GetPlayerArray()[0]; p.SetOrigin( {vec(v[:3])} ); '
                         f'p.SetAngles( Vector( {float(v[3])}, {float(v[4])}, 0 ) ); p.SetVelocity( Vector( 0, 0, 0 ) )')
        time.sleep(2)
        path = output / f'view_{i}.png'
        if capture_window(pid, path):
            screenshots.append(str(path))
        events.append(f'VIEW {i}')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def launch(session, port):
    app, game = Path(session['app']), Path(session['game'])
    env = os.environ.copy()
    # As R1Delta's launcher (launcher_ex/App.xaml.cs): no -game, game cwd, DLL paths.
    env.update(FROM_DELTA_LAUNCHER='1', ContentId='1025161', __COMPAT_LAYER='NoDTToDITMouseBatch=1')
    paths = [app / 'r1delta/bin_delta', app / 'r1delta/bin', game / 'bin/x64_retail', game / 'r1/bin/x64_retail']
    env['PATH'] = os.pathsep.join([str(p) for p in paths if p.is_dir()] + [env.get('PATH', '')])
    command = [str(app / 'Titanfall.exe'), '-novid', '-usemcp', '-windowed', '-w', '1280', '-h', '720',
               '+developer', '1', '+mcp_start_http', str(port)]
    return subprocess.Popen(command, cwd=game, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def stop(process, control):
    if process is None or process.poll() is not None:
        return
    try:
        control.console('quit')
        process.wait(timeout=30)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, urllib.error.URLError):
        process.kill()
        process.wait(timeout=30)


def attempt(session, checks, output, timeout):
    port = free_port()
    control = Control(port)
    process = launch(session, port)
    report = {'map': session['map'], 'events': [], 'errors': [], 'screenshots': [], 'loaded': False, 'finished': False}
    start = time.monotonic()
    try:
        while not control.healthy():
            if process.poll() is not None:
                raise RuntimeError(f'R1Delta exited with code {process.returncode} before its control server started')
            if time.monotonic() - start > timeout:
                raise TimeoutError('R1Delta control server did not start')
            time.sleep(1)
        control.initialize()
        time.sleep(5)  # let the main menu finish initialising
        control.console('map ' + session['map'])
        while True:
            if process.poll() is not None:
                raise RuntimeError(f'R1Delta exited with code {process.returncode} while loading the map')
            if time.monotonic() - start > timeout:
                raise TimeoutError('map did not load')
            state = control.state()
            if state.get('in_game') and state.get('current_map', '').lower() in (session['map'].lower(),
                                                                              session['map'].lower() + '.bsp'):
                break
            time.sleep(2)
        while True:  # the local player spawns after the map loads
            try:
                if control.squirrel('printl( "[MRVN] PLAYERS " + GetPlayerArray().len() )') != ['PLAYERS 0']:
                    break
            except RuntimeError:
                pass
            if time.monotonic() - start > timeout:
                raise TimeoutError('no player spawned')
            time.sleep(2)
        report['loaded'] = True
        # The pilot loadout menu runs "setpause nomsg" on maps without a match
        # intro, which stops server time (and physics); "unpause" is a no-op otherwise.
        control.console('unpause nomsg')
        time.sleep(3)
        report['events'].append('BEGIN')
        run_checks(control, checks, process.pid, output, report['events'], report['screenshots'])
        report['events'].append('DONE')
        report['finished'] = True
    except Exception as error:
        report['errors'].append(f'{type(error).__name__}: {error}')
        try:  # the last console lines usually name the failure
            lines = control.call('get_console_log', {}, timeout=10).get('structuredContent', {}).get('lines', [])
            report['console_tail'] = [line.rstrip() for line in lines]
        except Exception:
            pass
    finally:
        stop(process, control)
    if report['finished']:
        report['errors'] += expectation_errors(report['events'], checks['expect'])
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--game', type=Path, help='Titanfall install (default: R1Delta InstallPath)')
    p.add_argument('--r1delta', type=Path, help='R1Delta app directory (default: newest app-*)')
    p.add_argument('--maps', type=Path, help='Folder with the compiled .bsp/.ent; omit for a retail map')
    p.add_argument('--map', required=True)
    p.add_argument('--checks', type=Path)
    p.add_argument('--model-files', type=Path,
                   help="Loose model tree (e.g. Titanfall Online's assets_dump) to stage drop models from; "
                        'needed for drops on compiled maps')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=300, help='Seconds to start, load and spawn')
    p.add_argument('--attempts', type=int, default=3)
    args = p.parse_args(argv)
    if not 30 <= args.timeout <= 3600 or args.attempts < 1:
        p.error('--timeout must be 30..3600 and --attempts at least 1')
    checks = validate_checks(json.loads(args.checks.read_text()) if args.checks else {})
    args.output.mkdir(parents=True, exist_ok=True)
    session = prepare(find_app(args.r1delta), find_game(args.game), args.maps, args.map,
                      checks['drop_models'] if checks['drops'] else None, model_source=args.model_files)
    try:
        for number in range(1, args.attempts + 1):
            report = attempt(session, checks, args.output, args.timeout)
            if report['loaded'] or number == args.attempts:
                break
            print(f'attempt {number}: {report["errors"]}, retrying', flush=True)
    finally:
        cleanup(session)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['finished'] and not report['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
