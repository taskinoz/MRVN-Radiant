#!/usr/bin/env python3
"""Read-only TF2 world-index budget audit for an explicitly identified engine.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Research provenance: docs/respawn/RESPAWN_GRAVEMIND.md. Original implementation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from inspect_bsp import FormatError, inspect
from validate_records import check_records, load_records

ENGINE_SHA256 = "58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487"
INDEX_CAPACITY = 3_145_728
SORT_CAPACITY = 8_192


def budget(meshes, sort_count, engine_sha256):
    """Conservative all-visible cost; not a runtime visibility/performance test."""
    triangles = sum(m[1] for m in meshes)
    odd = sum(m[1] & 1 for m in meshes)
    padded = 3 * (triangles + odd)
    matched = engine_sha256.lower() == ENGINE_SHA256
    issues = []
    if matched and padded > INDEX_CAPACITY:
        issues.append("all-visible padded world-index estimate exceeds audited engine capacity")
    if matched and sort_count > SORT_CAPACITY:
        issues.append("material-sort count exceeds Gravemind's reported loader capacity")
    return {
        "engine_sha256": engine_sha256, "engine_profile_matched": matched,
        "world_meshes": len(meshes), "serialized_triangle_slots": triangles,
        "odd_triangle_meshes": odd, "serialized_index_count": triangles * 3,
        "all_visible_padded_index_estimate": padded, "material_sorts": sort_count,
        "index_capacity": INDEX_CAPACITY if matched else None,
        "index_capacity_fraction": padded / INDEX_CAPACITY if matched else None,
        "material_sort_capacity_reported": SORT_CAPACITY if matched else None,
        "draw_batch_capacity": 2048 if matched else None,
        "draw_batches": None,
        "scope": "world model only; includes disabled slots; excludes native model rendering",
        "warnings": (["unknown engine hash: capacity comparisons were not applied"] if not matched else []) + [
            "pair-padding cost comes from Gravemind; the capacity comparison was locally re-audited",
            "8192-sort loader limit is Gravemind research, not independently re-audited here",
            "draw batches depend on runtime light masks and cannot be certified by mesh count",
            "all-visible estimate exceeding capacity is not proof a selective-visibility map fails",
        ],
        "issues": issues,
    }


def audit(path, engine):
    inv = inspect(path)
    if inv["version_raw"] != 37 or inv["byte_order"] != "little":
        raise FormatError("budget audit requires little-endian TF2 BSP v37")
    if any(i["severity"] == "error" for i in inv["issues"]):
        raise FormatError("BSP structural inventory failed")
    records = load_records(path, inv)
    issues = check_records(records)
    if issues:
        raise FormatError(f"selected-record validation failed: {issues[:3]}")
    if not records[14]:
        raise FormatError("BSP has no world model")
    digest = hashlib.sha256()
    with Path(engine).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    first, count = records[14][0][6:8]
    report = budget(records[80][first:first + count], len(records[82]), digest.hexdigest())
    report["path"] = str(Path(path).resolve())
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bsp", type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = audit(args.bsp, args.engine)
    except (OSError, FormatError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return int(bool(report["issues"]))


if __name__ == "__main__":
    sys.exit(main())
