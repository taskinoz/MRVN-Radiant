#!/usr/bin/env python3
"""TF1/TF2 triangle collision decoding, range checks and optional OBJ export.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original code; schema provenance in docs/respawn/RESPAWN_TRICOLL_PORTALS.md.
"""
import argparse
import json
import math
from pathlib import Path


def triangle_indices(word):
    base = word & 0x3ff
    return base, base + ((word >> 10) & 0x7f), base + ((word >> 17) & 0x7f)


def node_count(triangles):
    # Native loader engine RVA 0x128090 has an explicit <=3 special case.
    return 0 if triangles <= 3 else 4 * ((triangles + 3) // 6)


def bevel_index(words, first, index, width=11):
    bit = width * index
    offset, shift = divmod(bit, 32)
    value = words[first + offset][0] >> shift
    if shift + width > 32:
        value |= words[first + offset + 1][0] << (32 - shift)
    return value & ((1 << width) - 1)


def check_bevel_chain(words, first, start, total, width, headers, current):
    while start + 2 <= total:
        value = bevel_index(words, first, start, width)
        value |= bevel_index(words, first, start + 1, width) << width
        start += 2
        count, target = value & 0x7f, value >> 7
        if target >= len(headers) or start + count > total:
            return False
        if any(bevel_index(words, first, i, width) >= headers[target][4] for i in range(start, start + count)):
            return False
        start += count
        # Both engines terminate on the current header pointer, not zero count.
        if target == current:
            return True
    return False


def check_tricoll_records(records, version=37):
    errors = []
    def error(index, message):
        errors.append({"severity": "error", "lump": 69, "record": index, "message": message})
    triangles, nodes, headers = (records.get(i, []) for i in (66, 68, 69))
    starts, bevels, vertices = (records.get(i, []) for i in (96, 97, 3))
    width = 10 if version == 29 else 11
    if len(starts) != len(triangles):
        error(None, "tricoll bevel-start count differs from packed triangle count")
    for index, h in enumerate(headers):
        _, _, texture, nv, nt, nb, fv, ft, fn, fb, *frame = h
        if not nv or not nt or fv < 0 or ft < 0 or fn < 0 or fb < 0:
            error(index, "invalid tricoll counts or negative offset")
            continue
        if texture >= len(records[2]):
            error(index, "tricoll texture reference outside TEXTURE_DATA")
        if fv + nv > len(vertices):
            error(index, "tricoll vertex slice outside VERTICES")
        if ft + nt > len(triangles):
            error(index, "tricoll triangle slice outside TRICOLL_TRIS")
            continue
        if fn + node_count(nt) > len(nodes):
            error(index, "tricoll node slice outside TRICOLL_NODES")
        valid_bevels = fb + (width * nb + 31) // 32 <= len(bevels)
        if not valid_bevels:
            error(index, "tricoll packed bevel slice outside TRICOLL_BEVEL_INDICES")
        if ft + nt <= len(starts):
            for (word,), (start,) in zip(triangles[ft:ft + nt], starts[ft:ft + nt]):
                count = (word >> 24) & 0xf
                if start > nb or (count < 15 and start + count > nb):
                    error(index, "tricoll triangle bevel range exceeds header bevel count")
                    break
                if valid_bevels and count < 15 and any(bevel_index(bevels, fb, i, width) >= nt for i in range(start, start + count)):
                    error(index, "tricoll bevel triangle index exceeds header triangle count")
                    break
                if valid_bevels and count == 15 and not check_bevel_chain(bevels, fb, start, nb, width, headers, index):
                    error(index, "invalid tricoll bevel chain")
                    break
        if not all(math.isfinite(v) for v in frame) or frame[-1] < 0:
            error(index, "nonfinite tricoll frame or negative node scale")
        for (word,) in triangles[ft:ft + nt]:
            if max(triangle_indices(word)) >= nv:
                error(index, "packed tricoll triangle vertex exceeds header vertex count")
                break
    return errors


def main(argv=None):
    from inspect_bsp import FormatError, inspect
    from validate_records import load_records
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bsp", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--obj", type=Path)
    args = parser.parse_args(argv)
    inv = inspect(args.bsp)
    if inv["version_raw"] not in (29, 37) or inv["byte_order"] != "little" or any(i["severity"] == "error" for i in inv["issues"]):
        raise FormatError("tricoll inspection requires structurally valid little-endian BSP v29 or v37")
    records = load_records(args.bsp, inv)
    errors = check_tricoll_records(records, inv["version_raw"])
    report = {"path": str(args.bsp.resolve()), "headers": len(records[69]),
              "triangles": len(records[66]), "nodes": len(records[68]),
              "small_headers": sum(h[4] <= 3 for h in records[69]), "issues": errors}
    if args.obj and not errors:
        with args.obj.open("x", encoding="ascii") as out:
            vertex = 1
            for i, h in enumerate(records[69]):
                out.write(f"g tricoll_{i}\n")
                for (word,) in records[66][h[7]:h[7] + h[4]]:
                    for local in triangle_indices(word):
                        out.write("v %.9g %.9g %.9g\n" % records[3][h[6] + local])
                    out.write(f"f {vertex} {vertex+1} {vertex+2}\n")
                    vertex += 3
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
