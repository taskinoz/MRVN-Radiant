#!/usr/bin/env python3
"""Bounded TF2 GAME_LUMP inspection and directory relocation (stdlib only).

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original code; schema attribution/evidence: docs/respawn/RESPAWN_GAME_LUMP.md.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

from inspect_bsp import FormatError, HEADER_SIZE, inspect

MAX_BYTES = 256 * 1024 * 1024
PROP = struct.Struct("<7fH2B2H4f4b4B2H")
ENTRY = struct.Struct("<4sHHII")


def parse_directory(data, base):
    """Directory offsets are BSP-absolute, including in default sidecars."""
    if len(data) > MAX_BYTES or base < HEADER_SIZE or base + len(data) > 0xffffffff:
        raise FormatError("GAME_LUMP size/base exceeds supported range")
    if len(data) < 4:
        raise FormatError("GAME_LUMP lacks directory count")
    count, = struct.unpack_from("<I", data)
    directory_end = 4 + count * ENTRY.size
    if directory_end > len(data):
        raise FormatError("GAME_LUMP directory count exceeds payload")
    entries, spans = [], []
    for i in range(count):
        ident, flags, version, offset, size = ENTRY.unpack_from(data, 4 + i * ENTRY.size)
        relative = offset - base
        if size or offset:
            if relative < directory_end or relative > len(data) or size > len(data) - relative:
                raise FormatError(f"game entry {i}: absolute payload range outside GAME_LUMP")
        if size:
            spans.append((relative, relative + size))
        entries.append({"id_hex": ident.hex(), "name": "sprp" if ident == b"prps" else ident.hex(),
                        "flags": flags, "version": version, "offset": offset, "length": size,
                        "relative_offset": relative if offset else None})
    spans.sort()
    if any(a[1] > b[0] for a, b in zip(spans, spans[1:])):
        raise FormatError("overlapping game-entry payloads")
    return entries


def decode_sprp_v13(data, include_props=False):
    if len(data) < 4:
        raise FormatError("sprp lacks model count")
    model_count, = struct.unpack_from("<I", data)
    cursor = 4 + 128 * model_count
    if cursor + 12 > len(data):
        raise FormatError("sprp model-name table exceeds payload")
    names = []
    for i in range(model_count):
        raw = data[4 + 128 * i:4 + 128 * (i + 1)]
        if b"\0" not in raw:
            raise FormatError(f"sprp model {i}: missing name terminator")
        # Keep bytes losslessly recoverable even if a game uses non-UTF8 names.
        names.append(raw.split(b"\0", 1)[0].decode("utf-8", errors="surrogateescape"))
    count, unknown_a, unknown_b = struct.unpack_from("<3I", data, cursor)
    cursor += 12
    end = cursor + count * PROP.size
    if end + 4 > len(data):
        raise FormatError("sprp placement count exceeds payload or lacks trailer count")
    extra_count, = struct.unpack_from("<I", data, end)
    if end + 4 + extra_count * 64 != len(data):
        raise FormatError("sprp unknown-record count/tail length mismatch")
    props, referenced = [], set()
    inactive_nonfinite = 0
    for i in range(count):
        r = PROP.unpack_from(data, cursor + i * PROP.size)
        if r[7] >= len(names):
            raise FormatError(f"sprp placement {i}: model index outside name table")
        if not all(math.isfinite(v) for v in (*r[:7], r[12])):
            raise FormatError(f"sprp placement {i}: nonfinite transform/lighting field")
        has_lighting_origin = bool(r[9] & 0x02)
        if not all(math.isfinite(v) for v in r[13:16]):
            if has_lighting_origin:
                raise FormatError(f"sprp placement {i}: nonfinite enabled lighting origin")
            inactive_nonfinite += 1
        referenced.add(r[7])
        if include_props:
            props.append({"index": i, "model_index": r[7], "model": names[r[7]],
                          "origin": r[:3], "angles_raw": r[3:6], "scale": r[6],
                          "solid": r[8], "flags": r[9], "skin": r[10], "cubemap_raw": r[11],
                          "fade_scale": r[12], "lighting_origin": r[13:16] if has_lighting_origin else None,
                          "lighting_origin_raw_hex": data[cursor + i * 64 + 40:cursor + i * 64 + 52].hex(),
                          "cpu_levels": r[16:18], "gpu_levels": r[18:20],
                          "diffuse_modulation": r[20:24], "collision_flags": r[24:26]})
    result = {"decoded": True, "model_names": names, "model_count": model_count,
              "placement_count": count, "referenced_model_count": len(referenced),
              "unknown_header_counts": [unknown_a, unknown_b], "unknown_record_count": extra_count,
              "inactive_nonfinite_lighting_origins": inactive_nonfinite,
              "unknown_records_sha256": hashlib.sha256(data[end + 4:]).hexdigest()}
    if include_props:
        result["placements"] = props
    return result


def inspect_blob(data, base, include_props=False):
    entries = parse_directory(data, base)
    for entry in entries:
        start, size = entry["relative_offset"], entry["length"]
        contents = data[start:start + size] if start is not None else b""
        entry["sha256"] = hashlib.sha256(contents).hexdigest()
        entry["decoded"] = False
        if entry["name"] == "sprp" and entry["version"] == 13 and entry["flags"] == 0:
            entry.update(decode_sprp_v13(contents, include_props))
    return entries


def read_blob(path, inventory):
    if inventory["version_raw"] != 37 or inventory["byte_order"] != "little":
        raise FormatError("GAME_LUMP tool requires little-endian TF2 BSP v37")
    if any(i["severity"] == "error" for i in inventory["issues"]):
        raise FormatError("BSP structural inventory failed")
    entry = inventory["lumps"][35]
    if entry["fourcc"]:
        raise FormatError("encoded GAME_LUMP is unsupported")
    external = next((e for e in entry["external_files"] if e["variant"] == "default"), None)
    size = external["size"] if external else entry["length"]
    if size > MAX_BYTES:
        raise FormatError("GAME_LUMP exceeds 256 MiB read limit")
    if not size:
        return b"", entry["offset"], "absent"
    if entry["version"] != 0:
        raise FormatError("unsupported GAME_LUMP outer record version")
    source = Path(external["path"]) if external else Path(path)
    with source.open("rb") as stream:
        stream.seek(0 if external else entry["offset"])
        data = stream.read(size)
    if len(data) != size:
        raise FormatError("truncated GAME_LUMP")
    return data, entry["offset"], "default_external" if external else "internal"


def inspect_game_lump(path, include_props=False, inventory=None):
    inv = inventory if inventory is not None else inspect(path)
    data, base, storage = read_blob(path, inv)
    return {"path": str(Path(path).resolve()), "storage": storage, "base": base,
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "entries": inspect_blob(data, base, include_props) if data else []}


def relocate_blob(data, old_base, new_base):
    """Patch directory offsets only; never infer private pointers in unknown lumps."""
    entries = inspect_blob(data, old_base)
    if new_base < HEADER_SIZE or new_base + len(data) > 0xffffffff:
        raise FormatError("relocated GAME_LUMP exceeds supported offset range")
    # Rewriting unknown formats could leave private absolute pointers dangling.
    if any(not e["decoded"] or e.get("unknown_record_count", 0) for e in entries):
        raise FormatError("relocation requires understood sprp v13 with no opaque extra records")
    result = bytearray(data)
    for i, entry in enumerate(entries):
        if entry["offset"]:
            struct.pack_into("<I", result, 4 + i * ENTRY.size + 8,
                             new_base + entry["relative_offset"])
    inspect_blob(result, new_base)
    return bytes(result)


def relocate_bsp(source, output):
    source, output = Path(source), Path(output)
    inv = inspect(source)
    if any(e["external_files"] for e in inv["lumps"]):
        raise FormatError("BSP relocation refuses sidecar-bearing inputs")
    if inv["size"] > MAX_BYTES:
        raise FormatError("BSP exceeds 256 MiB rewrite limit")
    blob, base, _ = read_blob(source, inv)
    if not blob:
        raise FormatError("BSP has no GAME_LUMP to relocate")
    new_base = (inv["size"] + 15) & ~15
    replacement = relocate_blob(blob, base, new_base)
    data = bytearray(source.read_bytes())
    if len(data) != inv["size"]:
        raise FormatError("BSP size changed during read")
    source_hash = hashlib.sha256(data).hexdigest()
    data.extend(bytes(new_base - len(data)))
    data.extend(replacement)
    struct.pack_into("<I", data, 16 + 35 * 16, new_base)
    with output.open("xb") as stream:
        stream.write(data)
    return {"source_sha256": source_hash,
            "output_sha256": hashlib.sha256(data).hexdigest(), "old_base": base,
            "new_base": new_base, "game_lump_bytes": len(blob)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    reader = commands.add_parser("inspect")
    reader.add_argument("bsp", type=Path)
    reader.add_argument("--placements", action="store_true")
    reader.add_argument("--output", type=Path)
    writer = commands.add_parser("relocate")
    writer.add_argument("source", type=Path)
    writer.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    try:
        result = (inspect_game_lump(args.bsp, args.placements) if args.command == "inspect"
                  else relocate_bsp(args.source, args.destination))
        text = json.dumps(result, indent=2) + "\n"
        if args.command == "inspect" and args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    except (OSError, FormatError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
