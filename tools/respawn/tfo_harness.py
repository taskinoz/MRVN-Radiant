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
              "views": [[x, y, z, pitch, yaw], ...],
              "drops": [[x, y, z], ...]}   physics objects; their resting height is logged
"""
import argparse
import ctypes
import ctypes.wintypes
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

MOD = 'MRVN.TF1Harness'
SCRIPT = r'''
// MRVN TF1 harness: traces and screenshots, then quit.
::MRVN_Traces <- %TRACES%
::MRVN_Views <- %VIEWS%
::MRVN_Drops <- %DROPS%

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

function MRVN_Run( player )
{
	player.EndSignal( "OnDestroy" )
	wait 3
	MRVN_Log( "BEGIN" )
	foreach ( i, t in MRVN_Traces )
	{
		local result = TraceLine( Vector( t[0], t[1], t[2] ), Vector( t[3], t[4], t[5] ), null, TRACE_MASK_PLAYERSOLID, TRACE_COLLISION_GROUP_NONE )
		MRVN_Log( "TRACE " + i + " fraction=" + result.fraction + " end=" + result.endPos.z + " solid=" + result.startSolid )
	}
	// Physics objects dropped from each point show whether VPhysics collides with the world.
	local dropped = []
	foreach ( i, d in MRVN_Drops )
	{
		local prop = CreateEntity( "prop_physics" )
		prop.kv.model = "models/weapons/bullets/projectile_rocket.mdl"
		prop.kv.minhealthdmg = 9999
		prop.SetOrigin( Vector( d[0], d[1], d[2] ) )
		DispatchSpawn( prop, false )
		prop.SetModel( "models/weapons/grenades/m20_f_grenade.mdl" )
		dropped.append( prop )
	}
	if ( dropped.len() )
		wait 4
	foreach ( i, prop in dropped )
		MRVN_Log( "DROP " + i + " z=" + ( IsValid( prop ) ? prop.GetOrigin().z : "gone" ) )
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
                                                .replace('%VIEWS%', sq(checks.get('views', [])))
                                                .replace('%DROPS%', sq(checks.get('drops', []))))
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
    enabled_path = args.game/'Mods/enabledmods.json'
    enabled_backup = enabled_path.read_text()
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
            process = subprocess.Popen(command, cwd=args.game/'Bin')
            deadline = time.time() + args.timeout
            text = ''
            captured = set()
            while time.time() < deadline and process.poll() is None:
                time.sleep(0.25)
                text = log.read_text('utf-8', 'replace') if log.exists() else ''
                for view in re.findall(r'\[MRVN\] VIEW (\d+)', text):
                    if view not in captured:
                        captured.add(view)
                        args.output.mkdir(parents=True, exist_ok=True)
                        capture_window(process.pid, args.output/f'view{view}.png')
                if '[MRVN] DONE' in text or 'A CRASH HAS BEEN CAPTURED' in text:
                    time.sleep(4)
                    break
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=30)
            text = log.read_text('utf-8', 'replace') if log.exists() else ''
            started = 'loading progress' in text
            if started:
                break
            print(f'attempt {attempt + 1}: exited before loading the map, retrying', flush=True)
    finally:
        shutil.rmtree(mod, ignore_errors=True)
        enabled_path.write_text(enabled_backup)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output/'tforevive.log').write_text(text, encoding='utf-8')
    new_shots = sorted(args.output.glob('view*.png'))
    events = [line.split('[MRVN] ', 1)[1] for line in text.splitlines() if '[MRVN] ' in line]
    errors = [line for line in text.splitlines() if 'SCRIPT ERROR' in line or 'CRASH HAS BEEN CAPTURED' in line]
    report = {'map': args.map, 'events': events, 'errors': errors, 'screenshots': [s.name for s in new_shots],
              'loaded': 'loading progress' in text, 'finished': '[MRVN] DONE' in text}
    (args.output/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
