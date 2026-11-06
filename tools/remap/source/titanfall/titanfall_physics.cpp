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
#include "../respawn/encoding.h"
#include "../respawn/box_coverage.h"
#include "../respawn/vmt_surfaceprop.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <map>
#include <string>
#include <tuple>
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
    std::vector<uint8_t> materials;                  // materialtable index per triangle
    P3 mins{1e30, 1e30, 1e30}, maxs{-1e30, -1e30, -1e30};
};

struct Writer {
    std::vector<uint8_t> bytes;
    std::size_t Reserve(std::size_t n) { const std::size_t at = bytes.size(); bytes.resize(at + n, 0); return at; }
    template <typename T> void Put(std::size_t at, T value) { std::memcpy(bytes.data() + at, &value, sizeof(T)); }
};

/* Surface properties. Triangle material indices name entries of the keydata's
   materialtable, which retail fills from each face material's $surfaceprop. */
std::vector<std::string> materialTable;
std::map<std::string, std::string> vmtSurfaceProps;

std::string SurfaceProp(const shaderInfo_t *shader) {
    if (!shader) return "default";
    if (!shader->surfaceProp.empty()) return shader->surfaceProp;
    std::string name;
    try { name = Respawn::textureName(shader->shader.c_str()); } catch (const std::exception &) { return "default"; }
    const auto cached = vmtSurfaceProps.find(name);
    if (cached != vmtSurfaceProps.end()) return cached->second;
    std::string path = "materials/" + name + ".vmt", prop = "default";
    std::replace(path.begin(), path.end(), '\\', '/');
    Respawn::VmtProperty resolved;
    bool loadedAny = false;
    const auto load = [&loadedAny](const std::string &filename, std::string &text) {
        if (const MemBuffer file = vfsLoadFile(filename.c_str())) {
            text.assign(file.data(), file.size());
            loadedAny = true;
            return true;
        }
        return false;
    };
    if (Respawn::resolveVmtSurfaceProp(path, load, resolved)) {
        if (resolved.present && !resolved.value.empty()) prop = resolved.value;
    } else if (loadedAny) {
        Sys_FPrintf(SYS_WRN, "VPhysics: unable to resolve VMT %s; using default surface property\n", path.c_str());
    }
    return vmtSurfaceProps[name] = prop;
}

uint8_t MaterialIndex(const shaderInfo_t *shader) {
    const std::string prop = SurfaceProp(shader);
    for (std::size_t i = 0; i < materialTable.size(); ++i)
        if (materialTable[i] == prop) return uint8_t(i + 1);
    if (materialTable.size() >= 127)
        Error("VPhysics cannot encode more than 127 distinct surface properties (7-bit material field); cannot add '%s'", prop.c_str());
    materialTable.push_back(prop);
    return uint8_t(materialTable.size());
}

// Closes a ledge from convex polygons (rings of IVP points, each with a
// material). Triangles are fanned and turned to face away from the centroid,
// or left in their given winding when the caller already made it outward.
// Returns false when the polygons do not close into a watertight hull.
bool FinishLedge(Ledge &ledge, const std::vector<std::pair<std::vector<P3>, uint8_t>> &polygons) {
    constexpr double weld = 0.01 * kMetresPerUnit;
    auto pointIndex = [&](P3 p) -> uint16_t {
        for (std::size_t i = 0; i < ledge.points.size(); ++i)
            if (Length(ledge.points[i] - p) < weld) return uint16_t(i);
        ledge.points.push_back(p);
        return uint16_t(ledge.points.size() - 1);
    };
    std::vector<std::pair<std::vector<uint16_t>, uint8_t>> rings;
    for (const auto &[polygon, material] : polygons) {
        std::vector<uint16_t> ring;
        for (const P3 &v : polygon) {
            const uint16_t index = pointIndex(v);
            if (ring.empty() || ring.back() != index) ring.push_back(index);
        }
        while (ring.size() > 1 && ring.front() == ring.back()) ring.pop_back();
        if (ring.size() >= 3) rings.push_back({ring, material});
    }
    if (ledge.points.size() < 4 || ledge.points.size() > 65535) return false;
    P3 centroid{0, 0, 0};
    for (const P3 &p : ledge.points) centroid = centroid + p;
    centroid = centroid * (1.0 / ledge.points.size());
    for (const auto &[ring, material] : rings) {
        for (std::size_t i = 1; i + 1 < ring.size(); ++i) {
            std::array<uint16_t, 3> tri = {ring[0], ring[i], ring[i + 1]};
            const P3 a = ledge.points[tri[0]], b = ledge.points[tri[1]], c = ledge.points[tri[2]];
            const P3 normal = Cross(b - a, c - a);
            if (Length(normal) < 1e-12) continue;
            if (Dot(normal, (a + b + c) * (1.0 / 3) - centroid) < 0) std::swap(tri[1], tri[2]);
            ledge.triangles.push_back(tri);
            ledge.materials.push_back(material);
        }
    }
    if (ledge.triangles.size() < 4 || ledge.triangles.size() > 4095) return false;
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

// One convex ledge per brush, from its side windings.
bool BuildLedge(const brush_t &brush, Ledge &ledge) {
    std::vector<std::pair<std::vector<P3>, uint8_t>> polygons;
    for (const side_t &side : brush.sides) {
        if (side.bevel || side.winding.size() < 3) continue;
        std::vector<P3> ring;
        for (const Vector3 &v : side.winding) ring.push_back(ToIvp(v));
        polygons.push_back({ring, MaterialIndex(side.shaderInfo)});
    }
    return FinishLedge(ledge, polygons);
}

// Each patch triangle becomes a convex prism `kPatchThickness` units deep into
// the solid behind the surface, so the visible surface itself collides. A thin
// slab is tunnelled through by falling physics objects; the whole patch uses one
// offset direction, so neighbouring prisms share their edge points (no seam
// gaps) and every prism stays convex, which IVP requires.
constexpr double kPatchThickness = 32.0;
bool BuildPrism(const std::array<P3, 3> &top, const std::array<P3, 3> &bottom, uint8_t material, Ledge &ledge) {
    std::vector<std::pair<std::vector<P3>, uint8_t>> polygons = {
        {{top[0], top[1], top[2]}, material}, {{bottom[0], bottom[2], bottom[1]}, material}};
    for (int k = 0; k < 3; ++k) {
        const int next = (k + 1) % 3;
        polygons.push_back({{top[next], top[k], bottom[k], bottom[next]}, material});
    }
    return FinishLedge(ledge, polygons);
}

bool BuildPatchPrisms(const mesh_t &mesh, uint8_t material, std::vector<Ledge> &out) {
    const int width = mesh.width, height = mesh.height;
    if (width < 2 || height < 2) return false;
    Vector3 normal(0, 0, 0);
    for (int y = 0; y + 1 < height; ++y) for (int x = 0; x + 1 < width; ++x) {
        const int a = x + y * width, b = a + width, c = b + 1, d = a + 1;
        normal = normal + vector3_cross(mesh.verts[b].xyz - mesh.verts[a].xyz,
                                        mesh.verts[d].xyz - mesh.verts[a].xyz);
    }
    const double length = vector3_length(normal);
    if (length < 1e-6) return false;
    // Respawn triangles face the opposite direction to cross(b-a, c-a).
    // Extrude into the solid behind that front face, rather than into the
    // playable space in front of it. FinishLedge gives IVP outward windings.
    const Vector3 offset = normal * float(-kPatchThickness / length);
    const int count = width * height;
    std::vector<P3> top(count), bottom(count);
    for (int i = 0; i < count; ++i) {
        top[i] = ToIvp(mesh.verts[i].xyz);
        bottom[i] = ToIvp(mesh.verts[i].xyz - offset);
    }
    for (int y = 0; y + 1 < height; ++y) for (int x = 0; x + 1 < width; ++x) {
        const int a = x + y * width, b = a + width, c = b + 1, d = a + 1;
        for (const auto &tri : {std::array<int, 3>{a, b, c}, std::array<int, 3>{a, c, d}}) {
            Ledge ledge;
            if (BuildPrism({top[tri[0]], top[tri[1]], top[tri[2]]},
                           {bottom[tri[0]], bottom[tri[1]], bottom[tri[2]]}, material, ledge))
                out.push_back(std::move(ledge));
        }
    }
    return !out.empty();
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
        w.Put<uint32_t>(tri, uint32_t(t & 0xFFF) | uint32_t(pierce & 0xFFF) << 12 | uint32_t(ledge.materials[t] & 0x7F) << 24);
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

void AppendModel(std::vector<uint8_t> &lump, int modelIndex, const std::vector<std::vector<uint8_t>> &solids, const std::string &keydata) {
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

namespace {
// The world model is written last, once every model's materials are in the table.
std::vector<std::vector<uint8_t>> worldSolids;
std::string worldKeydata;
bool worldPending = false;
std::size_t worldTricollHeaders = 0;
std::vector<uint8_t> otherModels;

// Retail gives a world TRICOLL header a keydata vtric entry exactly when its
// contents carry a player, NPC or Titan clip bit and none of SOLID, WINDOW or
// GRATE; the entry repeats the header's collision contents. This held for every
// header of Angel City, Colony, Lagoon and Fracture (2,590 vtric of 15,524).
bool NeedsVtric(int contents) {
    constexpr int clip = CONTENTS_PLAYERCLIP | CONTENTS_MONSTERCLIP | CONTENTS_TITANCLIP;
    constexpr int solid = CONTENTS_SOLID | CONTENTS_WINDOW | CONTENTS_GRATE;
    return (contents & clip) && !(contents & solid);
}

void SplitStaticSolids(int contents, const std::vector<Ledge> &ledges) {
    for (std::size_t first = 0; first < ledges.size();) {
        std::size_t bytes = 0, last = first;
        while (last < ledges.size() && (last == first || bytes < kMaxSurfaceBytes))
            bytes += 44 + 16 * (ledges[last].triangles.size() + ledges[last].points.size()), ++last;
        const std::vector<Ledge> part(ledges.begin() + first, ledges.begin() + last);
        worldKeydata += "staticsolid {\n\"index\" \"" + std::to_string(worldSolids.size()) +
                        "\"\n\"contents\" \"" + std::to_string(contents) + "\"\n}\n";
        worldSolids.push_back(WriteSolid(part, P3{0, 0, 0}));
        first = last;
    }
}

P3 Centre(const std::vector<Ledge> &ledges) {
    P3 mins{1e30, 1e30, 1e30}, maxs{-1e30, -1e30, -1e30};
    for (const Ledge &ledge : ledges) {
        mins = {std::min(mins.x, ledge.mins.x), std::min(mins.y, ledge.mins.y), std::min(mins.z, ledge.mins.z)};
        maxs = {std::max(maxs.x, ledge.maxs.x), std::max(maxs.y, ledge.maxs.y), std::max(maxs.z, ledge.maxs.z)};
    }
    return (mins + maxs) * 0.5;
}

// Water: brushes sharing a surface height, contents and surface material form one fluid solid and one leaf
// water record (surface Z, minimum Z, surface texture), as in retail.
struct Water {
    std::vector<Ledge> ledges;
    std::vector<Respawn::CoverageSolid> brushVolumes;
    int contents = 0;
    MinMax bounds;
    const shaderInfo_t *surface = nullptr;
};
} // namespace

/*
    EmitPhysicsModel()
    Writes the VPhysics model of the entity's brushes and patches.
    Call after its collision (EmitBrush fills brush contents). The world becomes
    static solids grouped by contents plus fluid solids for water; brush entities
    get one movable solid.
*/
void Titanfall::EmitPhysicsModel(const entity_t &e, int modelIndex) {
    const bool world = modelIndex == 0;
    std::map<int, std::vector<Ledge>> byContents;
    std::map<std::tuple<float, int, std::string>, Water> waters;
    std::size_t skipped = 0;
    for (const brush_t &brush : e.brushes) {
        const int contents = brush.contentFlags;
        if (!contents) continue;
        bool sky = false;
        for (const side_t &side : brush.sides)
            if (!side.bevel && side.shaderInfo && (side.shaderInfo->compileFlags & C_SKY)) sky = true;
        if (sky) continue;
        Ledge ledge;
        if (!BuildLedge(brush, ledge)) { ++skipped; continue; }
        if (contents & (CONTENTS_WATER | CONTENTS_SLIME)) {
            if (!world) continue;
            const shaderInfo_t *surface = nullptr;
            for (const side_t &side : brush.sides)
                if (!side.bevel && side.shaderInfo && side.plane.normal().z() > 0.7f && !surface)
                    surface = side.shaderInfo;
            const float surfaceZ = brush.minmax.maxs.z();
            if (!std::isfinite(surfaceZ)) Error("Nonfinite water surface height");
            Water &water = waters[{surfaceZ, contents, surface ? surface->shader.c_str() : ""}];
            water.ledges.push_back(std::move(ledge));
            water.contents = contents;
            water.bounds.extend(brush.minmax);
            Respawn::CoverageSolid volume;
            for (int axis = 0; axis < 3; ++axis) {
                volume.bounds.mins[axis] = brush.minmax.mins[axis];
                volume.bounds.maxs[axis] = brush.minmax.maxs[axis];
            }
            for (const side_t& side : brush.sides) {
                if (side.bevel) continue;
                const Plane3 plane = side.plane.normal() != g_vector3_identity ? side.plane : Plane3(mapplanes[side.planenum].plane);
                const auto& normal = plane.normal();
                // Brush bounds already impose the axial faces. Keep the
                // authored non-axial cuts for exact sloped-volume coverage.
                if ((normal[0] == 0 && normal[1] == 0) || (normal[0] == 0 && normal[2] == 0) ||
                    (normal[1] == 0 && normal[2] == 0)) continue;
                volume.planes.push_back({{normal[0],normal[1],normal[2]},plane.dist()});
            }
            water.brushVolumes.push_back(std::move(volume));
            water.surface = surface;
            continue;
        }
        byContents[world ? contents : 0].push_back(std::move(ledge));
    }
    // World patches collide in VPhysics through their TRICOLL headers: the engine
    // turns every header into a virtual mesh (with an empty PHYSICS_TRIANGLES it
    // builds the hulls itself), as retail does. Prisms would duplicate those
    // meshes (one TFO run left props resting up to 17 units high), so they are kept only
    // for movable brush entities and for a world without any brush solid,
    // because the world physics object is built from static solid 0.
    if (world) worldTricollHeaders = Titanfall::Bsp::tricollHeaders.size();
    const bool patchPrismsNeeded = !world || byContents.empty();
    if (world && patchPrismsNeeded && e.patches)
        Sys_Warning("VPhysics: the world has no brush solid; patches use prisms instead of virtual meshes\n");
    std::size_t patchPrisms = 0;
    for (const parseMesh_t *patch = patchPrismsNeeded ? e.patches : nullptr; patch; patch = patch->next) {
        const shaderInfo_t &shader = *patch->shaderInfo;
        if (!shader.contentFlags || (shader.compileFlags & C_SKY)) continue;
        std::vector<Ledge> ledges;
        if (BuildPatchPrisms(patch->mesh, MaterialIndex(&shader), ledges)) {
            for (Ledge &ledge : ledges) byContents[world ? shader.contentFlags : 0].push_back(std::move(ledge));
            patchPrisms += ledges.size();
        }
    }
    if (skipped) Sys_FPrintf(SYS_VRB, "   VPhysics: skipped %zu brushes without closed windings\n", skipped);

    if (world) {
        for (const auto &[contents, ledges] : byContents) SplitStaticSolids(contents, ledges);
        for (auto &[key, water] : waters) {
            const float surfaceZ = water.bounds.maxs.z();
            std::string prop = SurfaceProp(water.surface);
            if (prop == "default") prop = "water";
            char text[512];
            snprintf(text, sizeof(text),
                     "fluid {\n\"index\" \"%zu\"\n\"surfaceprop\" \"%s\"\n\"damping\" \"0.010000\"\n\"contents\" \"%d\"\n"
                     "\"surfaceplane\" \"0.000000 0.000000 1.000000 %f \"\n\"currentvelocity\" \"0.000000 0.000000 0.000000 \"\n}\n",
                     worldSolids.size(), prop.c_str(), water.contents, surfaceZ);
            worldKeydata += text;
            worldSolids.push_back(WriteSolid(water.ledges, Centre(water.ledges)));
            Titanfall::LeafWaterData_t data{};
            if (Titanfall::Bsp::leafWaterData.size() > 32767)
                Error("Water record index exceeds its signed 16-bit cell field");
            data.surfaceZ = surfaceZ;
            data.minZ = water.bounds.mins.z();
            data.textureData = water.surface ? int32_t(Titanfall::EmitTextureData(*water.surface)) : 0;
            Titanfall::Bsp::leafWaterData.push_back(data);
            Titanfall::Bsp::leafWaterVolumes.push_back(std::move(water.brushVolumes));
        }
        worldPending = !worldSolids.empty();
        if (patchPrisms || !waters.empty())
            Sys_Printf("%9zu patch prisms and %zu water volumes in VPhysics\n", patchPrisms, waters.size());
        return;
    }
    if (byContents.empty()) return;
    const std::vector<Ledge> &ledges = byContents.begin()->second;
    double volume = 0;
    std::map<uint8_t, std::size_t> uses;
    for (const Ledge &ledge : ledges) {
        for (const auto &tri : ledge.triangles)  // signed tetrahedra volume
            volume += Dot(ledge.points[tri[0]], Cross(ledge.points[tri[1]], ledge.points[tri[2]])) / 6.0;
        for (uint8_t m : ledge.materials) ++uses[m];
    }
    volume /= kMetresPerUnit * kMetresPerUnit * kMetresPerUnit;  // cubic inches, as retail
    uint8_t common = uses.empty() ? 1 : uses.begin()->first;
    for (const auto &[m, n] : uses) if (n > uses[common]) common = m;
    const std::string prop = common >= 1 && common <= materialTable.size() ? materialTable[common - 1] : "default";
    char text[512];
    snprintf(text, sizeof(text), "solid {\n\"index\" \"0\"\n\"mass\" \"50000.000000\"\n\"surfaceprop\" \"%s\"\n\"volume\" \"%f\"\n}\n",
             prop.c_str(), volume);
    AppendModel(otherModels, modelIndex, {WriteSolid(ledges, Centre(ledges))}, text);
}

/*
    FinishPhysics()
    Writes the world model, with the material table of every model, then the
    brush entities and the model -1 terminator.
*/
void Titanfall::FinishPhysics() {
    std::vector<uint8_t> &lump = Titanfall::Bsp::physicsCollide;
    lump.clear();
    if (!worldPending && otherModels.empty()) return;
    if (worldPending) {
        std::string keydata = worldKeydata + "virtualterrain {}\nvirtualtrimeshes {}\n";
        const auto &contents = Titanfall::Bsp::tricollHeaderContents;
        std::size_t vtric = 0;
        for (std::size_t i = 0; i < worldTricollHeaders && i < contents.size(); ++i)
            if (NeedsVtric(contents[i])) {
                keydata += "vtric {\n\"index\" \"" + std::to_string(i) + "\"\n\"contents\" \"" +
                           std::to_string(contents[i]) + "\"\n}\n";
                ++vtric;
            }
        if (vtric) Sys_Printf("%9zu clip triangle meshes in VPhysics\n", vtric);
        // The TFO server makes physics objects for virtual meshes 0..8191 only.
        if (worldTricollHeaders > 8192)
            Sys_Warning("VPhysics: %zu world triangle collision headers; physics objects ignore those after 8192\n",
                        worldTricollHeaders);
        keydata += "materialtable {\n";
        if (materialTable.empty()) materialTable.push_back("default");
        for (std::size_t i = 0; i < materialTable.size(); ++i)
            keydata += "\"" + materialTable[i] + "\" \"" + std::to_string(i + 1) + "\"\n";
        AppendModel(lump, 0, worldSolids, keydata + "}\n");
    }
    lump.insert(lump.end(), otherModels.begin(), otherModels.end());
    const int32_t end[4] = {-1, -1, 0, 0};
    const auto *e = reinterpret_cast<const uint8_t *>(end);
    lump.insert(lump.end(), e, e + sizeof(end));
    Sys_Printf("%9zu bytes of VPhysics collision, %zu surface properties\n", lump.size(), materialTable.size());
}

/*
    AssignWaterCells()
    Cells mostly inside a water volume reference its leaf water record. Call
    after the cells are built.
*/
void Titanfall::AssignWaterCells() {
    auto &cells = Titanfall::Bsp::cells_stub;
    const auto &nodes = Titanfall::Bsp::cellAABBNodes;
    const auto &bounds = Titanfall::Bsp::cellBounds;  // access roots also cover referenced meshes
    std::size_t assigned = 0;
    for (std::size_t i = 0; i < cells.size() && i < nodes.size(); ++i) {
        const Vector3 mins = i < bounds.size() ? bounds[i].mins : nodes[i].mins;
        const Vector3 maxs = i < bounds.size() ? bounds[i].maxs : nodes[i].maxs;
        double volume = 1;
        for (int a = 0; a < 3; ++a) volume *= std::max(0.0, double(maxs[a]) - mins[a]);
        if (!(volume > 0) || !std::isfinite(volume)) continue;
        Respawn::CoverageBox cell;
        for (int axis = 0; axis < 3; ++axis) {
            cell.mins[axis] = mins[axis];
            cell.maxs[axis] = maxs[axis];
        }
        for (std::size_t w = 0; w < Titanfall::Bsp::leafWaterVolumes.size(); ++w) {
            if (Respawn::coversConvexFraction(cell, Titanfall::Bsp::leafWaterVolumes[w], 0.5)) { cells[i].leafWaterData = int16_t(w); ++assigned; break; }
        }
    }
    if (!Titanfall::Bsp::leafWaterData.empty())
        Sys_Printf("%9zu leaf water records, %zu water cells\n", Titanfall::Bsp::leafWaterData.size(), assigned);
}
