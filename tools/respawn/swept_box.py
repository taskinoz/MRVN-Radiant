#!/usr/bin/env python3
"""Independent continuous SAT oracle for an axis-aligned box and triangles.

Original mathematical reference, GPL-2.0-or-later. This uses authored positions,
not BSP flags, bevel lists or native trace code. Triangles are closed and two
sided; callers comparing a one-sided engine must choose front-facing sweeps.
No engine collision skin, contents masks or start-solid policy is simulated.
"""
import math


def vector(value):
    result = tuple(float(v) for v in value)
    if len(result) != 3 or not all(math.isfinite(v) for v in result):
        raise ValueError('Expected three finite coordinates')
    return result


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def sweep_triangle(start, end, mins, maxs, triangle):
    """Return first contact fraction in [0,1], or None for no intersection.

    On every separating axis the projected moving box must overlap the fixed
    triangle. Intersect those time intervals for the triangle normal, the three
    box normals and the nine edge cross products. These are all SAT axes for
    this pair, so no triangle adjacency or face-selection heuristic is involved.
    """
    start, end, mins, maxs = map(vector, (start, end, mins, maxs))
    triangle = tuple(map(vector, triangle))
    if len(triangle) != 3 or any(a > b for a, b in zip(mins, maxs)):
        raise ValueError('Expected a triangle and ordered box extents')
    edges = [sub(triangle[(i+1) % 3], triangle[i]) for i in range(3)]
    normal = cross(edges[0], edges[1])
    if dot(normal, normal) < 1e-20:
        raise ValueError('Degenerate triangle')
    basis = ((1,0,0), (0,1,0), (0,0,1))
    axes = [normal, *basis, *(cross(edge, axis) for edge in edges for axis in basis)]
    center = tuple(start[i] + (mins[i]+maxs[i])*0.5 for i in range(3))
    extent = tuple((maxs[i]-mins[i])*0.5 for i in range(3))
    velocity = sub(end, start)
    enter, leave = 0.0, 1.0
    for axis in axes:
        length = math.sqrt(dot(axis, axis))
        if length < 1e-10:
            continue
        axis = tuple(v/length for v in axis)
        projection = [dot(axis, point) for point in triangle]
        radius = sum(abs(axis[i])*extent[i] for i in range(3))
        low, high = min(projection)-radius, max(projection)+radius
        position, speed = dot(axis, center), dot(axis, velocity)
        if abs(speed) < 1e-12:
            if position < low-1e-10 or position > high+1e-10:
                return None
            continue
        first, last = sorted(((low-position)/speed, (high-position)/speed))
        enter, leave = max(enter, first), min(leave, last)
        if enter > leave+1e-10:
            return None
    return min(1.0, max(0.0, enter))


def sweep_mesh(start, end, mins, maxs, triangles):
    hits = [hit for triangle in triangles
            if (hit := sweep_triangle(start, end, mins, maxs, triangle)) is not None]
    return min(hits) if hits else None


def sweep_halfspaces(start, end, mins, maxs, planes):
    """Clip a moving box against expanded convex half-spaces n.p <= d.

    Callers supply every relevant separating plane, including edge bevels.
    This is deliberately a different representation from the triangle SAT
    oracle, so compiler plane sets can be checked against authored surfaces.
    """
    start,end,mins,maxs = map(vector,(start,end,mins,maxs))
    if any(a>b for a,b in zip(mins,maxs)):
        raise ValueError('Expected ordered box extents')
    velocity = sub(end,start)
    enter,leave = 0.0,1.0
    for plane in planes:
        plane = tuple(float(v) for v in plane)
        if len(plane)!=4 or not all(math.isfinite(v) for v in plane) or dot(plane[:3],plane[:3])==0:
            raise ValueError('Expected a finite nonzero plane')
        n,d = plane[:3],plane[3]
        expanded = d-sum(min(n[i]*mins[i],n[i]*maxs[i]) for i in range(3))
        distance,speed = dot(n,start)-expanded,dot(n,velocity)
        if abs(speed)<1e-12:
            if distance>1e-10:return None
            continue
        crossing = -distance/speed
        if speed<0:enter = max(enter,crossing)
        else:leave = min(leave,crossing)
        if enter>leave+1e-10:return None
    return min(1.0,max(0.0,enter))
