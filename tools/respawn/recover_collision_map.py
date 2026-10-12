#!/usr/bin/env python3
"""Recover selected v29/v37 collision brushes as a partial, editable Radiant map.

Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
Format research: docs/RESPAWN_SOURCES.md. Original implementation.
Does not recover render meshes, props, entities, transforms, lighting or UVs.
All recovered brushes are placed in worldspawn in their stored coordinates.
"""
import argparse
import math
from pathlib import Path

from inspect_bsp import inspect
from validate_records import load_records, validate


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def plane_points(plane):
    n = plane[:3]
    length = math.sqrt(sum(v*v for v in n))
    if not all(math.isfinite(v) for v in plane) or length < 1e-8:
        raise ValueError("invalid collision plane")
    n = tuple(v / length for v in n)
    center = tuple(v * plane[3] / length for v in n)
    u = cross((0, 0, 1) if abs(n[2]) < 0.9 else (0, 1, 0), n)
    ulen = math.sqrt(sum(v*v for v in u))
    u = tuple(v / ulen for v in u)
    v = cross(n, u)
    # Radiant .map planes use (p0-p1) cross (p2-p1), opposite glTF winding.
    return (center, tuple(center[i]+64*v[i] for i in range(3)),
            tuple(center[i]+64*u[i] for i in range(3)))


def recover(path, output):
    report = validate(path)
    if report["issues"]:
        raise ValueError("selected record validation failed")
    records = load_records(path, inspect(path))
    base = records[85][0][6] if records[85] else 0
    lines = ['// Partial collision recovery; original entity/model placement is not restored.',
             '{', '"classname" "worldspawn"', '"message" "Recovered collision brushes only"']
    for b in records[92]:
        planes = []
        for axis in range(3):
            for sign in (1, -1):
                normal = [0, 0, 0]
                normal[axis] = sign
                planes.append((*normal, sign * b[axis] + b[axis+6]))
        for j in range(b[4]):
            offset = b[9] + j
            index = base + offset - records[93][offset][0]
            planes.append(records[1][index])
        lines.append('{')
        for plane in planes:
            coords = ' '.join('( %.9f %.9f %.9f )' % p for p in plane_points(plane))
            lines.append(coords + ' compat/recovered_collision 0 0 0 1 1 0 0 0')
        lines.append('}')
    lines.append('}')
    with Path(output).open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    return len(records[92])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bsp', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(f'Recovered {recover(args.bsp, args.output)} collision brushes into {args.output}')
