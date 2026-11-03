#!/usr/bin/env python3
"""Local R5 SDK 2.3 map controller, using its legacy protobuf netconsole.

Original implementation, GPL-2.0-or-later. Protocol reference: the installed
SDK v2.3_rc0 resource/protobuf/{cl,sv}_rcon.proto and engine/server/sv_rcon.cpp.
No injected DLL or third-party Python dependency is needed.
"""
import argparse
from collections import deque
from contextlib import nullcontext
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import socket
import struct
import subprocess
import threading
import time
import uuid

MAX_FRAME = 1024 * 1024


def varint(value):
    value &= (1 << 64) - 1
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def read_varint(data, at):
    value = 0
    for shift in range(0, 70, 7):
        if at >= len(data):
            raise ValueError('Truncated protobuf varint')
        byte = data[at]
        at += 1
        value |= (byte & 127) << shift
        if not byte & 128:
            if value >= 1 << 64:
                raise ValueError('Protobuf varint overflow')
            return value, at
    raise ValueError('Protobuf varint overflow')


def encode_request(kind, message='', value=''):
    # Legacy Execute looks up requestMsg as the command NAME, and tokenizes
    # requestVal as the ENTIRE console command, including that name.
    result = b'\x08' + varint(-1) + b'\x18' + varint(kind)
    for field, text in ((4, message), (5, value)):
        raw = text.encode('utf-8')
        result += varint(field << 3 | 2) + varint(len(raw)) + raw
    if len(result) > MAX_FRAME:
        raise ValueError('Console request too large')
    return struct.pack('>I', len(result)) + result


def decode_message(data):
    fields, at = {}, 0
    while at < len(data):
        tag, at = read_varint(data, at)
        field, wire = tag >> 3, tag & 7
        if field == 0:
            raise ValueError('Invalid protobuf field')
        if wire == 0:
            fields[field], at = read_varint(data, at)
        elif wire == 2:
            size, at = read_varint(data, at)
            if size > len(data) - at:
                raise ValueError('Truncated protobuf string')
            fields[field] = data[at:at + size].decode('utf-8', errors='replace')
            at += size
        elif wire in (1, 5):
            at += 8 if wire == 1 else 4
            if at > len(data):
                raise ValueError('Truncated protobuf fixed field')
        else:
            raise ValueError('Unsupported protobuf wire type')
    return fields


def receive_frame(sock):
    def exact(count):
        data = bytearray()
        while len(data) < count:
            chunk = sock.recv(count - len(data))
            if not chunk:
                raise EOFError('Netconsole disconnected')
            data.extend(chunk)
        return bytes(data)
    size, = struct.unpack('>I', exact(4))
    if not 0 < size <= MAX_FRAME:
        raise ValueError('Console frame outside bounded size')
    return decode_message(exact(size))


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}', value):
        raise ValueError('Expected a lowercase map, playlist or game-mode identifier')
    return value


def make_playlist(source, map, playlist, gamemode):
    map, playlist, gamemode = tuple(identifier(v) for v in (map, playlist, gamemode))
    if playlist == 'mrvn_harness_run':
        raise ValueError('Choose a base playlist rather than the generated harness playlist')
    block = f'''\n mrvn_harness_run
 {{
  inherit {playlist}
  vars {{ visible 0 }}
  gamemodes {{ {gamemode} {{ maps {{ {map} 1 }} }} }}
 }}\n'''
    result, count = re.subn(r'(\bPlaylists\s*\{)', lambda m: m[0] + block, source, count=1)
    if count != 1:
        raise ValueError('Base file has no Playlists block')
    return result


class Netconsole:
    def __init__(self, port, password, callback):
        self.sock = socket.create_connection(('::1', port), timeout=2)
        self.sock.sendall(encode_request(1, password))
        while True:
            response = receive_frame(self.sock)
            if response.get(3, 0) == 0:
                if 'Authentication successful' not in response.get(4, ''):
                    self.sock.close()
                    raise PermissionError('Netconsole authentication rejected')
                break
        self.sock.sendall(encode_request(2, '', '1'))
        self.sock.settimeout(None)
        self.lock = threading.Lock()
        self.error = None
        self.callback = callback
        threading.Thread(target=self.read, daemon=True).start()

    def read(self):
        try:
            while True:
                message = receive_frame(self.sock)
                self.callback(message.get(4, ''))
        except (OSError, EOFError, ValueError) as error:
            self.error = str(error)

    def command(self, line):
        if not isinstance(line, str) or not line.strip() or len(line) > 16384 or any(c in line for c in '\r\n\0'):
            raise ValueError('Expected one bounded console command')
        if self.error:
            raise ConnectionError(self.error)
        with self.lock:
            self.sock.sendall(encode_request(0, line.split(None, 1)[0], line))

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class Harness:
    def __init__(self, game, state_dir, game_port):
        self.game, self.directory, self.port = game.resolve(), state_dir.resolve(), game_port
        self.directory.mkdir(parents=True, exist_ok=True)
        self.process = self.console = None
        self.events = deque(maxlen=2000)
        self.condition = threading.Condition()
        self.operation = threading.Lock()
        self.password = secrets.token_urlsafe(32)
        self.session = uuid.uuid4().hex[:12]
        self.last_load = None
        self.playlist_base = None

    def event(self, text):
        # The engine can log generated network keys. Never expose those through
        # HTTP, the CLI, or our event artifact.
        if re.search(r'net.?key|password|auth.?token|authorization|rcon_key', text, re.I):
            return
        text = text.replace(self.password, '[redacted]')
        with self.condition:
            entry = dict(sequence=getattr(self, 'sequence', 0) + 1, time=time.time(), text=text[:32768])
            self.sequence = entry['sequence']
            self.events.append(entry)
            with (self.directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(entry) + '\n')
            self.condition.notify_all()

    def status(self):
        if self.process and not getattr(self, 'engine_log_dir', None):
            new_dirs = [p for p in (self.game / 'platform/logs').glob('*')
                        if p.is_dir() and p.name not in self.log_dirs_before]
            if len(new_dirs) == 1:
                self.engine_log_dir = new_dirs[0]
        crash = None
        if getattr(self, 'engine_log_dir', None):
            path = self.engine_log_dir / 'apex_crash.txt'
            if path.is_file():
                # Only the short crash header; never dump registers, module
                # lists, command lines or the unfiltered engine logs over HTTP.
                crash = '\n'.join(path.read_text(errors='replace').splitlines()[:6])
        return dict(pid=self.process.pid if self.process else None,
                    running=self.process is not None and self.process.poll() is None,
                    exit_code=self.process.poll() if self.process else None,
                    console_connected=self.console is not None and self.console.error is None,
                    console_error=self.console.error if self.console else None,
                    mode=getattr(self, 'mode', None), last_load=self.last_load,
                    sequence=getattr(self, 'sequence', 0), crash=crash,
                    engine_log_dir=str(self.engine_log_dir) if getattr(self, 'engine_log_dir', None) else None)

    def boot(self, mode='dedicated', playlist_file='playlists_mrvn_coliseum.txt', timeout=45):
        if self.process and self.process.poll() is None:
            raise ValueError('Harness already owns a running game process')
        if mode not in ('dedicated', 'client'):
            raise ValueError('Mode must be dedicated or client')
        if not re.fullmatch(r'[a-zA-Z0-9_]+\.txt', playlist_file):
            raise ValueError('Expected a playlist filename inside platform')
        if not (self.game / 'platform' / playlist_file).is_file():
            raise ValueError('Playlist file does not exist')
        exe = self.game / ('r5apex_ds.exe' if mode == 'dedicated' else 'r5apex.exe')
        if not exe.is_file():
            raise ValueError('Game executable does not exist')
        # Refuse to authenticate against an unrelated server already using
        # this port, rather than trying the harness password on that server.
        with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as probe:
            if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('::1', self.port))
        self.mode = mode
        self.last_load = None
        self.playlist_base = (self.game / 'platform' / playlist_file).read_text()
        self.playlist_name = 'playlists_mrvn_harness_' + self.session + '.txt'
        (self.game / 'platform' / self.playlist_name).write_text(self.playlist_base)
        # net_usesocketsforloopback=0 makes legacy v2.3 RCON bind ::1 instead
        # of the wildcard address. This is a per-process test configuration.
        cfg_name = 'mrvn_harness_' + self.session + '.cfg'
        cfg = self.game / 'platform/cfg' / cfg_name
        cfg.write_text(f'hostport {self.port}\nnet_usesocketsforloopback 0\nrcon_password "{self.password}"\nsv_rcon_sendlogs 1\ndeveloper 1\nsv_cheats 1\nscript_show_output 2\nscript_show_warning 2\n', encoding='ascii')
        args = [str(exe), '-launcher', '1', '-dev', '-devsdk', '-console', '-novid',
                '-playlistfile', self.playlist_name, '+exec', cfg_name]
        if mode == 'client':
            args += ['-windowed', '-noborder', '-w', '1280', '-h', '720']
        self.log_dirs_before = {p.name for p in (self.game / 'platform/logs').glob('*') if p.is_dir()}
        self.engine_log_dir = None
        # Keep all engine output local; expose only filtered netconsole events.
        with (self.directory / 'engine-output.log').open('ab') as output:
            self.process = subprocess.Popen(args, cwd=self.game, stdin=subprocess.DEVNULL,
                                            stdout=output, stderr=subprocess.STDOUT,
                                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        deadline = time.monotonic() + min(max(float(timeout), 1), 90)
        try:
            while time.monotonic() < deadline:
                new_dirs = [p for p in (self.game / 'platform/logs').glob('*') if p.is_dir() and p.name not in self.log_dirs_before]
                if len(new_dirs) == 1:
                    self.engine_log_dir = new_dirs[0]
                if self.process.poll() is not None:
                    raise RuntimeError(f'Game exited during boot ({self.process.returncode})')
                try:
                    self.console = Netconsole(self.port, self.password, self.event)
                    self.console.command('echo MRVN_HARNESS_CONNECTED_' + self.session)
                    return self.status()
                except PermissionError:
                    raise
                except (OSError, EOFError):
                    time.sleep(.25)
            raise TimeoutError('No legacy R5 netconsole connection before boot timeout')
        finally:
            # No persistent password/config edit remains after startup.
            cfg.unlink(missing_ok=True)

    def command(self, text, timeout=5):
        if not self.console:
            raise ConnectionError('Boot the harness first')
        marker = 'MRVN_HARNESS_BARRIER_' + uuid.uuid4().hex
        start = getattr(self, 'sequence', 0)
        self.console.command(text)
        self.console.command('script print("' + marker + '")')
        deadline = time.monotonic() + min(max(float(timeout), .1), 30)
        with self.condition:
            while time.monotonic() < deadline:
                entries = [e for e in self.events if e['sequence'] > start]
                if any(marker in e['text'] for e in entries):
                    return dict(acknowledged=True, events=[e for e in entries if marker not in e['text']])
                if self.console.error or self.process.poll() is not None:
                    break
                self.condition.wait(min(.2, max(0, deadline-time.monotonic())))
        with self.condition:
            entries = [e for e in self.events if e['sequence'] > start]
        return dict(acknowledged=False, events=entries, state=self.status())

    def load(self, map, playlist, gamemode=None, timeout=45):
        map, playlist = identifier(map), identifier(playlist)
        if gamemode is None:
            raise ValueError('Provide gamemode explicitly so map selection is deterministic')
        gamemode = identifier(gamemode)
        if not self.console:
            raise ConnectionError('Boot the harness first')
        active_playlist = 'mrvn_harness_run'
        self.last_load = dict(map=map, playlist=playlist, active_playlist=active_playlist, requested_gamemode=gamemode,
                              state='loading', started=time.time())
        start_sequence = getattr(self, 'sequence', 0)
        # Use an owned playlist copy to force exactly one map and game mode.
        # Never edit the requested base playlist or its stock source file.
        text = make_playlist(self.playlist_base, map, playlist, gamemode)
        (self.game / 'platform' / self.playlist_name).write_text(text)
        self.console.command('reload_playlists')
        self.console.command('launchplaylist ' + active_playlist)
        deadline = time.monotonic() + min(max(float(timeout), 1), 90)
        while time.monotonic() < deadline:
            if self.process.poll() is not None or self.console.error or self.status()['crash']:
                self.last_load['state'] = 'failed'
                return self.status()
            marker = 'MRVN_HARNESS_PROBE_' + uuid.uuid4().hex
            result = self.command(f'script print("{marker} " + GetMapName() + " " + GetCurrentPlaylistName() + " " + GameRules_GetGameMode() + " entities=" + Flag("EntitiesDidLoad"))', timeout=2)
            text = '\n'.join(e['text'] for e in result.get('events', []))
            with self.condition:
                new_vm = any(e['sequence'] > start_sequence and 'Created SERVER VM' in e['text'] for e in self.events)
            if new_vm and marker in text and map in text and active_playlist in text and 'entities=true' in text:
                evidence = '\n'.join(line for line in text.splitlines() if marker in line)
                if gamemode and not re.search(r'\b' + re.escape(gamemode) + r'\b', text):
                    self.last_load.update(state='mode_mismatch', evidence=evidence, fresh_server_vm=True)
                else:
                    self.last_load.update(state='loaded', evidence=evidence, fresh_server_vm=True)
                return self.status()
            time.sleep(.5)
        self.last_load['state'] = 'timeout'
        return self.status()

    def stop(self):
        # Only terminate the exact Popen child owned by this controller. Never
        # locate or kill other users' game processes by executable name.
        if self.process and self.process.poll() is None:
            try:
                if self.console:
                    self.console.command('quit')
                self.process.wait(timeout=5)
            except (OSError, ConnectionError, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=5)
        if self.console:
            self.console.close()
            self.console = None
        if getattr(self, 'playlist_name', None):
            (self.game / 'platform' / self.playlist_name).unlink(missing_ok=True)
        return self.status()


def serve(args):
    controller = Harness(args.game, args.state_dir, args.game_port)
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def respond(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self.dispatch(False)

        def do_POST(self):
            self.dispatch(True)

        def dispatch(self, mutate):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                return self.respond(401, dict(error='Authentication required'))
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 <= size <= 32768:
                    raise ValueError('Request body too large')
                data = json.loads(self.rfile.read(size)) if size else {}
                if not isinstance(data, dict):
                    raise ValueError('Expected a JSON object')
                with controller.operation if mutate else nullcontext():
                    if not mutate and self.path == '/state':
                        result = controller.status()
                    elif not mutate and self.path == '/events':
                        with controller.condition:
                            result = list(controller.events)[-100:]
                    elif mutate and self.path == '/boot':
                        result = controller.boot(**data)
                    elif mutate and self.path == '/load':
                        result = controller.load(**data)
                    elif mutate and self.path == '/command':
                        result = controller.command(**data)
                    elif mutate and self.path == '/stop':
                        result = controller.stop()
                    else:
                        return self.respond(404, dict(error='Unknown endpoint'))
                self.respond(200, result)
            except (ValueError, TypeError, OSError, RuntimeError, EOFError) as error:
                self.respond(400, dict(error=str(error).replace(controller.password, '[redacted]'), state=controller.status()))

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    connection = dict(url=f'http://127.0.0.1:{server.server_port}', token=token)
    connection_path = controller.directory / 'connection.json'
    connection_path.write_text(json.dumps(connection), encoding='utf-8')
    print(json.dumps(dict(url=connection['url'], connection_file=str(connection_path))), flush=True)
    try:
        server.serve_forever()
    finally:
        controller.stop()
        server.server_close()
        connection_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=39300)
    parser.add_argument('--game-port', type=int, default=37025)
    args = parser.parse_args()
    serve(args)


if __name__ == '__main__':
    main()
