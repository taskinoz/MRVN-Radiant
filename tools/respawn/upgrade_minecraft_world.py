#!/usr/bin/env python3
"""Upgrade an old Minecraft Java world ZIP to the current format for the converter.

Worlds saved before Minecraft 1.13 store numeric block IDs (no block-state palette),
which build_minecraft_ports.py cannot read. This runs Mojang's own upgrader once:
the official dedicated server for the converter's Minecraft version, started with
--forceUpgrade on a copy of the world, then stopped. The upgraded world is zipped
next to the output path. The original ZIP is never modified.

Running the server requires accepting the Minecraft EULA
(https://aka.ms/MinecraftEULA); pass --accept-eula to do so.

  python tools/respawn/upgrade_minecraft_world.py --world old.zip --output new.zip \\
      --java "C:/Program Files/Java/jdk-26.0.1/bin/java.exe" --accept-eula

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

VERSION = '1.20.6'  # the block and model data the converter reads (its client JAR)
MANIFEST = 'https://piston-meta.mojang.com/mc/game/version_manifest_v2.json'


def fetch_json(url):
    with urllib.request.urlopen(url, timeout=60) as reply:
        return json.loads(reply.read())


def server_jar(cache):
    """The official dedicated server JAR for VERSION, downloaded once and checked by SHA-1."""
    jar = cache/f'minecraft_server.{VERSION}.jar'
    if jar.exists(): return jar
    entry = next(v for v in fetch_json(MANIFEST)['versions'] if v['id'] == VERSION)
    download = fetch_json(entry['url'])['downloads']['server']
    with urllib.request.urlopen(download['url'], timeout=300) as reply:
        data = reply.read()
    if hashlib.sha1(data).hexdigest() != download['sha1']: raise ValueError('server JAR checksum mismatch')
    cache.mkdir(parents=True, exist_ok=True); jar.write_bytes(data)
    return jar


def world_root(names):
    """The folder inside the ZIP that holds level.dat (shortest path wins)."""
    roots = sorted((PurePosixPath(n).parent for n in names if PurePosixPath(n).name == 'level.dat'), key=lambda p: len(p.parts))
    if not roots: raise ValueError('no level.dat in the world ZIP')
    return roots[0]


def upgrade(world_zip, output, java, cache):
    with tempfile.TemporaryDirectory() as temp:
        server = Path(temp)
        world = server/'world'
        with zipfile.ZipFile(world_zip) as z:
            root = world_root(z.namelist())
            for info in z.infolist():
                path = PurePosixPath(info.filename)
                if info.is_dir() or root not in (path, *path.parents) or '..' in path.parts: continue
                rel = path.relative_to(root)
                target = world/Path(*rel.parts); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(z.read(info))
        (server/'eula.txt').write_text('eula=true\n')
        (server/'server.properties').write_text('level-name=world\nonline-mode=false\nserver-port=0\nenable-query=false\n'
                                                'spawn-protection=0\nmax-players=1\n')
        jar = server_jar(Path(cache).resolve())
        process = subprocess.Popen([str(java), '-Xmx4G', '-jar', str(jar), '--forceUpgrade', '--nogui'], cwd=server,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        done = False
        for line in process.stdout:
            print(line.rstrip(), flush=True)
            if 'Done (' in line and not done:
                done = True  # the upgrade runs before the server finishes starting
                process.stdin.write('stop\n'); process.stdin.flush()
        process.wait(timeout=120)
        if not done: raise RuntimeError('the server did not finish starting; see the log above')
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
            for path in sorted(world.rglob('*')):
                if path.is_file() and path.suffix != '.lock':
                    z.write(path, PurePosixPath('world', *path.relative_to(world).parts).as_posix())
    return output


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--world', type=Path, required=True, help='Original world ZIP')
    p.add_argument('--output', type=Path, required=True, help='Upgraded world ZIP to write')
    p.add_argument('--java', type=Path, default=Path('java'), help='Java 21 or later')
    p.add_argument('--cache', type=Path, default=Path('.local/minecraft-server'), help='Where the server JAR is kept')
    p.add_argument('--accept-eula', action='store_true', help='Accept the Minecraft EULA (https://aka.ms/MinecraftEULA)')
    args = p.parse_args(argv)
    if not args.accept_eula: p.error('running the Minecraft server requires --accept-eula')
    if args.output.resolve() == args.world.resolve(): p.error('--output must differ from --world')
    started = time.time()
    upgrade(args.world, args.output, args.java, args.cache)
    print(f'upgraded world written to {args.output} in {time.time()-started:.0f} s')


if __name__ == '__main__':
    main()
