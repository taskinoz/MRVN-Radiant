// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once

#include <array>
#include <cmath>
#include <cstdint>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>

namespace Respawn {

// Triangle-collision bevel selection for R1/R2 TRICOLL. For each source
// triangle, select every other triangle of the entity that shares a vertex
// with it and whose plane supports it: every source vertex lies within 1/32
// unit in front of that plane and at least one lies more than 1/32 behind it.
// Sources whose physical front normal, cross(v2 - v0, v1 - v0), has Z below
// -0.5 select nothing. A target whose plane duplicates one already in the
// source's list (normals within 1e-5, distances within 1/32) is skipped: it
// clips nothing more. Retail TF2 lists never repeat a plane; on Coliseum
// geometry this drops 40% of the references (85,709 to 51,064).
//
// This is not retail's exact selector. Every sampled retail reference satisfies
// the support conditions, and in TF1 (Angel City) every one also shares a
// vertex, so for TF1 this is a superset. TF2 retail also references nearby
// triangles without a shared vertex, which this rule never selects: on retail
// Coliseum geometry it reproduces 31.9% of retail's references and adds others.
// In native TFO and TF2 sweeps over closed concave solids and open terrain, these
// lists moved hull contacts toward the matching native convex brushes and never
// past them; without bevels, triangle hulls catch early on ridges. Purely
// concave neighbours (valleys, pits) are never selected, because a source that
// rises in front of a neighbour's plane fails the support test.
using BevelTriangle = std::array<std::array<double, 3>, 3>;

inline std::vector<std::vector<std::uint32_t>> selectTricollBevels(const std::vector<BevelTriangle>& triangles) {
    constexpr double slab = 1.0 / 32.0;
    if (triangles.size() > 0xffffffffull) throw std::runtime_error("Too many triangles for bevel selection");
    const auto sub = [](const std::array<double, 3>& a, const std::array<double, 3>& b) {
        return std::array<double, 3>{a[0] - b[0], a[1] - b[1], a[2] - b[2]};
    };
    struct Plane { std::array<double, 3> n; double d; bool valid; };
    std::vector<Plane> planes;
    planes.reserve(triangles.size());
    std::map<std::array<double, 3>, std::vector<std::uint32_t>> byVertex;
    for (std::size_t i = 0; i < triangles.size(); ++i) {
        const auto& t = triangles[i];
        for (const auto& p : t)
            for (const double v : p)
                if (!std::isfinite(v)) throw std::runtime_error("Nonfinite triangle in bevel selection");
        const auto u = sub(t[2], t[0]), v = sub(t[1], t[0]);
        std::array<double, 3> n{u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]};
        const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
        const bool valid = length > 1e-9;
        if (valid) for (double& c : n) c /= length;
        planes.push_back({n, valid ? n[0] * t[0][0] + n[1] * t[0][1] + n[2] * t[0][2] : 0.0, valid});
        for (const auto& p : t) {
            auto& owners = byVertex[p];
            if (owners.empty() || owners.back() != i) owners.push_back(static_cast<std::uint32_t>(i));
        }
    }
    std::vector<std::vector<std::uint32_t>> references(triangles.size());
    for (std::size_t i = 0; i < triangles.size(); ++i) {
        if (!planes[i].valid || planes[i].n[2] < -0.5) continue;
        std::set<std::uint32_t> neighbours;
        for (const auto& p : triangles[i])
            for (const auto j : byVertex[p])
                if (j != i) neighbours.insert(j);
        for (const auto j : neighbours) {
            const Plane& plane = planes[j];
            if (!plane.valid) continue;
            double highest = -1e300, lowest = 1e300;
            for (const auto& p : triangles[i]) {
                const double distance = plane.n[0] * p[0] + plane.n[1] * p[1] + plane.n[2] * p[2] - plane.d;
                highest = std::max(highest, distance);
                lowest = std::min(lowest, distance);
            }
            if (!(highest <= slab && lowest < -slab)) continue;
            bool duplicate = false;
            for (const auto k : references[i]) {
                const Plane& kept = planes[k];
                if (kept.n[0] * plane.n[0] + kept.n[1] * plane.n[1] + kept.n[2] * plane.n[2] >= 1.0 - 1e-5 &&
                    std::fabs(kept.d - plane.d) <= slab) { duplicate = true; break; }
            }
            if (!duplicate) references[i].push_back(j);
        }
    }
    return references;
}

} // namespace Respawn
