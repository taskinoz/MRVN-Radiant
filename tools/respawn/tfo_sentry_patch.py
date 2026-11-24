"""Locally patch TFORevive's sentry-native 0.7.8 DLL so TFO reaches map load.

The installed `sentry.dll` sets a 64 KiB stack guarantee on every thread from
`DllMain`. NVIDIA D3D worker threads use small stacks and overflow before the
map loads; Sentry then reports the overflow as a TFO crash. Upstream fixed the
regression in sentry-native 0.8.4 (getsentry/sentry-native#1193, PR #1196).

This tool makes `DllMain` return TRUE immediately. In 0.7.8 that is the entire
function apart from the stack-guarantee call. The patch is local, byte-exact,
and reversible; it does not change the compiler, BSPs, mods or game files.

Examples:
  python tools/respawn/tfo_sentry_patch.py --game "D:/Games/Titanfall Online" status
  python tools/respawn/tfo_sentry_patch.py --game "D:/Games/Titanfall Online" apply
  python tools/respawn/tfo_sentry_patch.py --game "D:/Games/Titanfall Online" revert
  python tools/respawn/tfo_sentry_patch.py --game "D:/Games/Titanfall Online" run -- \
      python tools/respawn/tfo_harness.py --game "D:/Games/Titanfall Online" ...
"""
import argparse
import hashlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ORIGINAL_SHA256 = '768f9a5f6ea8c8dd88e3b00c0c604fee09f745831b16de54397815623dda2c26'
PATCHED_SHA256 = 'f93c0d4be3ee78509f043bedecd3d58eed66492357194e1043434db74f813bf1'

# PE file offset for RVA 0x8800 in the 0.7.8 DLL (.text RVA 0x1000 / raw 0x400).
DLL_MAIN_OFFSET = 0x7C00
ORIGINAL_PREFIX = bytes.fromhex('4883ec28')  # sub rsp, 28h
PATCH = bytes.fromhex('b801000000c3')        # mov eax, 1 ; ret


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def make_patched_bytes(data):
    """Return the patched DLL bytes, or raise ValueError on an unexpected DLL."""
    if len(data) <= DLL_MAIN_OFFSET + len(PATCH):
        raise ValueError('sentry.dll is too short for the DllMain patch')
    if data[DLL_MAIN_OFFSET:DLL_MAIN_OFFSET + len(ORIGINAL_PREFIX)] != ORIGINAL_PREFIX:
        raise ValueError('unexpected DllMain prologue; refusing to patch this build')
    result = bytearray(data)
    result[DLL_MAIN_OFFSET:DLL_MAIN_OFFSET + len(PATCH)] = PATCH
    patched = bytes(result)
    if hashlib.sha256(patched).hexdigest() != PATCHED_SHA256:
        raise ValueError('patched DLL does not match the recorded hash')
    return patched


def paths(game, patch_dir):
    dll = Path(game) / 'Bin' / 'sentry.dll'
    patch_dir = Path(patch_dir).resolve()
    backup = patch_dir / 'sentry-original-backup.dll'
    return dll, backup


def state(dll):
    if not dll.exists():
        return 'missing'
    digest = sha256(dll)
    if digest == ORIGINAL_SHA256:
        return 'original'
    if digest == PATCHED_SHA256:
        return 'patched'
    return f'unknown ({digest})'


def show(dll, backup, label):
    print(f'{label}: {dll} ({state(dll)})')
    if backup.exists():
        print(f'backup: {backup} ({state(backup)})')
    else:
        print(f'backup: {backup} (absent)')


def do_apply(dll, backup):
    current = state(dll)
    if current == 'patched':
        show(dll, backup, 'sentry.dll')
        return 0
    if current != 'original':
        raise SystemExit(f'refusing to patch sentry.dll in state {current}')
    data = dll.read_bytes()
    patched = make_patched_bytes(data)
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(data)
    elif sha256(backup) != ORIGINAL_SHA256:
        raise SystemExit(f'backup has unexpected hash; refusing to overwrite {backup}')
    temporary = dll.with_name(dll.name + '.tfo-patch-tmp')
    temporary.write_bytes(patched)
    os.replace(temporary, dll)
    show(dll, backup, 'sentry.dll')
    return 0


def do_revert(dll, backup):
    current = state(dll)
    if current == 'original':
        show(dll, backup, 'sentry.dll')
        return 0
    if current != 'patched':
        raise SystemExit(f'refusing to revert sentry.dll in state {current}')
    if not backup.exists() or sha256(backup) != ORIGINAL_SHA256:
        raise SystemExit(f'valid original backup not found at {backup}')
    temporary = dll.with_name(dll.name + '.tfo-revert-tmp')
    temporary.write_bytes(backup.read_bytes())
    os.replace(temporary, dll)
    show(dll, backup, 'sentry.dll')
    return 0


@contextmanager
def patched_dll(dll, backup, enabled):
    if not enabled:
        yield False
        return
    applied = state(dll) == 'original'
    if applied:
        do_apply(dll, backup)
    elif state(dll) != 'patched':
        raise SystemExit(f'refusing to run with sentry.dll in state {state(dll)}')
    try:
        yield applied
    finally:
        if applied:
            do_revert(dll, backup)


def main():
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--game', type=Path, default=Path('D:/Games/Titanfall Online'))
    parser.add_argument('--patch-dir', type=Path,
                        default=root / '.local' / 'respawn' / 'tfo-crash-patch')
    subparsers = parser.add_subparsers(dest='action', required=True)
    subparsers.add_parser('status', help='show the current DLL and backup state')
    subparsers.add_parser('apply', help='patch the installed DLL and keep an original backup')
    subparsers.add_parser('revert', help='restore the original DLL from the backup')
    run_parser = subparsers.add_parser('run', help='run a command with the patch applied, then revert')
    run_parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    dll, backup = paths(args.game, args.patch_dir)

    if args.action == 'status':
        show(dll, backup, 'sentry.dll')
        return 0
    if args.action == 'apply':
        return do_apply(dll, backup)
    if args.action == 'revert':
        return do_revert(dll, backup)
    command = args.command
    if command and command[0] == '--':
        command = command[1:]
    if not command:
        raise SystemExit('run requires a command after --')
    with patched_dll(dll, backup, True):
        return subprocess.call(command, cwd=Path.cwd())


if __name__ == '__main__':
    sys.exit(main())
