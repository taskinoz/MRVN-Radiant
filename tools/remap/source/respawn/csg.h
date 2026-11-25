/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Hidden-face removal for brush faces. Respawn writers emit brush faces
 * directly, so faces buried in or flush against other brushes would otherwise
 * draw, z-fighting where two brushes share a surface.
 *
 * A face fragment is hidden by an occluding solid when it lies inside it, or
 * on its boundary facing into it. Where two solids share a coplanar surface
 * facing the same way, the later solid's face is kept.
 */
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace Respawn::Csg {

using Point = std::array<double, 3>;
using Polygon = std::vector<Point>;

struct Plane {
    Point normal;
    double dist;  // inside when normal . p <= dist
};

struct Solid {
    std::vector<Plane> planes;
    Point mins, maxs;
    int order;  // later solids win coplanar ties
};

inline double dot(const Point& a, const Point& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }

// Split a convex polygon by a plane; points within eps of the plane go to both sides.
inline void split(const Polygon& polygon, const Plane& plane, double eps, Polygon& front, Polygon& back) {
    front.clear();
    back.clear();
    const std::size_t n = polygon.size();
    std::vector<double> d(n);
    for (std::size_t i = 0; i < n; ++i) d[i] = dot(plane.normal, polygon[i]) - plane.dist;
    for (std::size_t i = 0; i < n; ++i) {
        const Point& a = polygon[i];
        const Point& b = polygon[(i + 1) % n];
        const double da = d[i], db = d[(i + 1) % n];
        if (da >= -eps) front.push_back(a);
        if (da <= eps) back.push_back(a);
        if ((da > eps && db < -eps) || (da < -eps && db > eps)) {
            const double t = da / (da - db);
            const Point p{a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t};
            front.push_back(p);
            back.push_back(p);
        }
    }
    if (front.size() < 3) front.clear();
    if (back.size() < 3) back.clear();
}

inline double area(const Polygon& polygon) {
    Point sum{0, 0, 0};
    for (std::size_t i = 1; i + 1 < polygon.size(); ++i) {
        const Point& a = polygon[0];
        const Point& b = polygon[i];
        const Point& c = polygon[i + 1];
        const Point u{b[0] - a[0], b[1] - a[1], b[2] - a[2]}, v{c[0] - a[0], c[1] - a[1], c[2] - a[2]};
        sum[0] += u[1] * v[2] - u[2] * v[1];
        sum[1] += u[2] * v[0] - u[0] * v[2];
        sum[2] += u[0] * v[1] - u[1] * v[0];
    }
    return 0.5 * std::sqrt(dot(sum, sum));
}

// Fragments of `face` (on `facePlane`, belonging to solid `owner`) left visible.
inline std::vector<Polygon> visibleFragments(const Polygon& face, const Plane& facePlane, int owner,
                                             const std::vector<Solid>& solids, double eps = 0.01) {
    std::vector<Polygon> fragments{face};
    Point lo{1e300, 1e300, 1e300}, hi{-1e300, -1e300, -1e300};
    for (const Point& p : face)
        for (int k = 0; k < 3; ++k) { lo[k] = std::min(lo[k], p[k]); hi[k] = std::max(hi[k], p[k]); }

    for (const Solid& solid : solids) {
        if (solid.order == owner) continue;
        bool overlaps = true;
        for (int k = 0; k < 3; ++k)
            if (hi[k] < solid.mins[k] - eps || lo[k] > solid.maxs[k] + eps) overlaps = false;
        if (!overlaps) continue;

        // Planes of the solid that coincide with the face decide coplanar cases.
        bool skip = false, coplanar = false;
        std::vector<const Plane*> cutting;
        for (const Plane& plane : solid.planes) {
            if (dot(plane.normal, plane.normal) < 0.5)
                continue;  // unset plane: every point would lie on it
            const double alignment = dot(plane.normal, facePlane.normal);
            if (alignment > 1 - 1e-6 && std::abs(plane.dist - facePlane.dist) <= eps) {
                // Shared surface facing the same way: the later solid keeps its face.
                if (solid.order < owner) skip = true;
                coplanar = true;
                continue;
            }
            if (alignment < -1 + 1e-6 && std::abs(plane.dist + facePlane.dist) <= eps)
                continue;  // back to back: the face is on the solid's boundary, facing into it
            cutting.push_back(&plane);
        }
        if (skip) continue;

        std::vector<Polygon> next;
        Polygon front, back;
        for (const Polygon& fragment : fragments) {
            // Only split fragments the solid really covers; otherwise splitting by
            // its planes would fragment faces that nothing hides.
            Polygon hidden = fragment;
            for (const Plane* plane : cutting) {
                split(hidden, *plane, eps, front, back);
                hidden = back;
                if (hidden.empty()) break;
            }
            if (hidden.empty() || area(hidden) <= 1e-3) {
                next.push_back(fragment);
                continue;
            }
            // Partly buried faces render correctly (depth hides the buried part),
            // so only coplanar overlaps, which z-fight, are trimmed. Otherwise a
            // face is dropped only when it is hidden entirely.
            if (!coplanar) {
                if (area(hidden) < area(fragment) - 1e-2)
                    next.push_back(fragment);
                continue;
            }
            Polygon inside = fragment;
            for (const Plane* plane : cutting) {
                split(inside, *plane, eps, front, back);
                if (!front.empty() && area(front) > 1e-3) next.push_back(front);
                inside = back;
                if (inside.empty()) break;
            }
            // Whatever remains in `inside` is hidden by the solid.
        }
        fragments.swap(next);
        if (fragments.empty()) break;
    }
    return fragments;
}

}  // namespace Respawn::Csg
