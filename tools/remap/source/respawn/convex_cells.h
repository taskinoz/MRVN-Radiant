// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include <array>
#include <cmath>
#include <vector>
#include <utility>
#include <numeric>
#include <unordered_set>

namespace Respawn {
// R1/R2 renderer cell masks reserve two of 1024 bits for sentinels.
inline constexpr std::size_t MaxVisibilityCells = 1022;
// A protected interface must survive even when its endpoints can be joined
// through another path. Keep original leaf IDs in the exclusions and resolve
// their current owners when considering either convex or budget merges.
class CellMergeGroups {
    std::vector<std::size_t> parents;
    std::vector<std::unordered_set<std::size_t>> exclusions;
public:
    explicit CellMergeGroups(std::size_t count) : parents(count), exclusions(count) {
        std::iota(parents.begin(), parents.end(), std::size_t{0});
    }
    std::size_t root(std::size_t id) {
        while (parents[id] != id) { parents[id] = parents[parents[id]]; id = parents[id]; }
        return id;
    }
    void protect(std::size_t a, std::size_t b) {
        exclusions[root(a)].insert(b);
        exclusions[root(b)].insert(a);
    }
    bool canJoin(std::size_t a, std::size_t b) {
        a = root(a); b = root(b);
        if (a == b) return false;
        for (const auto other : exclusions[a])
            if (root(other) == b) return false;
        return true;
    }
    bool join(std::size_t a, std::size_t b) {
        a = root(a); b = root(b);
        if (!canJoin(a, b)) return false;
        parents[b] = a;
        exclusions[a].insert(exclusions[b].begin(), exclusions[b].end());
        exclusions[b].clear();
        return true;
    }
};

using CellPoint = std::array<double, 3>;
struct CellPlane { CellPoint normal; double distance; };
struct ConvexCellHull { std::vector<CellPlane> planes; std::vector<CellPoint> points; };

inline bool sameCellPlane(const CellPlane& a, const CellPlane& b) {
    for (int axis = 0; axis < 3; ++axis)
        if (std::abs(a.normal[axis] - b.normal[axis]) > 1e-6) return false;
    return std::abs(a.distance - b.distance) < 0.001;
}
inline CellPlane reverseCellPlane(CellPlane p) {
    for (double& n : p.normal) n = -n;
    p.distance = -p.distance;
    return p;
}

// The two convex regions share a portal in `separator`, outward from a.
// Their union stays convex only if each region is behind every other boundary
// of the other region. Removing only this separator then describes that exact
// union. AABB overlap or connectivity alone would also merge L-shaped rooms.
inline bool canMergeCells(const ConvexCellHull& a, const ConvexCellHull& b,
                          const CellPlane& separator) {
    const auto contains = [](const ConvexCellHull& hull, const ConvexCellHull& other,
                             const CellPlane& shared) {
        bool found = false;
        for (const auto& plane : hull.planes) {
            if (sameCellPlane(plane, shared)) { found = true; continue; }
            for (const auto& point : other.points) {
                double distance = -plane.distance;
                for (int axis = 0; axis < 3; ++axis) distance += plane.normal[axis] * point[axis];
                if (distance > 0.001) return false;
            }
        }
        return found;
    };
    return !a.points.empty() && !b.points.empty() &&
           contains(a, b, separator) && contains(b, a, reverseCellPlane(separator));
}

inline void mergeCells(ConvexCellHull& a, const ConvexCellHull& b, const CellPlane& separator) {
    std::vector<CellPlane> planes;
    const auto append = [&](const ConvexCellHull& hull, const CellPlane& shared) {
        for (const auto& plane : hull.planes) {
            if (sameCellPlane(plane, shared)) continue;
            bool duplicate = false;
            for (const auto& previous : planes)
                if (sameCellPlane(previous, plane)) { duplicate = true; break; }
            if (!duplicate) planes.push_back(plane);
        }
    };
    append(a, separator); append(b, reverseCellPlane(separator));
    a.planes = std::move(planes);
    a.points.insert(a.points.end(), b.points.begin(), b.points.end());
}
} // namespace Respawn
