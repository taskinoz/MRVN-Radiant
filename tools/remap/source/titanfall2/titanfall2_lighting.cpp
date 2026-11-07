/* -------------------------------------------------------------------------------

   Copyright (C) 2026 MRVN-Radiant and contributors.
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
    Titanfall 2 lighting: world lights, lightmap atlas pages, SKY/RTL planes and
    RTL pages. Record values follow retail Coliseum/Glitch light entities and
    their compiled world lights; see docs/respawn/RESPAWN_LIGHTING.md.
*/

#include "../remap.h"
#include "../bspfile_abstract.h"
#include <chrono>
#include <functional>
#include <cstdio>
#include <limits>
#include <map>

namespace {
using Respawn::Bake::V3;
using Respawn::Bake::Light;
using Respawn::Bake::LightType;

// Retail world-light flags (Coliseum/Glitch): realtime with baked shadow masks,
// realtime without shadows ("shadow" "0"), realtime with dynamic shadows
// ("realtime_shadows" "2"), static ("realtime" "0") and suns. Only 28 and 24
// appear in retail RTL pages.
constexpr int32_t FlagRealtime = 28;
constexpr int32_t FlagRealtimeNoShadow = 56;
constexpr int32_t FlagRealtimeDynamicShadow = 104;
constexpr int32_t FlagStatic = 4;
constexpr int32_t FlagSun = 24;
// Lights with "_pbr_falloff" "1" store intensity x100000 (Coliseum spotlights).
constexpr double PbrIntensityScale = 100000.0;

constexpr double Pi = 3.14159265358979323846;

bool HasKey(const entity_t &e, const char *key) {
    const char *value = e.valueForKey(key);
    return value && value[0];
}

double DoubleForKey(const entity_t &e, const char *key, double fallback) {
    return HasKey(e, key) ? atof(e.valueForKey(key)) : fallback;
}

/*
    Colour keys use Source-style "_light"/"_ambient" "R G B brightness":
    intensity = (channel / 255) ^ 2.2 * brightness / 255. Quake-style "light"
    brightness with an optional "_color" is accepted as a fallback.
*/
bool ColourForKey(const entity_t &e, const char *key, V3 &intensity) {
    if (!HasKey(e, key))
        return false;
    float c[4] = {255, 255, 255, 200};
    const int n = sscanf(e.valueForKey(key), "%f %f %f %f", &c[0], &c[1], &c[2], &c[3]);
    if (n < 1)
        return false;
    if (n < 3)  // a single value is a brightness
        c[3] = c[0], c[0] = c[1] = c[2] = 255;
    auto channel = [&](float v) { return std::pow(std::max(0.0f, v) / 255.0, 2.2) * c[3] / 255.0; };
    intensity = {channel(c[0]), channel(c[1]), channel(c[2])};
    return true;
}

V3 QuakeColour(const entity_t &e, double brightness) {
    V3 colour{1, 1, 1};
    if (HasKey(e, "_color")) {
        float c[3] = {1, 1, 1};
        if (sscanf(e.valueForKey("_color"), "%f %f %f", &c[0], &c[1], &c[2]) == 3) {
            const float scale = std::max({c[0], c[1], c[2]}) > 1.0f ? 1.0f / 255.0f : 1.0f;
            colour = {std::pow(c[0] * scale, 2.2), std::pow(c[1] * scale, 2.2), std::pow(c[2] * scale, 2.2)};
        }
    }
    // Quake brightness (~200) is far below retail realtime lights, whose
    // "_light" brightness reaches thousands (Glitch: 5100 -> intensity 20).
    // In-game E1M1 (199 dense lights) was fully overexposed at 10x; tune with
    // worldspawn "_lightscale" instead.
    constexpr double QuakeScale = 1.0;
    return colour * (brightness / 255.0 * QuakeScale);
}

/*
    Direction the light travels. "pitch" overrides angles[0] with the opposite
    sign, matching retail: pitch -22.49, yaw -143.64 -> (-0.744, -0.548, -0.382).
*/
V3 DirectionForEntity(const entity_t &e, double defaultPitch) {
    double pitch = defaultPitch, yaw = 0;
    Vector3 angles;
    if (e.read_keyvalue(angles, "angles")) {
        pitch = -angles[0];
        yaw = angles[1];
    } else if (HasKey(e, "angle")) {
        yaw = DoubleForKey(e, "angle", 0);
    }
    if (HasKey(e, "pitch"))
        pitch = DoubleForKey(e, "pitch", pitch);
    const double p = pitch * Pi / 180, y = yaw * Pi / 180;
    return Respawn::Bake::normalize({std::cos(p) * std::cos(y), std::cos(p) * std::sin(y), std::sin(p)});
}

V3 OriginForEntity(const entity_t &e) {
    const Vector3 origin = e.vectorForKey("origin");
    return {origin.x(), origin.y(), origin.z()};
}

Titanfall2::WorldLight_t BaseRecord(const Light &light, int32_t type) {
    Titanfall2::WorldLight_t record{};
    // Vector3's default constructor leaves its components uninitialized even
    // inside an otherwise zero-initialized record. These fields are unused by
    // ambient/point lights and must not contain allocator data.
    record.normal = Vector3(0);
    record.shadowOffset = Vector3(0);
    record.origin = Vector3(light.origin.x, light.origin.y, light.origin.z);
    record.intensity = Vector3(light.intensity.x, light.intensity.y, light.intensity.z);
    record.type = type;
    return record;
}

void SetFalloff(const entity_t &e, Light &light, Titanfall2::WorldLight_t &record, double quakeBrightness) {
    double zero = DoubleForKey(e, "_zero_percent_distance", DoubleForKey(e, "_distance", 0));
    double fifty = DoubleForKey(e, "_fifty_percent_distance", 0);
    if (!(zero > 0)) {
        zero = quakeBrightness > 0 ? quakeBrightness : 300;
        if (!(fifty > 0)) fifty = zero * 0.5;
    }
    if (!(fifty > 0) || fifty >= zero)
        fifty = zero * 0.3;  // retail authoring commonly uses 30%
    light.zeroDistance = zero;
    light.attenuation = Respawn::Bake::fitAttenuation(zero, fifty);
    record.radius = zero;
    record.constantAttn = light.attenuation.constant;
    record.linearAttn = light.attenuation.linear;
    record.quadraticAttn = light.attenuation.quadratic;
}

struct PendingLight {
    Titanfall2::WorldLight_t  record;
    Light                     light;
    int                       environment = 0;  // lightEnvironmentIndex of suns and ambients
};

std::vector<PendingLight> pendingLights;
std::vector<int> bakeLightEnvironments;  // parallel to Titanfall2::Bsp::bakeLights
std::map<int, V3> environmentAmbients;
int environments = 0;

// "*N" -> N; environments without the key are numbered in order.
int EnvironmentIndex(const entity_t &e, int fallback) {
    const char *value = e.valueForKey("lightEnvironmentIndex");
    if (value && value[0] == '*')
        return atoi(value + 1);
    return fallback;
}

// Convex light_environment_volume brushes: "*trigger_brush_B_plane_P" "nx ny nz d",
// relative to the entity origin, inside when n.p <= d.
struct EnvironmentVolume {
    int environment;
    std::vector<std::vector<std::array<double, 4>>> brushes;

    bool contains(V3 p) const {
        for (const auto &brush : brushes) {
            bool inside = !brush.empty();
            for (const auto &plane : brush)
                if (plane[0] * p.x + plane[1] * p.y + plane[2] * p.z > plane[3] + 1e-3) { inside = false; break; }
            if (inside)
                return true;
        }
        return false;
    }
};

EnvironmentVolume ParseVolume(const entity_t &e) {
    EnvironmentVolume volume{EnvironmentIndex(e, 1), {}};
    const V3 origin = OriginForEntity(e);
    for (int b = 0;; b++) {
        std::vector<std::array<double, 4>> brush;
        for (int p = 0;; p++) {
            char key[64];
            snprintf(key, sizeof(key), "*trigger_brush_%d_plane_%d", b, p);
            if (!HasKey(e, key))
                break;
            double n[4] = {0, 0, 0, 0};
            sscanf(e.valueForKey(key), "%lf %lf %lf %lf", &n[0], &n[1], &n[2], &n[3]);
            brush.push_back({n[0], n[1], n[2], n[3] + n[0] * origin.x + n[1] * origin.y + n[2] * origin.z});
        }
        if (brush.empty())
            break;
        volume.brushes.push_back(brush);
    }
    return volume;
}
}  // namespace


/*
    EmitLightprobeBsp()
    The probe lookup BSP (0x06, 0x07) over LIGHTPROBE_REFERENCES. Each node is a
    plane and two children: back (n.p - d < 0) first, front second, as retail
    traversal of every reference to its own leaf shows. A leaf word is
    0x80000000 | count << 25 | index: count 0 means one reference `index`,
    otherwise `count` (2-12) reference ids from 0x07 starting at `index`. Retail
    splits along world planes; this uses axis-aligned median splits.
*/
static void EmitLightprobeBsp() {
    auto &nodes = Titanfall2::Bsp::lightprobeBspNodes;
    auto &ids = Titanfall2::Bsp::lightprobeBspRefIds;
    const auto &refs = Titanfall2::Bsp::lightprobeReferences;
    nodes.clear();
    ids.clear();
    if (refs.empty()) return;
    constexpr std::size_t LeafSize = 8;
    std::vector<uint32_t> order(refs.size());
    for (uint32_t i = 0; i < order.size(); ++i) order[i] = i;
    auto position = [&](uint32_t r, int axis) { return axis == 0 ? refs[r].x : (axis == 1 ? refs[r].y : refs[r].z); };
    std::function<uint32_t(std::size_t, std::size_t, int)> build = [&](std::size_t first, std::size_t count, int depth) -> uint32_t {
        if (count <= LeafSize || depth > 40) {
            if (count == 1) return 0x80000000u | order[first];
            const uint32_t start = static_cast<uint32_t>(ids.size());
            const std::size_t kept = std::min<std::size_t>(count, 12);
            ids.insert(ids.end(), order.begin() + first, order.begin() + first + kept);
            if (start > 0xFFFFFF) Error("Light probe BSP reference ids exceed 24 bits");
            return 0x80000000u | uint32_t(kept) << 25 | start;
        }
        double lo[3] = {1e300, 1e300, 1e300}, hi[3] = {-1e300, -1e300, -1e300};
        for (std::size_t i = first; i < first + count; ++i)
            for (int a = 0; a < 3; ++a) { lo[a] = std::min(lo[a], double(position(order[i], a))); hi[a] = std::max(hi[a], double(position(order[i], a))); }
        const int axis = (hi[0] - lo[0] >= hi[1] - lo[1] && hi[0] - lo[0] >= hi[2] - lo[2]) ? 0 : (hi[1] - lo[1] >= hi[2] - lo[2] ? 1 : 2);
        const std::size_t middle = first + count / 2;
        std::nth_element(order.begin() + first, order.begin() + middle, order.begin() + first + count,
                         [&](uint32_t a, uint32_t b) { return position(a, axis) < position(b, axis); });
        float split = position(order[middle], axis);
        // Points equal to the split go front, so the back half must lie strictly below it.
        std::size_t back = first;
        for (std::size_t i = first; i < first + count; ++i)
            if (position(order[i], axis) < split) std::swap(order[i], order[back++]);
        if (back == first || back == first + count) {
            if (count <= 12) return build(first, count, 41);
            back = middle;  // coincident positions: split the list anyway
        }
        const uint32_t index = static_cast<uint32_t>(nodes.size());
        Titanfall2::LightprobeBspNode_t &node = nodes.emplace_back();
        node.normal[axis] = 1.0f;
        node.distance = split;
        const uint32_t backChild = build(first, back - first, depth + 1);
        const uint32_t frontChild = build(back, first + count - back, depth + 1);
        nodes[index].children[0] = backChild;
        nodes[index].children[1] = frontChild;
        return index;
    };
    const uint32_t root = build(0, order.size(), 0);
    if (root & 0x80000000u) {
        // A single leaf still needs a root node; both sides share it.
        Titanfall2::LightprobeBspNode_t &node = nodes.emplace_back();
        node.normal[2] = 1.0f;
        node.children[0] = node.children[1] = root;
    }
}


/*
    EmitCsmTree()
    Cascaded shadow map object tree for one sun: static props (world geometry
    casts through the shadow meshes) in an AABB tree built in light space, where
    z is against the sun, x is horizontal and y = z x x, as fitted from retail
    Colony, Glitch, Homestead and Live Fire Stacks. Nodes use the cell AABB
    layout; references are object ids, as in OBJ_REFERENCES.
*/
static void EmitCsmNode(const Shared::visNode_t &node, std::size_t index) {
    std::size_t total = 0;
    std::function<void(const Shared::visNode_t &)> count = [&](const Shared::visNode_t &n) {
        total += n.refs.size();
        for (const auto &c : n.children) count(c);
    };
    count(node);
    Titanfall::CellAABBNode_t &out = Titanfall2::Bsp::csmAABBNodes.at(index);
    out = {};
    out.mins = node.minmax.mins;
    out.maxs = node.minmax.maxs;
    out.childCount = static_cast<uint8_t>(node.children.size());
    out.totalRefCount = static_cast<uint16_t>(std::min<std::size_t>(total, 65535));
    if (!node.refs.empty()) {
        out.objRef = static_cast<uint16_t>(Titanfall2::Bsp::csmObjReferences.size());
        out.objRefCount = static_cast<uint8_t>(node.refs.size());
        for (const Shared::visRef_t &ref : node.refs) Titanfall2::Bsp::csmObjReferences.push_back(ref.index);
    }
    if (node.children.empty()) return;
    const std::size_t first = Titanfall2::Bsp::csmAABBNodes.size();
    Titanfall2::Bsp::csmAABBNodes.resize(first + node.children.size());
    Titanfall2::Bsp::csmAABBNodes.at(index).firstChild = static_cast<uint16_t>(first);
    for (std::size_t i = 0; i < node.children.size(); ++i)
        EmitCsmNode(node.children[i], first + i);
}

static bool EmitCsmTree(const Vector3 &sun) {
    if (Titanfall::Bsp::levelInfo.empty()) return false;
    // TF2 reserves 64-entry blocks of object ids for world meshes; TF1 numbers
    // static props straight after them.
    const uint32_t propBase = g_game->bspVersion == 29 ? Titanfall::Bsp::models.at(0).meshCount
                            : (Titanfall::Bsp::levelInfo.at(0).firstSkyMeshIndex + 63u) & ~63u;
    const Vector3 z = vector3_normalised(-sun);
    Vector3 x(sun.y(), -sun.x(), 0);
    x = vector3_length(x) < 1e-4f ? Vector3(1, 0, 0) : vector3_normalised(x);
    const Vector3 y = vector3_cross(z, x);
    std::vector<Shared::visRef_t> refs;
    for (const Shared::visRef_t &ref : Shared::visRefs) {
        if (ref.index < propBase) continue;
        Shared::visRef_t &light = refs.emplace_back();
        light.index = ref.index;
        for (int corner = 0; corner < 8; ++corner) {
            const Vector3 p((corner & 1) ? ref.minmax.maxs.x() : ref.minmax.mins.x(),
                            (corner & 2) ? ref.minmax.maxs.y() : ref.minmax.mins.y(),
                            (corner & 4) ? ref.minmax.maxs.z() : ref.minmax.mins.z());
            light.minmax.extend(Vector3(vector3_dot(p, x), vector3_dot(p, y), vector3_dot(p, z)));
        }
    }
    if (refs.empty()) return false;
    const Shared::visNode_t root = Shared::MakeVisTree(refs, 1e30f);
    const std::size_t index = Titanfall2::Bsp::csmAABBNodes.size();
    Titanfall2::Bsp::csmAABBNodes.emplace_back();
    EmitCsmNode(root, index);
    if (Titanfall2::Bsp::csmAABBNodes.size() > 65535 || Titanfall2::Bsp::csmObjReferences.size() > 65535)
        Error("Cascaded shadow tree exceeds 16-bit node or reference indices");
    return true;
}


/*
    EmitShadowEnvironments()
    One shadow environment per light environment. Environment 0 owns opaque and
    alpha-tested world shadow meshes for its sun's cascaded shadows, plus a
    light-space tree of static props; other environments (the menu stage) own
    none, so their dynamic shadows stay out of gameplay.
*/
static void EmitShadowEnvironments() {
    std::map<int, Vector3> suns;  // environment -> sun direction
    for (std::size_t i = 0; i < Titanfall2::Bsp::worldLights.size(); i++)
        if (Titanfall2::Bsp::worldLights[i].type == 3)
            suns.emplace(bakeLightEnvironments[i], Titanfall2::Bsp::worldLights[i].normal);
    if (suns.empty())
        return;

    // Shadow meshes from the world model's opaque meshes (before decals,
    // translucent and sky), position-only with mesh-local 16-bit indices.
    const Titanfall::Model_t &world = Titanfall::Bsp::models.at(0);
    const uint32_t opaqueEnd = Titanfall::Bsp::levelInfo.empty() ? world.meshCount
                             : std::min(world.meshCount, Titanfall::Bsp::levelInfo[0].firstDecalMeshIndex);
    std::map<std::array<float, 3>, uint16_t> lookup;
    Titanfall2::ShadowMesh_t *current = nullptr;
    auto flush = [&]() { current = nullptr; lookup.clear(); };
    for (uint32_t m = world.firstMesh; m < world.firstMesh + opaqueEnd; m++) {
        const Titanfall::Mesh_t &mesh = Titanfall::Bsp::meshes.at(m);
        if (mesh.flags & (S_SKY | S_TRANSLUCENT))
            continue;
        const int32_t base = Titanfall::Bsp::materialSorts.at(mesh.materialOffset).vertexOffset;
        for (uint32_t t = 0; t < mesh.triCount; t++) {
            if (!current || lookup.size() + 3 > 65535) {
                flush();
                Titanfall2::Bsp::shadowMeshes.push_back({static_cast<uint32_t>(Titanfall2::Bsp::shadowMeshVertices.size()), 0, 1, -1});
                current = &Titanfall2::Bsp::shadowMeshes.back();
            }
            for (int k = 0; k < 3; k++) {
                const std::size_t v = base + Titanfall::Bsp::meshIndices.at(mesh.triOffset + t * 3 + k);
                uint32_t position;
                switch (mesh.flags & 0x600) {
                    case S_VERTEX_LIT_BUMP: position = Titanfall::Bsp::vertexLitBumpVertices.at(v).vertexIndex; break;
                    case S_VERTEX_UNLIT:    position = Titanfall::Bsp::vertexUnlitVertices.at(v).vertexIndex; break;
                    case S_VERTEX_UNLIT_TS: position = Titanfall::Bsp::vertexUnlitTSVertices.at(v).vertexIndex; break;
                    default:                position = Titanfall::Bsp::vertexLitFlatVertices.at(v).vertexIndex; break;
                }
                const Vector3 &p = Titanfall::Bsp::vertices.at(position);
                const std::array<float, 3> key{p.x(), p.y(), p.z()};
                auto found = lookup.find(key);
                if (found == lookup.end()) {
                    found = lookup.emplace(key, static_cast<uint16_t>(Titanfall2::Bsp::shadowMeshVertices.size() - current->vertexOffset)).first;
                    Titanfall2::Bsp::shadowMeshVertices.push_back(p);
                }
                Titanfall2::Bsp::shadowMeshIndices.push_back(found->second);
            }
            current->triangleCount++;
        }
    }

    // Alpha-tested casters ("surfaceparm alphashadow"): position and texture UV in
    // SHADOW_MESH_ALPHA_VERTICES (0x7D), one shadow mesh per material sort so the
    // engine can test the sort's texture alpha. Their indices follow the opaque ones.
    std::map<uint16_t, std::vector<uint32_t>> alphaMeshes;  // material sort -> meshes
    for (uint32_t m = world.firstMesh; m < world.firstMesh + world.meshCount; m++) {
        const Titanfall::Mesh_t &mesh = Titanfall::Bsp::meshes.at(m);
        if (mesh.flags & S_SKY)
            continue;
        const int16_t texture = Titanfall::Bsp::materialSorts.at(mesh.materialOffset).textureData;
        const uint32_t name = Titanfall::Bsp::textureData.at(texture).name_index;
        const shaderInfo_t *shader = ShaderInfoForShaderNull(&Titanfall::Bsp::textureDataData.at(Titanfall::Bsp::textureDataTable.at(name)));
        if (shader && (shader->compileFlags & C_ALPHASHADOW))
            alphaMeshes[mesh.materialOffset].push_back(m);
    }
    for (const auto &[sort, meshes] : alphaMeshes) {
        Titanfall2::ShadowMesh_t *alpha = nullptr;
        std::map<std::array<float, 5>, uint16_t> alphaLookup;
        for (uint32_t m : meshes) {
            const Titanfall::Mesh_t &mesh = Titanfall::Bsp::meshes.at(m);
            const int32_t base = Titanfall::Bsp::materialSorts.at(mesh.materialOffset).vertexOffset;
            for (uint32_t t = 0; t < mesh.triCount; t++) {
                if (!alpha || alphaLookup.size() + 3 > 65535) {
                    alphaLookup.clear();
                    Titanfall2::Bsp::shadowMeshes.push_back({static_cast<uint32_t>(Titanfall2::Bsp::shadowMeshAlphaVertices.size()), 0, 0,
                                                             static_cast<int16_t>(sort)});
                    alpha = &Titanfall2::Bsp::shadowMeshes.back();
                }
                for (int k = 0; k < 3; k++) {
                    const std::size_t v = base + Titanfall::Bsp::meshIndices.at(mesh.triOffset + t * 3 + k);
                    uint32_t position;
                    Vector2 uv;
                    switch (mesh.flags & 0x600) {
                        case S_VERTEX_LIT_BUMP: position = Titanfall::Bsp::vertexLitBumpVertices.at(v).vertexIndex; uv = Titanfall::Bsp::vertexLitBumpVertices.at(v).textureUV; break;
                        case S_VERTEX_UNLIT:    position = Titanfall::Bsp::vertexUnlitVertices.at(v).vertexIndex; uv = Titanfall::Bsp::vertexUnlitVertices.at(v).textureUV; break;
                        case S_VERTEX_UNLIT_TS: position = Titanfall::Bsp::vertexUnlitTSVertices.at(v).vertexIndex; uv = Titanfall::Bsp::vertexUnlitTSVertices.at(v).textureUV; break;
                        default:                position = Titanfall::Bsp::vertexLitFlatVertices.at(v).vertexIndex; uv = Titanfall::Bsp::vertexLitFlatVertices.at(v).textureUV; break;
                    }
                    const Vector3 &p = Titanfall::Bsp::vertices.at(position);
                    const std::array<float, 5> key{p.x(), p.y(), p.z(), uv.x(), uv.y()};
                    auto found = alphaLookup.find(key);
                    if (found == alphaLookup.end()) {
                        found = alphaLookup.emplace(key, static_cast<uint16_t>(Titanfall2::Bsp::shadowMeshAlphaVertices.size() - alpha->vertexOffset)).first;
                        Titanfall2::Bsp::shadowMeshAlphaVertices.push_back(key);
                    }
                    Titanfall2::Bsp::shadowMeshIndices.push_back(found->second);
                }
                alpha->triangleCount++;
            }
        }
    }

    const float big = std::numeric_limits<float>::max();
    const int32_t meshCount = static_cast<int32_t>(Titanfall2::Bsp::shadowMeshes.size());
    int32_t expected = 0;
    for (const auto &[environment, normal] : suns) {
        if (environment != expected)
            Sys_FPrintf(SYS_WRN, "WARNING: light environment indices should be consecutive from 0 (found %d)\n", environment);
        expected++;
        const int32_t firstNode = static_cast<int32_t>(Titanfall2::Bsp::csmAABBNodes.size());
        const int32_t firstRef = static_cast<int32_t>(Titanfall2::Bsp::csmObjReferences.size());
        const bool gameplay = environment == 0;
        if (!gameplay || !EmitCsmTree(normal)) {
            Titanfall::CellAABBNode_t &root = Titanfall2::Bsp::csmAABBNodes.emplace_back();
            root = {};
            root.mins = Vector3(big, big, big);
            root.maxs = Vector3(-big, -big, -big);
        }
        Titanfall2::Bsp::shadowEnvironments.push_back({firstNode, firstRef, gameplay ? 0 : meshCount,
                                                       static_cast<int32_t>(Titanfall2::Bsp::csmAABBNodes.size()),
                                                       static_cast<int32_t>(Titanfall2::Bsp::csmObjReferences.size()), meshCount, normal});
    }
}


/*
    IsLightEntity()
*/
bool Titanfall2::IsLightEntity(const entity_t &e) {
    // Other light_* classes (Quake torches, fluoros, globes) bake as point lights.
    return e.classname_is("light") || (e.classname_prefixed("light_") && !e.classname_is("light_environment_volume"));
}


/*
    CollectLight()
    Converts a light entity into world-light records for EmitLighting
*/
void Titanfall2::CollectLight(const entity_t &e) {
    try {
        if (e.classname_is("light_environment")) {
            const V3 origin = OriginForEntity(e);
            const int environment = EnvironmentIndex(e, environments++);
            const bool gameplay = environment == 0;
            PendingLight ambient;
            ambient.environment = environment;
            ambient.light.type = LightType::Ambient;
            ambient.light.origin = origin;
            if (ColourForKey(e, "_ambient", ambient.light.intensity)) {
                ambient.record = BaseRecord(ambient.light, 5);
                pendingLights.push_back(ambient);
                environmentAmbients[environment] = ambient.light.intensity;
                if (gameplay)
                    Titanfall2::Bsp::ambient = ambient.light.intensity;
            }

            PendingLight sun;
            sun.environment = environment;
            sun.light.type = LightType::Sun;
            sun.light.origin = origin;
            sun.light.direction = DirectionForEntity(e, -90);
            if (!ColourForKey(e, "_light", sun.light.intensity))
                sun.light.intensity = {1, 1, 1};
            // Surfaces bake against environment 0; other environments (e.g. the
            // menu stage) light only their light_environment_volume's probes.
            sun.light.realtime = gameplay;
            sun.record = BaseRecord(sun.light, 3);
            sun.record.normal = Vector3(sun.light.direction.x, sun.light.direction.y, sun.light.direction.z);
            sun.record.flags = FlagSun;
            pendingLights.push_back(sun);
            return;
        }

        const bool spot = e.classname_is("light_spot");
        PendingLight pending;
        Light &light = pending.light;
        light.type = spot ? LightType::Spot : LightType::Point;
        light.origin = OriginForEntity(e);
        light.realtime = !HasKey(e, "realtime") || e.intForKey("realtime") != 0;
        double quakeBrightness = 0;
        if (!ColourForKey(e, "_light", light.intensity)) {
            quakeBrightness = DoubleForKey(e, "light", 300);
            light.intensity = QuakeColour(e, quakeBrightness);
        }
        pending.record = BaseRecord(light, spot ? 2 : 1);
        if (HasKey(e, "_pbr_falloff") && e.intForKey("_pbr_falloff") == 1)
            pending.record.intensity = pending.record.intensity * static_cast<float>(PbrIntensityScale);
        SetFalloff(e, light, pending.record, quakeBrightness);
        if (!light.realtime) {
            pending.record.flags = FlagStatic;
        } else if (HasKey(e, "shadow") && e.intForKey("shadow") == 0) {
            pending.record.flags = FlagRealtimeNoShadow;
            light.shadowMask = false;
        } else if (HasKey(e, "realtime_shadows") && e.intForKey("realtime_shadows") == 2) {
            pending.record.flags = FlagRealtimeDynamicShadow;
            light.shadowMask = false;
        } else {
            pending.record.flags = FlagRealtime;
        }

        if (spot) {
            const double outer = std::clamp(DoubleForKey(e, "_cone", 45), 1.0, 89.0);
            const double inner = std::clamp(DoubleForKey(e, "_inner_cone", outer * 0.5), 0.0, outer);
            light.direction = DirectionForEntity(e, -90);
            light.cosOuter = std::cos(outer * Pi / 180);
            light.cosInner = std::cos(inner * Pi / 180);
            pending.record.normal = Vector3(light.direction.x, light.direction.y, light.direction.z);
            pending.record.stopdot = light.cosInner;
            pending.record.stopdot2 = light.cosOuter;
            pending.record.exponent = DoubleForKey(e, "_exponent", 1);
            pending.record.unknown[2] = 1.0f;  // retail spotlights store 1 here
        } else {
            pending.record.normal = Vector3(1, 0, 0);
        }
        pendingLights.push_back(pending);
    } catch (const std::exception &error) {
        Sys_FPrintf(SYS_WRN, "WARNING: Skipping %s at %s: %s\n", e.classname(), e.valueForKey("origin"), error.what());
    }
}


/*
    EmitLighting()
    Bakes lightmaps for every recorded chart and fills the lighting lumps
*/
void Titanfall2::EmitLighting(const entity_t &world) {
    Sys_Printf("--- EmitLighting ---\n");
    const auto started = std::chrono::steady_clock::now();

    // Retail order: ambient, suns, spots, points. Hardware indices skip ambients.
    std::stable_sort(pendingLights.begin(), pendingLights.end(), [](const PendingLight &a, const PendingLight &b) {
        auto rank = [](LightType t) { return t == LightType::Ambient ? 0 : t == LightType::Sun ? 1 : t == LightType::Spot ? 2 : 3; };
        return rank(a.light.type) < rank(b.light.type);
    });
    // Worldspawn "_lightscale" scales every point and spot light.
    const double lightScale = HasKey(world, "_lightscale") ? DoubleForKey(world, "_lightscale", 1) : 1.0;
    if (lightScale != 1.0)
        Sys_Printf("%9.2f light scale\n", lightScale);
    int hardware = 0;
    for (PendingLight &pending : pendingLights) {
        if (pending.light.type == LightType::Point || pending.light.type == LightType::Spot) {
            pending.light.intensity = pending.light.intensity * lightScale;
            pending.record.intensity = Vector3(pending.light.intensity.x, pending.light.intensity.y, pending.light.intensity.z);
        }
        if (pending.light.type != LightType::Ambient)
            pending.light.hardwareIndex = hardware++;
        Titanfall2::Bsp::worldLights.push_back(pending.record);
        Titanfall2::Bsp::bakeLights.push_back(pending.light);
        bakeLightEnvironments.push_back(pending.environment);
    }

    // Opaque, non-sky world brushes cast shadows; sky brushes let sun and sky rays out.
    std::vector<Respawn::Bake::Brush> brushes;
    for (const brush_t &brush : world.brushes) {
        bool visible = false, sky = false, translucent = false;
        for (const side_t &side : brush.sides) {
            if (side.bevel || !side.shaderInfo)
                continue;
            const int flags = side.shaderInfo->compileFlags;
            sky |= (flags & C_SKY) != 0;
            // Alpha-tested surfaces would shadow as solid sheets here; their sun
            // shadows come from the alpha-tested shadow meshes at run time.
            translucent |= (flags & (C_TRANSLUCENT | C_ALPHASHADOW)) != 0;
            visible |= (flags & C_NODRAW) == 0;
        }
        if (!visible || sky || translucent)
            continue;
        Respawn::Bake::Brush &out = brushes.emplace_back();
        // Supplemental collision planes do not define visible brush faces and
        // can have only a float planenum, leaving side.plane at zero. Feeding
        // that zero plane to the segment test makes the brush cast no shadow.
        for (const side_t &side : brush.sides) {
            if (side.bevel) continue;
            out.planes.push_back({side.plane.normal().x(), side.plane.normal().y(), side.plane.normal().z(), side.plane.dist()});
        }
        out.mins = {brush.minmax.mins.x(), brush.minmax.mins.y(), brush.minmax.mins.z()};
        out.maxs = {brush.minmax.maxs.x(), brush.minmax.maxs.y(), brush.minmax.maxs.z()};
    }
    if (world.valueForKey("_remap_mesh")[0]) {
        // A recovered scene's visible detail may have only triangle collision.
        // Thin closed triangle prisms let the existing convex BVH shadow these
        // surfaces without inventing render brushes or moving the recovered mesh.
        const auto &model = Titanfall::Bsp::models.at(0);
        const uint32_t opaqueEnd = Titanfall::Bsp::levelInfo.empty() ? model.meshCount
            : std::min(model.meshCount, Titanfall::Bsp::levelInfo[0].firstDecalMeshIndex);
        for (uint32_t m = model.firstMesh; m < model.firstMesh + opaqueEnd; ++m) {
            const auto &mesh = Titanfall::Bsp::meshes.at(m);
            if (mesh.flags & (S_SKY | S_TRANSLUCENT)) continue;
            {
                const int16_t texture = Titanfall::Bsp::materialSorts.at(mesh.materialOffset).textureData;
                const uint32_t name = Titanfall::Bsp::textureData.at(texture).name_index;
                const shaderInfo_t *shader = ShaderInfoForShaderNull(&Titanfall::Bsp::textureDataData.at(Titanfall::Bsp::textureDataTable.at(name)));
                if (shader && (shader->compileFlags & (C_ALPHASHADOW | C_TRANSLUCENT))) continue;
            }
            const auto base = Titanfall::Bsp::materialSorts.at(mesh.materialOffset).vertexOffset;
            for (uint32_t t = 0; t < mesh.triCount; ++t) {
                V3 points[3];
                for (int k = 0; k < 3; ++k) {
                    const auto v = base + Titanfall::Bsp::meshIndices.at(mesh.triOffset + t*3 + k);
                    uint32_t p;
                    switch (mesh.flags & 0x600) {
                        case S_VERTEX_LIT_BUMP: p = Titanfall::Bsp::vertexLitBumpVertices.at(v).vertexIndex; break;
                        case S_VERTEX_UNLIT: p = Titanfall::Bsp::vertexUnlitVertices.at(v).vertexIndex; break;
                        case S_VERTEX_UNLIT_TS: p = Titanfall::Bsp::vertexUnlitTSVertices.at(v).vertexIndex; break;
                        default: p = Titanfall::Bsp::vertexLitFlatVertices.at(v).vertexIndex; break;
                    }
                    const auto &xyz = Titanfall::Bsp::vertices.at(p);
                    points[k] = {xyz.x(),xyz.y(),xyz.z()};
                }
                const V3 cross = Respawn::Bake::cross(points[1]-points[0],points[2]-points[0]);
                if (Respawn::Bake::length(cross) < 1e-8) continue;
                const V3 n = Respawn::Bake::normalize(cross);
                constexpr double thickness = 0.025;
                Respawn::Bake::Brush prism;
                prism.mins = Respawn::Bake::vmin(points[0],Respawn::Bake::vmin(points[1],points[2])) - V3{thickness,thickness,thickness};
                prism.maxs = Respawn::Bake::vmax(points[0],Respawn::Bake::vmax(points[1],points[2])) + V3{thickness,thickness,thickness};
                const double d = Respawn::Bake::dot(n,points[0]);
                prism.planes = {{n.x,n.y,n.z,d+thickness},{-n.x,-n.y,-n.z,-d+thickness}};
                for (int k = 0; k < 3; ++k) {
                    const V3 edge = Respawn::Bake::normalize(Respawn::Bake::cross(points[(k+1)%3]-points[k],n));
                    prism.planes.push_back({edge.x,edge.y,edge.z,Respawn::Bake::dot(edge,points[k])});
                }
                brushes.push_back(std::move(prism));
            }
        }
    }
    const Respawn::Bake::Occluders occluders(std::move(brushes));

    // Page sizes: used area rounded up to a power of two, as retail pages are.
    std::vector<Respawn::Bake::PageSize> pages;
    for (const Respawn::LightmapPageExtent &used : Shared::lightmapAtlas.used()) {
        auto round = [](std::uint32_t v) { std::uint32_t p = 16; while (p < v) p <<= 1; return p; };
        pages.push_back({round(used.width), round(used.height)});
    }
    if (pages.empty())
        pages.push_back({16, 16});
    for (const Respawn::Bake::PageSize &page : pages)
        Titanfall2::Bsp::lightmapHeaders.push_back({1, static_cast<uint16_t>(page.width), static_cast<uint16_t>(page.height)});

    // Normalize vertex lightmap UVs now that page sizes are final.
    for (const Titanfall::Bsp::LightmapVertexRange &range : Titanfall::Bsp::lightmapVertexRanges) {
        const Respawn::Bake::PageSize &page = pages.at(range.page);
        const Vector2 scale(1.0f / page.width, 1.0f / page.height);
        for (std::size_t i = range.first; i < range.first + range.count; i++) {
            Vector2 &uv = range.bump ? Titanfall::Bsp::vertexLitBumpVertices.at(i).lightmapUV
                                     : Titanfall::Bsp::vertexLitFlatVertices.at(i).lightmapUV;
            uv = Vector2(uv.x() * scale.x(), uv.y() * scale.y());
        }
    }

    Respawn::Bake::Options options;
    options.luxelSize = Shared::luxelSize;
    // Authored outdoor test yards can opt out of sampled sky occlusion while
    // retaining realtime light shadow masks. Keep the existing default bake.
    if (HasKey(world, "_skyocclusion"))
        options.ambientOcclusion = DoubleForKey(world, "_skyocclusion", 1) > 0;
    if (HasKey(world, "_skyfixedpattern"))
        options.ambientFixedPattern = DoubleForKey(world, "_skyfixedpattern", 0) > 0;
    if (HasKey(world, "_skysamples")) {
        const double samples = DoubleForKey(world, "_skysamples", 16);
        if (!std::isfinite(samples)) Error("Sky sample count must be finite");
        options.ambientSamples = static_cast<int>(std::clamp(samples, 1.0, 256.0));
    }
    // Worldspawn "_bouncescale" scales the one-bounce indirect light (0 disables it).
    if (HasKey(world, "_bouncescale")) {
        options.bounceScale = DoubleForKey(world, "_bouncescale", 1);
        if (options.bounceScale <= 0)
            options.bounceSamples = 0;
    }
    Respawn::Bake::Result result;
    try {
        result = Respawn::Bake::bake(Titanfall::Bsp::lightmapCharts, pages, Titanfall2::Bsp::bakeLights,
                                     Titanfall2::Bsp::ambient, occluders, options);
    } catch (const std::exception &error) {
        Error("Lightmap bake failed: %s", error.what());
    }
    Titanfall2::Bsp::lightmapDataSky = std::move(result.sky);
    Titanfall2::Bsp::lightmapDataRtl = std::move(result.rtl);
    Titanfall2::Bsp::lightmapRtlPages = std::move(result.rtlPages);
    Titanfall2::Bsp::lightingBaked = true;

    // Character light probes over the lit geometry, found through a KD tree.
    V3 lo{1e30, 1e30, 1e30}, hi{-1e30, -1e30, -1e30};
    for (const Respawn::Bake::Chart &chart : Titanfall::Bsp::lightmapCharts)
        for (const V3 &p : chart.constant >= 0 ? std::vector<V3>() : chart.positions) {  // skip self-lit sky shells
            lo = Respawn::Bake::vmin(lo, p);
            hi = Respawn::Bake::vmax(hi, p);
        }
    std::vector<V3> probePoints;
    try {
        probePoints = Respawn::Bake::probePositions(occluders, lo, hi);
        // Dense probes where characters stand, as retail places them; the grid covers open air.
        const auto walkable = Respawn::Bake::walkableProbePositions(Titanfall::Bsp::lightmapCharts, occluders);
        probePoints.insert(probePoints.end(), walkable.begin(), walkable.end());
        Sys_Printf("%9zu walkable-surface light probes\n", walkable.size());
        Titanfall2::Bsp::lightprobes = Respawn::Bake::bakeProbes(probePoints, Titanfall2::Bsp::bakeLights,
                                                                  Titanfall2::Bsp::ambient, occluders, options,
                                                                  &result.bounce);
    } catch (const std::exception &error) {
        Error("Light probe bake failed: %s", error.what());
    }
    // Other environments: probes around client scene anchors (the menu stage)
    // inside their light_environment_volume, lit by that environment's sun and
    // ambient plus nearby realtime lights.
    std::size_t stageProbes = 0;
    for (const entity_t &volumeEntity : entities) {
        if (!volumeEntity.classname_is("light_environment_volume"))
            continue;
        const EnvironmentVolume volume = ParseVolume(volumeEntity);
        std::vector<V3> stage;
        for (const entity_t &anchor : entities) {
            if (!anchor.classname_is("info_target_clientside") || !striEqualPrefix(anchor.valueForKey("script_name"), "menu_"))
                continue;
            const V3 a = OriginForEntity(anchor);
            if (!volume.contains(a))
                continue;
            for (double z = 0; z <= 192; z += 64)
                for (double y = -128; y <= 128; y += 64)
                    for (double x = -128; x <= 128; x += 64)
                        stage.push_back({a.x + x, a.y + y, a.z + z});
        }
        if (stage.empty())
            continue;
        std::vector<Light> stageLights = Titanfall2::Bsp::bakeLights;
        for (std::size_t i = 0; i < stageLights.size(); i++)
            if (stageLights[i].type == LightType::Sun)
                stageLights[i].realtime = bakeLightEnvironments[i] == volume.environment;
        const auto found = environmentAmbients.find(volume.environment);
        const V3 stageAmbient = found != environmentAmbients.end() ? found->second : V3{};
        try {
            const auto baked = Respawn::Bake::bakeProbes(stage, stageLights, stageAmbient, occluders, options);
            Titanfall2::Bsp::lightprobes.insert(Titanfall2::Bsp::lightprobes.end(), baked.begin(), baked.end());
            probePoints.insert(probePoints.end(), stage.begin(), stage.end());
            stageProbes += stage.size();
        } catch (const std::exception &error) {
            Error("Light environment %d probe bake failed: %s", volume.environment, error.what());
        }
    }

    // Retail places one probe per static prop first, at its lighting origin, then
    // the environment's own probes. The parent record's range covers only the
    // latter, but the KD tree indexes every probe by absolute index. 0x66 maps
    // each prop to its probe.
    std::vector<V3> propPoints;
    for (const Titanfall2::GameLumpProp_t &prop : Titanfall2::Bsp::gameLumpProps) {
        const bool lightingOrigin = (prop.flags & 0x02) != 0;
        const Vector3 &o = lightingOrigin ? prop.unk : prop.origin;
        propPoints.push_back({o.x(), o.y(), o.z() + (lightingOrigin ? 0.0 : 32.0)});
    }
    // Titanfall 1 keeps its static props in its own game lump records.
    if (g_game->bspVersion == 29)
        for (const Titanfall::GameLumpProp_t &prop : Titanfall::Bsp::gameLumpProps)
            propPoints.push_back({prop.origin.x(), prop.origin.y(), prop.origin.z() + 32.0});
    try {
        auto propProbes = Respawn::Bake::bakeProbes(propPoints, Titanfall2::Bsp::bakeLights, Titanfall2::Bsp::ambient,
                                                    occluders, options, &result.bounce);
        Titanfall2::Bsp::lightprobes.insert(Titanfall2::Bsp::lightprobes.begin(), propProbes.begin(), propProbes.end());
    } catch (const std::exception &error) {
        Error("Static prop light probe bake failed: %s", error.what());
    }
    Titanfall2::Bsp::staticPropLightprobeIndices.clear();
    for (uint32_t i = 0; i < propPoints.size(); ++i)
        Titanfall2::Bsp::staticPropLightprobeIndices.push_back(i);
    const uint32_t propProbeCount = static_cast<uint32_t>(propPoints.size());
    probePoints.insert(probePoints.begin(), propPoints.begin(), propPoints.end());

    Respawn::Bake::ProbeTree tree = Respawn::Bake::buildProbeTree(probePoints);
    Titanfall2::Bsp::lightprobeTree = std::move(tree.nodes);
    Titanfall2::Bsp::lightprobeReferences = std::move(tree.references);
    EmitLightprobeBsp();
    Titanfall2::Bsp::lightprobeParentInfos.push_back({0, propProbeCount,
                                                      static_cast<uint32_t>(Titanfall2::Bsp::lightprobes.size()) - propProbeCount,
                                                      0, static_cast<uint32_t>(Titanfall2::Bsp::lightprobeReferences.size()),
                                                      0, static_cast<uint32_t>(Titanfall2::Bsp::lightprobeTree.size())});

    EmitShadowEnvironments();
    if (g_game->bspVersion == 29)
        EmitCubemapsTF1(&occluders, &result.bounce);
    else
        EmitCubemaps(&occluders, &result.bounce);

    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    Sys_Printf("%9zu world lights (%d hardware)\n", Titanfall2::Bsp::worldLights.size(), hardware);
    Sys_Printf("%9zu occluding brushes\n", occluders.size());
    Sys_Printf("%9zu lightmap pages, %zu charts\n", pages.size(), Titanfall::Bsp::lightmapCharts.size());
    Sys_Printf("%9zu lit texels, %zu with realtime lights, %zu RTL pages\n", result.chartedTexels,
               result.realtimeTexels, Titanfall2::Bsp::lightmapRtlPages.size());
    Sys_Printf("%9zu light probes (%zu for other environments), %zu tree nodes\n", Titanfall2::Bsp::lightprobes.size(),
               stageProbes, Titanfall2::Bsp::lightprobeTree.size());
    Sys_Printf("%9zu shadow environments, %zu shadow meshes (%zu triangles)\n", Titanfall2::Bsp::shadowEnvironments.size(),
               Titanfall2::Bsp::shadowMeshes.size(), Titanfall2::Bsp::shadowMeshIndices.size() / 3);
    Sys_Printf("%9.1f seconds baking\n", seconds);
}
