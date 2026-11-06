#!/usr/bin/env python3
"""TF1/TF2 cell/portal topology inspection and bounded cross-reference checks.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Original code; schema provenance in docs/respawn/RESPAWN_TRICOLL_PORTALS.md.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path


def locate_cell(records, point):
    nodes, planes = records[106], records[1]
    index, visited = 0, set()
    while 0 <= index < len(nodes) and index not in visited:
        visited.add(index)
        plane, child = nodes[index]
        if plane == -1:
            if child >= len(records[107]):
                break
            return child
        if plane < 0 or plane >= len(planes):
            break
        p = planes[plane]
        index = child + int(sum(point[a] * p[a] for a in range(3)) < p[3])
    raise ValueError("invalid or cyclic cell BSP traversal")


def connected(records, start, end):
    pending, seen = [start], set()
    while pending:
        cell = pending.pop()
        if cell == end:
            return True
        if cell in seen:
            continue
        seen.add(cell)
        n, first, _, _ = records[107][cell]
        pending.extend(p[5] for p in records[108][first:first+n] if p[1] == 0 and p[5] not in seen)
    return False


def ordering_cycles(records, samples=200):
    """Count camera-facing portal cycles the TF1/TF2 renderer cannot order.

    Both clients order cells by one depth-first walk over portals whose front
    faces the camera, visiting each cell once (TFO client.dll 0x5e9030, TF2
    0x2eae40), then pass each cell's view region on in that order and consume it.
    A camera-facing portal into a cell ordered earlier is a cycle: whatever it
    carries is dropped and visible geometry disappears. Cameras sit just in
    front of sampled portals. Returns (cameras tested, back edges found).

    Retail TF1 has some (Angel City 41, Relic 21 over ~100 cameras), which frustum
    clipping evidently never exercises; TF2 Coliseum and Glitch have none. remap's
    cells are whole BSP subtrees and must have none."""
    cells, portals, vertices, refs, planes = (records[i] for i in (107, 108, 109, 112, 1))
    regular = [(c, p) for c, cell in enumerate(cells) for p in portals[cell[1]:cell[1] + cell[0]] if p[1] == 0]
    step = max(1, len(regular) // samples)
    tested = back = 0
    for source, p in regular[::step]:
        points = [vertices[refs[p[4] + k][0]] for k in range(p[2])]
        plane = planes[p[6]]
        sign = 1 if p[0] == 0 else -1
        camera = [sum(q[a] for q in points) / len(points) + plane[a] * sign * 2 for a in range(3)]
        try:
            start = locate_cell(records, camera)
        except ValueError:
            continue
        if start != source:
            continue

        def faces(q):
            n = planes[q[6]]
            return (sum(n[a] * camera[a] for a in range(3)) - n[3]) * (1 if q[0] == 0 else -1) > 0
        visited, order, stack = {start}, [], [(start, 0)]
        while stack:
            cell, k = stack[-1]
            if k < cells[cell][0]:
                stack[-1] = (cell, k + 1)
                q = portals[cells[cell][1] + k]
                if q[1] == 0 and q[5] not in visited and faces(q):
                    visited.add(q[5]); stack.append((q[5], 0))
            else:
                order.append(cell); stack.pop()
        position = {c: i for i, c in enumerate(reversed(order))}
        tested += 1
        for cell in position:
            for q in portals[cells[cell][1]:cells[cell][1] + cells[cell][0]]:
                if q[1] == 0 and q[5] in position and faces(q) and position[q[5]] <= position[cell]:
                    back += 1
    return tested, back


def check_portal_records(records, version=37):
    issues = []
    def error(lump, index, message):
        issues.append({"severity": "error", "lump": lump, "record": index, "message": message})
    nodes, cells, portals, vertices, edges = (records[i] for i in (106, 107, 108, 109, 110))
    vertex_edges, vertex_refs, edge_refs, ie, iv, ih = (records[i] for i in range(111, 117))
    if not nodes and not cells and not portals:
        return issues
    if version in (29, 37) and len(cells) > 1022:
        error(107, None, "TF1/TF2 cell count exceeds the 1024-bit native mask with two sentinel bits")
    if not nodes or not cells:
        error(106, None, "cell BSP and cell table must both be present")
    if len(vertex_refs) != len(edge_refs):
        error(112, None, "portal vertex and edge reference counts differ")
    if len(vertex_edges) != len(vertices):
        error(111, None, "portal vertex incidence count differs from vertices")
    if len(ih) != len(edges) or len(ie) != len(iv):
        error(116, None, "portal edge/intersection parallel counts differ")
    for i, (plane, child) in enumerate(nodes):
        if plane == -1:
            if child >= len(cells):
                error(106, i, "cell BSP leaf references missing cell")
        elif plane < 0 or plane >= len(records[1]) or child + 1 >= len(nodes):
            error(106, i, "cell BSP plane/child range is invalid")
    # Iterative DFS avoids recursion limits and distinguishes cycles from sharing.
    stack, gray, black = ([(0, False)] if nodes else []), set(), set()
    while stack:
        index, done = stack.pop()
        if done:
            gray.discard(index); black.add(index)
            continue
        if index in gray:
            error(106, index, "cyclic cell BSP")
            continue
        if index in black or index >= len(nodes):
            continue
        gray.add(index); stack.append((index, True))
        plane, child = nodes[index]
        if plane >= 0 and child + 1 < len(nodes):
            stack.extend(((child + 1, False), (child, False)))
    for i, cell in enumerate(cells):
        if cell[1] + cell[0] > len(portals):
            error(107, i, "cell portal slice exceeds PORTALS")
    for i, p in enumerate(portals):
        reverse, kind, count, _, first, destination, plane = p
        if reverse not in (0, 1) or count < 3 or first + count > len(vertex_refs) or first + count > len(edge_refs):
            error(108, i, "portal direction or polygon reference slice is invalid")
        if plane >= len(records[1]):
            error(108, i, "portal plane outside PLANES")
        if (kind == 0 and destination >= len(cells)) or (kind == 1 and destination != len(cells) + 1):
            error(108, i, "portal destination or sky sentinel is invalid")
        if kind not in (0, 1, 2):
            error(108, i, "unsupported portal kind")
    for i, (vertex,) in enumerate(vertex_refs):
        if vertex >= len(vertices):
            error(112, i, "portal vertex reference outside PORTAL_VERTICES")
    for i, (word,) in enumerate(edge_refs):
        if word >> 1 >= len(edges):
            error(113, i, "oriented portal edge reference outside PORTAL_EDGES")
    for i, edge in enumerate(edges):
        if any(v >= len(vertices) for v in edge):
            error(110, i, "portal edge endpoint outside PORTAL_VERTICES")
    for i, block in enumerate(vertex_edges):
        if any(e < -1 or e >= len(edges) for e in block):
            error(111, i, "portal vertex incidence references missing edge")
    for i, (first, count) in enumerate(ih):
        if first + count > len(ie) or first + count > len(iv):
            error(116, i, "portal intersection block slice outside tables")
    for i, (es, vs) in enumerate(zip(ie, iv)):
        if any((e == -1) != (v == -1) or e < -1 or v < -1 or e >= len(edges) or v >= len(vertices)
               for e, v in zip(es, vs)):
            error(114, i, "invalid portal intersection edge/vertex pair")
    for i, p in enumerate(vertices):
        if not all(math.isfinite(v) for v in p):
            error(109, i, "nonfinite portal vertex")
    access, refs, bounds = (records[i] for i in (119, 120, 121))
    if len(access) < len(cells):
        error(119, None, "missing per-cell access roots")
    if len(refs) != len(bounds):
        error(121, None, "object references/bounds counts differ")
    for i, n in enumerate(access):
        if n[9] + n[3] > len(access) or n[10] + n[4] > len(refs):
            error(119, i, "cell access child/reference slice exceeds table")
        # The renderer culls a node by its bounds before drawing its references;
        # every retail node encloses its references (Angel City, Relic).
        elif all(math.isfinite(v) for v in (*n[:3], *n[6:9])) and len(refs) == len(bounds):
            for k in range(n[10], n[10] + n[4]):
                b = bounds[k]
                if any(b[a] < n[a] - 1 or b[a + 4] > n[a + 6] + 1 for a in range(3)):
                    error(119, i, "cell access node does not enclose its object reference bounds")
                    break
        # Retail has global environment roots with flags 0x02 and infinite bounds.
        global_root = i < len(cells) and cells[i][2] & 2
        infinite_root = global_root and all(n[a] == -math.inf and n[a+6] == math.inf for a in range(3))
        # Retail TF1 mp_o2 also has an empty global root initialized with the
        # float32 min/max accumulation sentinels, rather than infinite bounds.
        maximum = float.fromhex('0x1.fffffep+127')
        empty_root = (global_root and n[3:6] == (0, 0, 0) and
                      all(n[a] == maximum and n[a+6] == -maximum for a in range(3)))
        if not empty_root and ((not infinite_root and not all(math.isfinite(v) for v in (*n[:3], *n[6:9]))) or
                               any(n[a] > n[a+6] for a in range(3))):
            error(119, i, "invalid cell access bounds")
    return issues


def main(argv=None):
    from inspect_bsp import FormatError, inspect
    from validate_records import load_records
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bsp", type=Path)
    parser.add_argument("--point", type=float, nargs=3)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    inv = inspect(args.bsp)
    if inv["version_raw"] not in (29, 37) or inv["byte_order"] != "little" or any(i["severity"] == "error" for i in inv["issues"]):
        raise FormatError("portal inspection requires structurally valid little-endian BSP v29/v37")
    records = load_records(args.bsp, inv)
    issues = check_portal_records(records, inv["version_raw"])
    report = {"path": str(args.bsp.resolve()), "cells": len(records[107]),
              "portals": len(records[108]), "portal_types": dict(Counter(p[1] for p in records[108])),
              "issues": issues}
    if args.point and not issues:
        report["point_cell"] = locate_cell(records, args.point)
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
