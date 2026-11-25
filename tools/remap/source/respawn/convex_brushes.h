// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include "convex_cells.h"

namespace Respawn {
// Check an exact convex union through the two named outward interface planes.
// Unlike visibility clustering, collision may not fill a concavity or ignore a
// second nearby plane. Plane and vertex tolerances only absorb double arithmetic.
inline bool canMergeBrushHulls(const ConvexCellHull& a, std::size_t sa,
                               const ConvexCellHull& b, std::size_t sb) {
    if (sa >= a.planes.size() || sb >= b.planes.size() || a.points.empty() || b.points.empty()) return false;
    const auto& pa = a.planes[sa]; const auto& pb = b.planes[sb];
    for (int axis = 0; axis < 3; ++axis)
        if (std::abs(pa.normal[axis] + pb.normal[axis]) > 1e-10) return false;
    if (std::abs(pa.distance + pb.distance) > 1e-8) return false;
    const auto contains = [](const ConvexCellHull& hull, std::size_t shared, const ConvexCellHull& other) {
        for (std::size_t i = 0; i < hull.planes.size(); ++i) {
            if (i == shared) continue;
            const auto& plane = hull.planes[i];
            for (const auto& point : other.points) {
                double distance = -plane.distance;
                for (int axis = 0; axis < 3; ++axis) distance += plane.normal[axis]*point[axis];
                if (distance > 1e-7) return false;
            }
        }
        return true;
    };
    return contains(a,sa,b) && contains(b,sb,a);
}
} // namespace Respawn
