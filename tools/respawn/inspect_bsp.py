#!/usr/bin/env python3
"""Read-only rBSP inventory. Python 3.10+, standard library only.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Format references: docs/respawn/RESPAWN_SOURCES.md. No upstream implementation copied.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

LUMP_COUNT = 128
HEADER_SIZE = 16 + LUMP_COUNT * 16
CHUNK_SIZE = 1024 * 1024
NAMES_FILE = Path(__file__).resolve().parents[1] / "remap/source/lump_names.h"


class FormatError(ValueError):
    pass


def digest_region(stream, offset, length):
    stream.seek(offset)
    digest = hashlib.sha256()
    while length:
        block = stream.read(min(length, CHUNK_SIZE))
        if not block:
            raise FormatError("file truncated while hashing")
        digest.update(block)
        length -= len(block)
    return digest.hexdigest()


def lump_names(version):
    # Names reflect this compiler's definitions, not proof of a schema match.
    prefix = {29: "R1", 37: "R2", 47: "R5"}.get(version)
    if prefix is None:
        return {}
    pattern = rf"^#define {prefix}_LUMP_(\w+)\s+(0x[0-9A-Fa-f]+)"
    return {int(number, 16): name for name, number in
            re.findall(pattern, NAMES_FILE.read_text(), re.MULTILINE)}


def inspect(path, hashes=False):
    path = Path(path)
    with path.open("rb") as stream:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        header = stream.read(HEADER_SIZE)
        if len(header) != HEADER_SIZE:
            raise FormatError(f"truncated header: {len(header)} of {HEADER_SIZE} bytes")
        magic = header[:4]
        endian = {b"rBSP": "<", b"PSBr": ">"}.get(magic)
        if endian is None:
            raise FormatError(f"invalid rBSP magic: {magic!r}")
        raw_version, revision, max_lump = struct.unpack_from(endian + "3I", header, 4)
        if max_lump != 127:
            raise FormatError(f"unsupported maximum lump index: {max_lump}")
        major, minor = raw_version & 0xFFFF, raw_version >> 16
        streamed = major >= 49 and minor == 1
        unknown_layout = minor != 0 and not streamed
        names = lump_names(raw_version)
        profile = {29: "Titanfall / Titanfall Online", 37: "Titanfall 2",
                   47: "Apex Legends (compiler v47 target)"}.get(raw_version)
        report = {"path": str(path.resolve()), "size": size,
                  "byte_order": "little" if endian == "<" else "big",
                  "version_raw": raw_version, "version": [major, minor],
                  "revision": revision, "max_lump_index": max_lump,
                  "compiler_profile_hint": profile,
                  "issues": [], "lumps": [], "entity_files": []}
        if profile is None:
            report["issues"].append({"severity": "warning", "message":
                "No compiler schema assigned to this version; inventory uses numeric lump IDs."})
        if endian == ">":
            report["issues"].append({"severity": "warning", "message":
                "Big-endian inventory only; compiler compatibility is unverified."})
        if unknown_layout:
            report["issues"].append({"severity": "warning", "message":
                "Unknown version flags; payload location validation skipped."})
        intervals = []
        for index in range(LUMP_COUNT):
            offset, length, version, fourcc = struct.unpack_from(
                endian + "4I", header, 16 + index * 16)
            lump = {"index": index, "name": names.get(index), "offset": offset,
                    "length": length, "version": version, "fourcc": fourcc,
                    "storage": "empty", "external_files": []}
            report["lumps"].append(lump)
            # Overrides can exist even with a zero-length internal directory entry.
            for suffix in ("", ".client"):
                sidecar = path.with_name(f"{path.name}.{index:04x}.bsp_lump{suffix}")
                if not sidecar.is_file():
                    sidecar = path.with_name(f"{path.name}.{index:04X}.bsp_lump{suffix}")
                if sidecar.is_file():
                    actual = sidecar.stat().st_size
                    entry = {"path": str(sidecar.resolve()), "size": actual,
                             "variant": "client" if suffix else "default"}
                    if hashes:
                        with sidecar.open("rb") as extra:
                            entry["sha256"] = digest_region(extra, 0, actual)
                    lump["external_files"].append(entry)
                    if not actual:
                        report["issues"].append({"severity": "error", "lump": index,
                                                  "message": "Empty external lump file."})
            external = bool(lump["external_files"])
            if external:
                lump["storage"] = "external"
            if not length:
                continue
            if unknown_layout:
                lump["storage"] = "external" if external else "unresolved_version_layout"
                continue
            # Streamed Apex offsets are not ranges within the main file.
            if streamed:
                if not external:
                    lump["storage"] = "missing_external"
                    report["issues"].append({"severity": "error", "lump": index,
                                              "message": "Missing streamed lump file."})
                continue
            valid = offset >= HEADER_SIZE and offset + length <= size
            if not valid:
                if not external:
                    lump["storage"] = "invalid"
                    report["issues"].append({"severity": "error", "lump": index,
                                              "message": "Lump range is outside the payload."})
                continue
            intervals.append((offset, offset + length, index))
            lump["storage"] = "internal_with_override" if external else "internal"
            if hashes:
                lump["sha256"] = digest_region(stream, offset, length)
            if offset % 4:
                report["issues"].append({"severity": "warning", "lump": index,
                                          "message": "Lump offset is not four-byte aligned."})
        # Report every intersecting pair, including nested intervals.
        active = []
        for start, end, index in sorted(intervals):
            active = [(a, b, i) for a, b, i in active if b > start]
            for _, _, other in active:
                report["issues"].append({"severity": "error", "lump": index,
                    "message": f"Internal payload overlaps lump {other}."})
            active.append((start, end, index))
        if hashes:
            report["sha256"] = digest_region(stream, 0, size)
    for kind in ("env", "fx", "script", "snd", "spawn"):
        sidecar = path.with_name(f"{path.stem}_{kind}.ent")
        if not sidecar.is_file():
            continue
        actual = sidecar.stat().st_size
        with sidecar.open("rb") as stream:
            first_line = stream.readline(4097)
            known = first_line.startswith((b"ENTITIES01", b"ENTITIES02"))
            terminated = first_line.endswith(b"\n")
            if not known or not terminated:
                report["issues"].append({"severity": "warning", "message":
                    f"Unrecognized or unterminated entity header: {sidecar.name}"})
            entry = {"kind": kind, "path": str(sidecar.resolve()), "size": actual,
                     "header": first_line[:4096].decode("ascii", errors="replace").rstrip()}
            if hashes:
                entry["sha256"] = digest_region(stream, 0, actual)
            report["entity_files"].append(entry)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path,
                        help="BSP files or folders of extracted BSPs (recursive)")
    parser.add_argument("--hash", action="store_true", help="include SHA-256 hashes")
    parser.add_argument("--output", type=Path, help="write JSON report to this file")
    args = parser.parse_args(argv)
    paths = set()
    for path in args.paths:
        if path.is_dir():
            paths.update(p.resolve() for p in path.rglob("*")
                         if p.is_file() and p.suffix.lower() == ".bsp")
        else:
            paths.add(path.resolve())
    result = {"schema_version": 1, "maps": [], "errors": []}
    if not paths:
        result["errors"].append({"message": "No BSP files found."})
    for path in sorted(paths):
        try:
            result["maps"].append(inspect(path, args.hash))
        except (OSError, FormatError) as exc:
            result["errors"].append({"path": str(path), "message": str(exc)})
    failed = bool(result["errors"]) or any(
        issue["severity"] == "error" for report in result["maps"] for issue in report["issues"])
    payload = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
