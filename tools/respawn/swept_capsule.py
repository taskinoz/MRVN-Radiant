#!/usr/bin/env python3
"""Independent finite-triangle sweep oracle for a vertical rounded capsule.

Original mathematical reference, GPL-2.0-or-later. It minimizes segment/triangle
Euclidean distance along the motion, then bisects first contact. Distance to a
convex set along a line is convex. No native flags, bevel lists, collision skin,
contents, face culling or engine approximation is simulated.
"""
import math

from swept_box import vector, dot, sub, cross, sweep_triangle


def point_segment_distance2(point, a, b):
    edge = sub(b,a)
    length = dot(edge,edge)
    t = min(1.0,max(0.0,dot(sub(point,a),edge)/length)) if length else 0.0
    delta = tuple(point[i]-a[i]-t*edge[i] for i in range(3))
    return dot(delta,delta)


def point_triangle_distance2(point, triangle, normal):
    delta = sub(point,triangle[0])
    amount = dot(delta,normal)/dot(normal,normal)
    projected = tuple(point[i]-amount*normal[i] for i in range(3))
    if all(dot(cross(sub(triangle[(i+1)%3],triangle[i]),sub(projected,triangle[i])),normal) >= -1e-8 for i in range(3)):
        return amount*amount*dot(normal,normal)
    return min(point_segment_distance2(point,triangle[i],triangle[(i+1)%3]) for i in range(3))


def segment_distance2(a,b,c,d):
    u,v,w = sub(b,a),sub(d,c),sub(a,c)
    aa,bb,cc,dd,ee = dot(u,u),dot(u,v),dot(v,v),dot(u,w),dot(v,w)
    result = min(point_segment_distance2(a,c,d),point_segment_distance2(b,c,d),
                 point_segment_distance2(c,a,b),point_segment_distance2(d,a,b))
    determinant = aa*cc-bb*bb
    if determinant > 1e-12*max(aa*cc,1.0):
        s,t = (bb*ee-cc*dd)/determinant,(aa*ee-bb*dd)/determinant
        if 0 <= s <= 1 and 0 <= t <= 1:
            delta = tuple(w[i]+s*u[i]-t*v[i] for i in range(3))
            result = min(result,dot(delta,delta))
    return result


def segment_triangle_distance2(a,b,triangle,normal):
    direction = sub(b,a)
    denominator = dot(direction,normal)
    if abs(denominator) > 1e-12:
        t = dot(sub(triangle[0],a),normal)/denominator
        if 0 <= t <= 1:
            point = tuple(a[i]+t*direction[i] for i in range(3))
            if point_triangle_distance2(point,triangle,normal) < 1e-16:
                return 0.0
    return min(point_triangle_distance2(a,triangle,normal),point_triangle_distance2(b,triangle,normal),
               *(segment_distance2(a,b,triangle[i],triangle[(i+1)%3]) for i in range(3)))


def sweep_capsule_triangle(start,end,mins,maxs,triangle):
    start,end,mins,maxs = map(vector,(start,end,mins,maxs))
    triangle = tuple(map(vector,triangle))
    widths = sub(maxs,mins)
    if len(triangle) != 3 or min(widths) < 0 or abs(widths[0]-widths[1]) > 1e-8 or widths[2] < widths[0]:
        raise ValueError('Expected a triangle and a vertical capsule with equal XY widths and height >= diameter')
    normal = cross(sub(triangle[1],triangle[0]),sub(triangle[2],triangle[0]))
    if dot(normal,normal) < 1e-20:
        raise ValueError('Degenerate triangle')
    radius = widths[0]/2
    if radius == 0 and widths[2] == 0:
        return sweep_triangle(start,end,mins,maxs,triangle)
    velocity = sub(end,start)
    offset = ((mins[0]+maxs[0])/2,(mins[1]+maxs[1])/2,mins[2]+radius)
    height = widths[2]-2*radius
    def distance2(t):
        a = tuple(start[i]+offset[i]+t*velocity[i] for i in range(3))
        b = (a[0],a[1],a[2]+height)
        return segment_triangle_distance2(a,b,triangle,normal)
    threshold = radius*radius
    if distance2(0) <= threshold:
        return 0.0
    # Golden-section minimization finds the closest point along this motion.
    low,high = 0.0,1.0
    ratio = (math.sqrt(5)-1)/2
    a,b = high-ratio*(high-low),low+ratio*(high-low)
    da,db = distance2(a),distance2(b)
    for _ in range(55):
        if da <= db:
            high,b,db = b,a,da
            a = high-ratio*(high-low); da = distance2(a)
        else:
            low,a,da = a,b,db
            b = low+ratio*(high-low); db = distance2(b)
    closest = (low+high)/2
    if distance2(closest) > threshold+1e-8:
        return None
    low,high = 0.0,closest
    for _ in range(48):
        middle = (low+high)/2
        if distance2(middle) <= threshold:
            high = middle
        else:
            low = middle
    return high


def sweep_capsule_mesh(start,end,mins,maxs,triangles):
    hits = [hit for triangle in triangles
            if (hit := sweep_capsule_triangle(start,end,mins,maxs,triangle)) is not None]
    return min(hits) if hits else None
