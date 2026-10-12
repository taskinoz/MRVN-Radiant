#!/usr/bin/env python3
"""Extract map samples through an explicitly supplied tf2vpk executable.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
tf2vpk attribution and the tested revision: docs/RESPAWN_SOURCES.md.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def map_path(name):
    # Reject path traversal and Windows alternate stream/drive syntax even on Unix.
    path = PurePosixPath(name)
    if (not name or "\\" in name or ":" in name or path.is_absolute()
            or any(part in ("", ".", "..") for part in name.split("/"))):
        raise ValueError(f"unsafe archive path: {name!r}")
    return path.parts[0] == "maps" and (
        name.endswith((".bsp", ".ent", ".bsp_lump", ".bsp_lump.client")))


def extract(tool, archive, destination, relaxed_flags=False):
    tool, archive, destination = (Path(p).resolve() for p in (tool, archive, destination))
    if not tool.is_file() or not archive.is_file():
        raise ValueError("tool and archive must be existing files")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("destination must be empty; existing samples will not be overwritten")
    env = dict(os.environ)
    # Do not inherit a setting that silently disables checks.
    env.pop("TF2VPKDEBUG", None)
    if relaxed_flags:
        env["TF2VPKDEBUG"] = "nosanitycheck"
    command = [str(tool), "list", str(archive), "-e", "/maps"]
    listing = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
    names = sorted(set(name for name in listing.stdout.splitlines() if map_path(name)))
    if not any(name.endswith(".bsp") for name in names):
        raise ValueError("no BSP files found in this archive")
    destination.mkdir(parents=True, exist_ok=True)
    report = {"schema_version": 1, "tool": str(tool), "tool_sha256": sha256(tool),
              "archive": str(archive), "directory_sha256": sha256(archive),
              "relaxed_flags": relaxed_flags, "files": [], "complete": False}
    manifest = destination / "extraction.json"
    try:
        for name in names:
            output = destination.joinpath(*PurePosixPath(name).parts)
            # Resolve existing symlinks before writing, including any created
            # between invocations; do not follow them outside the destination.
            if not output.resolve().is_relative_to(destination):
                raise ValueError(f"archive path escapes destination: {name}")
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with output.open("xb") as stream:
                    result = subprocess.run([str(tool), "get", str(archive), name],
                                            env=env, stdout=stream, stderr=subprocess.PIPE)
                    if result.returncode:
                        raise RuntimeError(result.stderr.decode(errors="replace")[-4000:])
            except Exception:
                # Preserve failed extraction evidence; it is never marked complete.
                report["failed_file"] = name
                raise
            report["files"].append({"path": name, "size": output.stat().st_size,
                                    "sha256": sha256(output)})
        report["complete"] = True
    finally:
        manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tool", required=True, type=Path)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--relaxed-flags", action="store_true",
                        help="disable upstream metadata sanity checks (CRC checks remain enabled)")
    args = parser.parse_args(argv)
    try:
        report = extract(args.tool, args.archive, args.destination, args.relaxed_flags)
        print(f"Extracted {len(report['files'])} map files to {args.destination}")
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
