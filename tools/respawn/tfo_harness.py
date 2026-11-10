"""Load a compiled Titanfall 1 map in Titanfall Online (TFORevive) and run checks.

Installs the map folder as a temporary mod, adds a _mapspawn hook that runs
traces and takes screenshots from chosen views, launches TFO without auth,
waits for the run to finish in tforevive.log, collects the results, then
removes the mod and restores enabledmods.json. Offline sessions have no player
data, so the hook falls back to a stock pilot settings file to let the player
spawn. Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.

  python tools/respawn/tfo_harness.py --game "D:/Games/Titanfall Online" \\
      --maps BUILD_DIR --map mp_name --checks checks.json --output REPORT_DIR

checks.json: {"traces": [[x, y, z, ex, ey, ez], ...],
              "hulls": [[x,y,z,ex,ey,ez,minx,miny,minz,maxx,maxy,maxz], ...],
              "views": [[x, y, z, pitch, yaw], ...], "view_commands": ["thirdperson"],
              "drops": [[x, y, z], ...],
              "drop_sequential": true,
              "drop_models": ["models/containers/barrel.mdl", ...],
              "drop_wait": 8,
              "drop_samples": true,
              "expect": {"trace_z": [[0, 63.9, 64.1]],
                         "drop_z": [[0, 65, 66]]}}
Optional expectations give [check index, minimum Z, maximum Z]; failures make
this command return nonzero. Sequential drops isolate each physics object.
Optional drop_models must match drops and use models/... .mdl paths; they use
the selected model's physics and appearance. Omit them for the legacy rocket
physics probe. drop_wait is the positive observation duration in seconds
(default 4), per object for sequential drops or shared for simultaneous drops.
drop_samples logs every simultaneous drop's position each 0.2 seconds.
"""
import argparse
import ctypes
import ctypes.wintypes
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MOD = 'MRVN.TF1Harness'


def target_map_started(text, map_name):
    return bool(re.search(r'UICodeCallback_LevelLoadingStarted:\s*' + re.escape(map_name) + r'(?:\s|$)', text))


def target_map_loaded(text, map_name):
    return bool(re.search(r'UICodeCallback_LevelLoadingFinished:\s*' + re.escape(map_name) +
                          r'\s+\(error:\s*false\)', text))


def game_crashed(text, exit_code):
    return 'A CRASH HAS BEEN CAPTURED' in text or exit_code not in (None, 0)


def height_expectations(expect):
    if not isinstance(expect, dict) or set(expect) - {'trace_z', 'hull_z', 'drop_z'}:
        raise ValueError('expect must contain only trace_z, hull_z and drop_z lists')
    result = []
    for key, kind in (('trace_z', 'TRACE'), ('hull_z', 'HULL'), ('drop_z', 'DROP')):
        rows = expect.get(key, [])
        if not isinstance(rows, list):
            raise ValueError(f'{key} must be a list')
        for row in rows:
            if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int or row[0] < 0 or
                    any(type(v) not in (int, float) or not math.isfinite(v) for v in row[1:]) or row[1] > row[2]):
                raise ValueError(f'{key} expectations must be [nonnegative index, finite minimum, finite maximum]')
            result.append((kind, *row))
    return result


def expectation_errors(events, expect):
    errors = []
    for kind, index, low, high in height_expectations(expect):
        pattern = rf'^{kind} {index} fraction=\S+ end=(\S+)' if kind in ('TRACE', 'HULL') else rf'^DROP {index} z=(\S+)'
        matches = [match.group(1) for event in events if (match := re.search(pattern, event))]
        try:
            values = [float(value) for value in matches]
        except ValueError:
            values = []
        if not values or any(not math.isfinite(value) or not low <= value <= high for value in values):
            errors.append(f'{kind} {index}: expected Z in [{low}, {high}], observed {matches or "no result"}')
    return errors


def executable_path_key(path):
    # Compare canonical long paths: CI temp folders use 8.3 names (RUNNER~1),
    # and QueryFullProcessImageNameW may echo whichever form launched the process.
    return os.path.normcase(os.path.realpath(str(path)))


class CrashHandlers:
    def __init__(self, parent_pid, game):
        self.parent_pid = parent_pid
        self.executables = {name: executable_path_key(game / 'Bin' / name)
                            for name in ('crashpad_handler.exe', 'messagebox-win.exe')}
        self.handles = {}

    def capture(self):
        class ProcessEntry(ctypes.Structure):
            _fields_ = [('size', ctypes.wintypes.DWORD), ('usage', ctypes.wintypes.DWORD),
                        ('pid', ctypes.wintypes.DWORD), ('heap', ctypes.c_size_t),
                        ('module', ctypes.wintypes.DWORD), ('threads', ctypes.wintypes.DWORD),
                        ('parent', ctypes.wintypes.DWORD), ('priority', ctypes.wintypes.LONG),
                        ('flags', ctypes.wintypes.DWORD), ('name', ctypes.wintypes.WCHAR * 260)]

        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD]
        kernel.CreateToolhelp32Snapshot.restype = ctypes.wintypes.HANDLE
        kernel.Process32FirstW.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.Process32NextW.argtypes = [ctypes.wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
        kernel.OpenProcess.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD]
        kernel.OpenProcess.restype = ctypes.wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
                                                     ctypes.wintypes.LPWSTR, ctypes.POINTER(ctypes.wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        if snapshot == ctypes.wintypes.HANDLE(-1).value:
            return
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            found = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            entries = []
            while found:
                entries.append((entry.pid, entry.parent, entry.name.casefold()))
                found = kernel.Process32NextW(snapshot, ctypes.byref(entry))
            # A crashpad child may launch the dialog. Resolve parents after the
            # complete snapshot so process enumeration order does not matter.
            pending = True
            while pending:
                pending = False
                for pid, parent, name in entries:
                    if (parent not in {self.parent_pid, *self.handles} or
                            name not in self.executables or pid in self.handles):
                        continue
                    handle = kernel.OpenProcess(0x101001, False, pid)
                    if handle:
                        path = ctypes.create_unicode_buffer(32768)
                        length = ctypes.wintypes.DWORD(len(path))
                        if (kernel.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)) and
                                executable_path_key(path.value) == self.executables[name]):
                            self.handles[pid] = handle
                            pending = True
                        else:
                            kernel.CloseHandle(handle)
        finally:
            kernel.CloseHandle(snapshot)

    def close(self, crashed):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.TerminateProcess.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.UINT]
        kernel.WaitForSingleObject.argtypes = [ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD]
        kernel.WaitForSingleObject.restype = ctypes.wintypes.DWORD
        kernel.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
        if crashed:
            for pid, handle in self.handles.items():
                if kernel.TerminateProcess(handle, 1):
                    print(f'closed TFO crash handler {pid}', flush=True)
        for handle in self.handles.values():
            if crashed:
                kernel.WaitForSingleObject(handle, 5000)
            kernel.CloseHandle(handle)
        self.handles.clear()


SCRIPT = r'''
// MRVN TF1 harness: traces and screenshots, then quit.
::MRVN_Traces <- %TRACES%
::MRVN_Hulls <- %HULLS%
::MRVN_Views <- %VIEWS%
::MRVN_ViewCommands <- %VIEW_COMMANDS%
::MRVN_Drops <- %DROPS%
::MRVN_DropSequential <- %DROP_SEQUENTIAL%
::MRVN_DropModels <- %DROP_MODELS%
::MRVN_DropWait <- %DROP_WAIT%
::MRVN_DropSamples <- %DROP_SAMPLES%

// This include runs during level initialization, before prop spawning is allowed.
foreach ( model in MRVN_DropModels ) PrecacheModel( model )

::MRVN_OriginalPilotSetFile <- GetPlayerPilotSetFile
function GetPlayerPilotSetFile( self )
{
	local file = null
	try { file = MRVN_OriginalPilotSetFile( self ) } catch ( e ) {}
	if ( file == null )
		file = "pilot_male_fastest"  // offline sessions have no loadout data
	return file
}

function MRVN_Log( text ) { printl( "[MRVN] " + text ) }

function MRVN_LogDrop( i, prop )
{
	if ( IsValid( prop ) )
		MRVN_Log( "DROP " + i + " z=" + prop.GetOrigin().z + " origin=" + prop.GetOrigin() + " velocity=" + prop.GetVelocity() )
	else
		MRVN_Log( "DROP " + i + " z=gone" )
}

function MRVN_Run( player )
{
	player.EndSignal( "OnDestroy" )
	wait 3
	MRVN_Log( "BEGIN" )
	foreach ( i, t in MRVN_Traces )
	{
		local result = TraceLine( Vector( t[0], t[1], t[2] ), Vector( t[3], t[4], t[5] ), player, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
		MRVN_Log( "TRACE " + i + " fraction=" + result.fraction + " end=" + result.endPos.z + " solid=" + result.startSolid + " normal=" + result.surfaceNormal )
	}
	foreach ( i, t in MRVN_Hulls )
	{
		local result = TraceHull( Vector( t[0], t[1], t[2] ), Vector( t[3], t[4], t[5] ), Vector( t[6], t[7], t[8] ), Vector( t[9], t[10], t[11] ), player, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
		MRVN_Log( "HULL " + i + " fraction=" + result.fraction + " end=" + result.endPos.z + " solid=" + result.startSolid + " normal=" + result.surfaceNormal )
	}
	// Physics objects dropped from each point show whether VPhysics collides with the world.
	local dropped = []
	foreach ( i, d in MRVN_Drops )
	{
		local prop = CreateEntity( "prop_physics" )
		prop.kv.model = MRVN_DropModels.len() ? MRVN_DropModels[i] : "models/weapons/bullets/projectile_rocket.mdl"
		prop.kv.minhealthdmg = 9999
		prop.SetOrigin( Vector( d[0], d[1], d[2] ) )
		DispatchSpawn( prop, false )
		if ( !MRVN_DropModels.len() ) prop.SetModel( "models/weapons/grenades/m20_f_grenade.mdl" )
		dropped.append( prop )
		if ( MRVN_DropSequential )
		{
			wait MRVN_DropWait
			MRVN_LogDrop( i, prop )
			if ( IsValid( prop ) ) prop.Destroy()
		}
	}
	if ( dropped.len() && !MRVN_DropSequential )
	{
		if ( MRVN_DropSamples )
		{
			for ( local t = 0.0; t < MRVN_DropWait; t += 0.2 )
			{
				foreach ( i, prop in dropped )
					if ( IsValid( prop ) )
						MRVN_Log( "SAMPLE " + i + " t=" + t + " origin=" + prop.GetOrigin() + " velocity=" + prop.GetVelocity() )
				wait 0.2
			}
		}
		else
			wait MRVN_DropWait
		foreach ( i, prop in dropped )
			MRVN_LogDrop( i, prop )
	}
	if ( MRVN_Views.len() && MRVN_ViewCommands.len() )
	{
		ServerCommand( "sv_cheats 1" )
		wait 1
		foreach ( command in MRVN_ViewCommands )
			ClientCommand( player, command )
		wait 1
	}
	foreach ( i, v in MRVN_Views )
	{
		player.SetOrigin( Vector( v[0], v[1], v[2] ) )
		player.SetAngles( Vector( v[3], v[4], 0 ) )
		player.SetVelocity( Vector( 0, 0, 0 ) )
		wait 2
		MRVN_Log( "VIEW " + i )  // the harness captures the game window now
		wait 2
	}
	MRVN_Log( "DONE" )
	wait 2
	ServerCommand( "quit" )
}

function MRVN_OnSpawn( player )
{
	player.SetInvulnerable()
	thread MRVN_Run( player )
}

AddCallback_OnPlayerRespawned( MRVN_OnSpawn )
'''


def capture_window(pid, path):
    """Saves the visible client area of the process's main window."""
    from PIL import ImageGrab
    user32 = ctypes.windll.user32
    found = []
    def visit(hwnd, _):
        owner = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True
    user32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)(visit), 0)
    best = None
    seen = []
    for hwnd in found:
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, name, 256)
        seen.append(f'{name.value} {rect.right}x{rect.bottom}')
        # The engine's window, not the launcher's web UI windows.
        engine = name.value.startswith(('Respawn', 'Valve'))
        if rect.right >= 640 and (best is None or engine > best[2]):
            best = (hwnd, rect, engine)
    Path(path).with_suffix('.windows.txt').write_text('\n'.join(seen))
    if best is None:
        return False
    hwnd, rect, _ = best
    # PrintWindow returns a blank image for the engine's DirectX window, so the
    # screen is read instead. Windows only lets a background process raise a
    # window after a key event; the window is topmost while it is captured.
    from PIL import ImageGrab
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    user32.ShowWindow(hwnd, 9)
    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0003)  # HWND_TOPMOST, no move or size
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.6)
    corner = ctypes.wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(corner))
    ImageGrab.grab((corner.x, corner.y, corner.x + rect.right, corner.y + rect.bottom), all_screens=True).save(path)
    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0003)  # HWND_NOTOPMOST
    return True


def write_mod(game, maps, checks):
    hulls = checks.get('hulls', [])
    if not isinstance(hulls, list) or any(
            not isinstance(row, list) or len(row) != 12 or
            any(type(v) not in (int, float) or not math.isfinite(v) for v in row) or
            any(row[6+i] > row[9+i] for i in range(3)) for row in hulls):
        raise ValueError('hulls must contain finite start/end/mins/maxs rows with ordered extents')
    models = checks.get('drop_models', [])
    if (not isinstance(models, list) or (models and len(models) != len(checks.get('drops', []))) or
            any(not isinstance(name, str) or not re.fullmatch(r'models/[A-Za-z0-9_/-]+\.mdl', name) or
                '..' in name.split('/') for name in models)):
        raise ValueError('drop_models must match drops and contain model paths')
    drop_wait = checks.get('drop_wait', 4)
    if type(drop_wait) not in (int, float) or not math.isfinite(drop_wait) or drop_wait <= 0:
        raise ValueError('drop_wait must be a positive finite duration')
    # Console commands for the views, e.g. ["thirdperson"] to see the character's lighting.
    view_commands = checks.get('view_commands', [])
    if not isinstance(view_commands, list) or any(
            not isinstance(c, str) or not re.fullmatch(r'[A-Za-z0-9_ .+-]{1,64}', c) for c in view_commands):
        raise ValueError('view_commands must be short console commands')
    mods = game/'Mods'
    mod = mods/MOD
    if mod.exists():
        raise SystemExit(f'{mod} exists; remove it first')
    scripts = mod/'mod/scripts/vscripts'
    scripts.mkdir(parents=True)
    shutil.copytree(maps, mod/'mod/maps', ignore=shutil.ignore_patterns('*.map', '*.log', '*.json', '*.prt', '*.srf'))
    base = (mods/'TFORevive.Core/mod/scripts/vscripts/_mapspawn.nut').read_bytes()
    (scripts/'_mapspawn.nut').write_bytes(base + b'\nIncludeScript( "mrvn_tf1_harness", getroottable() )\n')
    sq = lambda rows: '[' + ', '.join('[' + ', '.join(f'{float(v):.3f}' for v in row) + ']' for row in rows) + ']'
    (scripts/'mrvn_tf1_harness.nut').write_text(SCRIPT.replace('%TRACES%', sq(checks.get('traces', [])))
                                                .replace('%HULLS%', sq(hulls))
                                                .replace('%VIEWS%', sq(checks.get('views', [])))
                                                .replace('%VIEW_COMMANDS%', json.dumps(view_commands))
                                                .replace('%DROPS%', sq(checks.get('drops', [])))
                                                .replace('%DROP_SEQUENTIAL%', 'true' if checks.get('drop_sequential', False) else 'false')
                                                .replace('%DROP_MODELS%', json.dumps(models))
                                                .replace('%DROP_WAIT%', str(float(drop_wait)))
                                                .replace('%DROP_SAMPLES%', 'true' if checks.get('drop_samples', False) is True else 'false'))
    (mod/'mod.json').write_text(json.dumps({'Name': MOD, 'Description': 'MRVN-Radiant TF1 compiler test', 'Authors': ['MRVN-Radiant'],
                                            'Version': '0.1.0', 'LoadPriority': 50, 'RequiredOnClient': True}, indent=1))
    return mod


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--game', type=Path, required=True)
    p.add_argument('--maps', type=Path, required=True, help='Folder with the compiled .bsp and .ent files')
    p.add_argument('--map', required=True)
    p.add_argument('--checks', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--timeout', type=int, default=300)
    p.add_argument('--attempts', type=int, default=3)
    p.add_argument('--enable', action='append', default=[], help='Also enable this installed mod, e.g. Titanfall1.Content.Client')
    args = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_]+', args.map):
        raise SystemExit('invalid map name')
    checks = json.loads(args.checks.read_text()) if args.checks else {}
    height_expectations(checks.get('expect', {}))  # reject malformed expectations before installing the mod
    enabled_path = args.game/'Mods/enabledmods.json'
    enabled_backup = enabled_path.read_bytes()
    log = args.game/'Logs/tforevive.log'
    mod = write_mod(args.game, args.maps, checks)
    try:
        enabled = json.loads(enabled_backup)
        enabled[MOD] = True
        for name in args.enable:
            enabled[name] = True
        enabled_path.write_text(json.dumps(enabled, indent=4))
        # TFO.exe requires --authToken even with -noauth; the value is not a credential.
        command = [str(args.game/'Bin/TFO.exe'), '--authToken', 'mrvn-local-noauth', '-noauth', '-novid', '-windowed',
                   '-w', '1280', '-h', '720', '+sv_lan', '1', '+sv_cheats', '1', '+developer', '1', '+map', args.map]
        # TFO recreates its log on every launch. Its graphics driver sometimes
        # overflows the stack while starting up; such launches are retried.
        for attempt in range(args.attempts):
            launch_time = time.time_ns()
            process = subprocess.Popen(command, cwd=args.game/'Bin')
            handlers = CrashHandlers(process.pid, args.game)
            deadline = time.time() + args.timeout
            text = ''
            captured = set()
            try:
                while time.time() < deadline and process.poll() is None:
                    # Capture every time: TFO can launch a replacement handler.
                    handlers.capture()
                    time.sleep(0.25)
                    if log.exists() and log.stat().st_mtime_ns >= launch_time:
                        text = log.read_text('utf-8', 'replace')
                    for view in re.findall(r'\[MRVN\] VIEW (\d+)', text):
                        if view not in captured:
                            captured.add(view)
                            args.output.mkdir(parents=True, exist_ok=True)
                            capture_window(process.pid, args.output/f'view{view}.png')
                    if '[MRVN] DONE' in text or 'A CRASH HAS BEEN CAPTURED' in text:
                        time.sleep(4)
                        break
                handlers.capture()
                if log.exists() and log.stat().st_mtime_ns >= launch_time:
                    text = log.read_text('utf-8', 'replace')
            finally:
                exit_code = process.poll()
                crashed = game_crashed(text, exit_code)
                try:
                    if exit_code is None:
                        process.terminate()
                        process.wait(timeout=30)
                finally:
                    handlers.capture()
                    handlers.close(crashed)
            if target_map_started(text, args.map):
                break
            print(f'attempt {attempt + 1}: exited before loading the map, retrying', flush=True)
    finally:
        shutil.rmtree(mod, ignore_errors=True)
        enabled_path.write_bytes(enabled_backup)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'tforevive.log').write_text(text, encoding='utf-8')
    new_shots = sorted(args.output.glob('view*.png'))
    events = [line.split('[MRVN] ', 1)[1] for line in text.splitlines() if '[MRVN] ' in line]
    errors = [line for line in text.splitlines() if 'SCRIPT ERROR' in line or 'CRASH HAS BEEN CAPTURED' in line]
    errors.extend(expectation_errors(events, checks.get('expect', {})))
    if exit_code not in (None, 0):
        errors.append(f'TFO exited abnormally with code {exit_code}')
    report = {'map': args.map, 'events': events, 'errors': errors, 'screenshots': [s.name for s in new_shots],
              'loaded': target_map_loaded(text, args.map), 'finished': '[MRVN] DONE' in text}
    (args.output/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report['loaded'] and report['finished'] and not report['errors'] else 1


if __name__ == '__main__':
    sys.exit(main())
