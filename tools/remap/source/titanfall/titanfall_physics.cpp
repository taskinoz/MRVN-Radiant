/* -------------------------------------------------------------------------------

   Copyright (C) 2022-2026 MRVN-Radiant and contributors.
   For a list of contributors, see the accompanying CONTRIBUTORS file.

   This file is part of MRVN-Radiant.

   MRVN-Radiant is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   MRVN-Radiant is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with GtkRadiant; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

   ------------------------------------------------------------------------------- */

/*
    Titanfall 1 PHYSICS_COLLIDE: VPhysics (IVP) compact surfaces built from brushes.
    See docs/respawn/RESPAWN_TF1_LUMPS.md for the layouts, read from retail Angel City.

    Per model: { int modelIndex, dataSize, keydataSize, solidCount }, then solidCount
    { int size; VPHY header; compact surface }, then the keydata text. The lump ends
    with { -1, -1, 0, 0 }.
*/

#include "../remap.h"
#include "../bspfile_abstract.h"
#include "titanfall.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace {
constexpr double kMetresPerUnit = 1.0 / 39.3701;
constexpr std::size_t kMaxSurfaceBytes = 4u << 20;  // retail world solids are about 1 MB

struct P3 { double x, y, z; };
P3 operator-(P3 a, P3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
P3 operator+(P3 a, P3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
P3 operator*(P3 a, double s) { return {a.x * s, a.y * s, a.z * s}; }
double Dot(P3 a, P3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
P3 Cross(P3 a, P3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
double Length(P3 a) { return std::sqrt(Dot(a, a)); }

// Source (x, y, z) inches to IVP (x, -z, y) metres: a proper rotation, so
// outward faces stay outward.
P3 ToIvp(const Vector3 &v) { return P3{v.x(), -v.z(), v.y()} * kMetresPerUnit; }

struct Ledge {
    std::vector<P3> points;
    std::vector<std::array<uint16_t, 3>> triangles;  // CCW seen from outside
    P3 mins{1e30, 1e30, 1e30}, maxs{-1e30, -1e30, -1e30};
};

struct Writer {
    std::vector<uint8_t> bytes;
    std::size_t Reserve(std::size_t n) { const std::size_t at = bytes.size(); bytes.resize(at + n, 0); return at; }
    template <typename T> void Put(std::size_t at, T value) { std::memcpy(bytes.data() + at, &value, sizeof(T)); }
};

// One convex ledge per brush, from its side windings. Returns false when the
// windings do not close into a watertight hull.
bool BuildLedge(const brush_t &brush, Ledge &ledge) {
    constexpr double weld = 0.01 * kMetresPerUnit;
    auto pointIndex = [&](P3 p) -> uint16_t {
        for (std::size_t i = 0; i < ledge.points.size(); ++i)
            if (Length(ledge.points[i] - p) < weld) return uint16_t(i);
        ledge.points.push_back(p);
        return uint16_t(ledge.points.size() - 1);
    };
    for (const side_t &side : brush.sides) {
        if (side.bevel || side.winding.size() < 3) continue;
        std::vector<uint16_t> ring;
        for (const Vector3 &v : side.winding) {
            const uint16_t index = pointIndex(ToIvp(v));
            if (ring.empty() || ring.back() != index) ring.push_back(index);
        }
        while (ring.size() > 1 && ring.front() == ring.back()) ring.pop_back();
        if (ring.size() < 3) continue;
        const Vector3 n = side.plane.normal();
        const P3 outward = ToIvp(n) * (1.0 / kMetresPerUnit);
        for (std::size_t i = 1; i + 1 < ring.size(); ++i) {
            std::array<uint16_t, 3> tri = {ring[0], ring[i], ring[i + 1]};
            const P3 a = ledge.points[tri[0]], b = ledge.points[tri[1]], c = ledge.points[tri[2]];
            const P3 normal = Cross(b - a, c - a);
            if (Length(normal) < 1e-12) continue;
            if (Dot(normal, outward) < 0) std::swap(tri[1], tri[2]);
            ledge.triangles.push_back(tri);
        }
    }
    if (ledge.triangles.size() < 4 || ledge.triangles.size() > 4095 || ledge.points.size() < 4) return false;
    // Every directed edge needs its reverse.
    std::map<std::pair<uint16_t, uint16_t>, int> edges;
    for (const auto &tri : ledge.triangles)
        for (int k = 0; k < 3; ++k)
            if (++edges[{tri[k], tri[(k + 1) % 3]}] > 1) return false;
    for (const auto &[edge, count] : edges)
        if (!edges.count({edge.second, edge.first})) return false;
    for (const P3 &p : ledge.points) {
        ledge.mins = {std::min(ledge.mins.x, p.x), std::min(ledge.mins.y, p.y), std::min(ledge.mins.z, p.z)};
        ledge.maxs = {std::max(ledge.maxs.x, p.x), std::max(ledge.maxs.y, p.y), std::max(ledge.maxs.z, p.z)};
    }
    return true;
}

// IVP_Compact_Ledge: 16-byte header, 16-byte triangles, then 16-byte points.
std::size_t WriteLedge(Writer &w, const Ledge &ledge) {
    const std::size_t nt = ledge.triangles.size();
    const std::size_t size = 16 + 16 * nt + 16 * ledge.points.size();
    const std::size_t at = w.Reserve(size);
    w.Put<int32_t>(at + 0, int32_t(16 + 16 * nt));                // c_point_offset
    w.Put<int32_t>(at + 4, 0);                                    // client_data
    w.Put<uint32_t>(at + 8, (1u << 2) | uint32_t(size / 16) << 8);  // is_compact, size_div_16
    w.Put<int16_t>(at + 12, int16_t(nt));

    std::vector<P3> normals;
    for (const auto &tri : ledge.triangles) {
        const P3 a = ledge.points[tri[0]], b = ledge.points[tri[1]], c = ledge.points[tri[2]];
        const P3 n = Cross(b - a, c - a);
        normals.push_back(n * (1.0 / Length(n)));
    }
    std::map<std::pair<uint16_t, uint16_t>, std::size_t> edgeAt;  // directed edge -> byte offset in ledge
    for (std::size_t t = 0; t < nt; ++t)
        for (int k = 0; k < 3; ++k)
            edgeAt[{ledge.triangles[t][k], ledge.triangles[t][(k + 1) % 3]}] = 16 + 16 * t + 4 + 4 * k;
    for (std::size_t t = 0; t < nt; ++t) {
        std::size_t pierce = t;
        double most = 2;
        for (std::size_t o = 0; o < nt; ++o) {
            const double d = Dot(normals[t], normals[o]);
            if (o != t && d < most) { most = d; pierce = o; }
        }
        const std::size_t tri = at + 16 + 16 * t;
        // tri_index:12, pierce_index:12, material_index:7, is_virtual:1
        w.Put<uint32_t>(tri, uint32_t(t & 0xFFF) | uint32_t(pierce & 0xFFF) << 12 | 1u << 24);
        for (int k = 0; k < 3; ++k) {
            const uint16_t a = ledge.triangles[t][k], b = ledge.triangles[t][(k + 1) % 3];
            const std::ptrdiff_t self = std::ptrdiff_t(16 + 16 * t + 4 + 4 * k);
            const std::ptrdiff_t opposite = (std::ptrdiff_t(edgeAt.at({b, a})) - self) / 4;
            // start_point_index:16, opposite_index:15 (signed, in edges), is_virtual:1
            w.Put<uint32_t>(tri + 4 + 4 * k, uint32_t(a) | (uint32_t(opposite) & 0x7FFF) << 16);
        }
    }
    for (std::size_t i = 0; i < ledge.points.size(); ++i) {
        const std::size_t p = at + 16 + 16 * nt + 16 * i;
        w.Put<float>(p + 0, float(ledge.points[i].x));
        w.Put<float>(p + 4, float(ledge.points[i].y));
        w.Put<float>(p + 8, float(ledge.points[i].z));
    }
    return at;
}

// IVP_Compact_Ledgetree_Node, 28 bytes. The left child follows its parent;
// spheres are the subtree's box centre and half diagonal, and box_sizes are
// each half extent as a fraction of the radius, in 250ths (rounded up).
void WriteTree(Writer &w, std::size_t surface, const std::vector<Ledge> &ledges,
               const std::vector<std::size_t> &ledgeAt, std::vector<std::size_t> &items) {
    P3 mins{1e30, 1e30, 1e30}, maxs{-1e30, -1e30, -1e30};
    for (std::size_t i : items) {
        mins = {std::min(mins.x, ledges[i].mins.x), std::min(mins.y, ledges[i].mins.y), std::min(mins.z, ledges[i].mins.z)};
        maxs = {std::max(maxs.x, ledges[i].maxs.x), std::max(maxs.y, ledges[i].maxs.y), std::max(maxs.z, ledges[i].maxs.z)};
    }
    const P3 centre = (mins + maxs) * 0.5, half = (maxs - mins) * 0.5;
    const double radius = std::max(Length(half), 1e-6);
    const std::size_t node = w.Reserve(28);
    w.Put<float>(node + 8, float(centre.x));
    w.Put<float>(node + 12, float(centre.y));
    w.Put<float>(node + 16, float(centre.z));
    w.Put<float>(node + 20, float(radius * 1.0001));
    const double extents[3] = {half.x, half.y, half.z};
    for (int a = 0; a < 3; ++a)
        w.bytes[node + 24 + a] = uint8_t(std::clamp(std::ceil(250.0 * extents[a] / radius), 1.0, 255.0));
    if (items.size() == 1) {
        w.Put<int32_t>(node + 4, int32_t(std::ptrdiff_t(surface + ledgeAt[items[0]]) - std::ptrdiff_t(node)));
        return;
    }
    const int axis = half.x >= half.y && half.x >= half.z ? 0 : (half.y >= half.z ? 1 : 2);
    auto key = [&](std::size_t i) {
        const P3 c = (ledges[i].mins + ledges[i].maxs) * 0.5;
        return axis == 0 ? c.x : (axis == 1 ? c.y : c.z);
    };
    std::sort(items.begin(), items.end(), [&](std::size_t a, std::size_t b) { return key(a) < key(b); });
    std::vector<std::size_t> left(items.begin(), items.begin() + items.size() / 2);
    std::vector<std::size_t> right(items.begin() + items.size() / 2, items.end());
    WriteTree(w, surface, ledges, ledgeAt, left);
    w.Put<int32_t>(node + 0, int32_t(w.bytes.size() - node));
    WriteTree(w, surface, ledges, ledgeAt, right);
}

// One solid: VPHY header and IVP_Compact_Surface.
std::vector<uint8_t> WriteSolid(const std::vector<Ledge> &ledges, P3 massCentre) {
    Writer w;
    const std::size_t header = w.Reserve(28);
    const std::size_t surface = w.Reserve(48);
    std::vector<std::size_t> ledgeAt;
    for (const Ledge &ledge : ledges) ledgeAt.push_back(WriteLedge(w, ledge) - surface);
    const std::size_t root = w.bytes.size();
    std::vector<std::size_t> items(ledges.size());
    for (std::size_t i = 0; i < items.size(); ++i) items[i] = i;
    WriteTree(w, surface, ledges, ledgeAt, items);

    double radius = 0;
    for (const Ledge &ledge : ledges)
        for (const P3 &p : ledge.points) radius = std::max(radius, Length(p - massCentre));
    const std::size_t surfaceSize = w.bytes.size() - surface;
    std::memcpy(w.bytes.data() + header, "VPHY", 4);
    w.Put<int16_t>(header + 4, 0x100);
    w.Put<int16_t>(header + 6, 0);
    w.Put<int32_t>(header + 8, int32_t(surfaceSize));
    w.Put<float>(header + 12, 1.0f);
    w.Put<float>(header + 16, 1.0f);
    w.Put<float>(header + 20, 1.0f);
    w.Put<float>(surface + 0, float(massCentre.x));
    w.Put<float>(surface + 4, float(massCentre.y));
    w.Put<float>(surface + 8, float(massCentre.z));
    for (int a = 0; a < 3; ++a) w.Put<float>(surface + 12 + 4 * a, float(radius * radius / 2));
    w.Put<float>(surface + 24, float(radius));
    w.Put<uint32_t>(surface + 28, 0xE3u | uint32_t(surfaceSize) << 8);  // max_deviation as retail, byte_size
    w.Put<int32_t>(surface + 32, int32_t(root - surface));
    w.Put<int32_t>(surface + 44, 0x53505649);  // "IVPS"
    return w.bytes;
}

void AppendModel(int modelIndex, const std::vector<std::vector<uint8_t>> &solids, const std::string &keydata) {
    std::vector<uint8_t> &lump = Titanfall::Bsp::physicsCollide;
    std::size_t dataSize = 0;
    for (const auto &solid : solids) dataSize += 4 + solid.size();
    const int32_t header[4] = {modelIndex, int32_t(dataSize), int32_t(keydata.size() + 1), int32_t(solids.size())};
    const auto *h = reinterpret_cast<const uint8_t *>(header);
    lump.insert(lump.end(), h, h + sizeof(header));
    for (const auto &solid : solids) {
        const int32_t size = int32_t(solid.size());
        const auto *s = reinterpret_cast<const uint8_t *>(&size);
        lump.insert(lump.end(), s, s + 4);
        lump.insert(lump.end(), solid.begin(), solid.end());
    }
    lump.insert(lump.end(), keydata.begin(), keydata.end());
    lump.push_back(0);
}
} // namespace

/*
    EmitPhysicsModel()
    Writes the VPhysics model of the entity's brushes. Call after its collision
    (EmitBrush fills brush contents). The world becomes static solids grouped by
    contents; brush entities get one movable solid.
*/
void Titanfall::EmitPhysicsModel(const entity_t &e, int modelIndex) {
    const bool world = modelIndex == 0;
    std::map<int, std::vector<Ledge>> byContents;
    std::size_t skipped = 0;
    for (const brush_t &brush : e.brushes) {
        const int contents = brush.contentFlags;
        if (!contents || (contents & (CONTENTS_WATER | CONTENTS_SLIME))) continue;
        bool sky = false;
        for (const side_t &side : brush.sides)
            if (!side.bevel && side.shaderInfo && (side.shaderInfo->compileFlags & C_SKY)) sky = true;
        if (sky) continue;
        Ledge ledge;
        if (BuildLedge(brush, ledge)) byContents[world ? contents : 0].push_back(std::move(ledge));
        else ++skipped;
    }
    if (byContents.empty()) return;

    std::vector<std::vector<uint8_t>> solids;
    std::string keydata;
    if (world) {
        for (auto &[contents, ledges] : byContents) {
            for (std::size_t first = 0; first < ledges.size();) {
                std::size_t bytes = 0, last = first;
                while (last < ledges.size() && (last == first || bytes < kMaxSurfaceBytes))
                    bytes += 44 + 16 * (ledges[last].triangles.size() + ledges[last].points.size()), ++last;
                const std::vector<Ledge> part(ledges.begin() + first, ledges.begin() + last);
                keydata += "staticsolid {\n\"index\" \"" + std::to_string(solids.size()) +
                           "\"\n\"contents\" \"" + std::to_string(contents) + "\"\n}\n";
                solids.push_back(WriteSolid(part, P3{0, 0, 0}));
                first = last;
            }
        }
        keydata += "virtualterrain {}\nvirtualtrimeshes {}\nmaterialtable {\n\"default\" \"1\"\n}\n";
    } else {
        const std::vector<Ledge> &ledges = byContents.begin()->second;
        P3 mins{1e30, 1e30, 1e30}, maxs{-1e30, -1e30, -1e30};
        double volume = 0;
        for (const Ledge &ledge : ledges) {
            mins = {std::min(mins.x, ledge.mins.x), std::min(mins.y, ledge.mins.y), std::min(mins.z, ledge.mins.z)};
            maxs = {std::max(maxs.x, ledge.maxs.x), std::max(maxs.y, ledge.maxs.y), std::max(maxs.z, ledge.maxs.z)};
            for (const auto &tri : ledge.triangles)  // signed tetrahedra volume, in cubic inches
                volume += Dot(ledge.points[tri[0]], Cross(ledge.points[tri[1]], ledge.points[tri[2]])) / 6.0;
        }
        volume /= kMetresPerUnit * kMetresPerUnit * kMetresPerUnit;
        solids.push_back(WriteSolid(ledges, (mins + maxs) * 0.5));
        char text[256];
        snprintf(text, sizeof(text), "solid {\n\"index\" \"0\"\n\"mass\" \"50000.000000\"\n\"surfaceprop\" \"default\"\n\"volume\" \"%f\"\n}\n", volume);
        keydata = text;
    }
    AppendModel(modelIndex, solids, keydata);
    if (skipped) Sys_FPrintf(SYS_VRB, "   VPhysics: skipped %zu brushes without closed windings\n", skipped);
}

/*
    FinishPhysics()
    Ends the lump with the model -1 terminator.
*/
void Titanfall::FinishPhysics() {
    if (Titanfall::Bsp::physicsCollide.empty()) return;
    const int32_t end[4] = {-1, -1, 0, 0};
    const auto *e = reinterpret_cast<const uint8_t *>(end);
    Titanfall::Bsp::physicsCollide.insert(Titanfall::Bsp::physicsCollide.end(), e, e + sizeof(end));
    Sys_Printf("%9zu bytes of VPhysics collision\n", Titanfall::Bsp::physicsCollide.size());
}
