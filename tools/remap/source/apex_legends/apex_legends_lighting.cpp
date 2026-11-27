/* -------------------------------------------------------------------------------

   Copyright (C) 2022-2025 MRVN-Radiant and contributors.
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
    Apex Legends Lighting Lumps

    This file handles lighting-related BSP lumps:
    - World Lights lump (0x36): Dynamic light sources
    - Cubemaps lump (0x2A): Cubemap sample positions
    - Cubemaps Ambient RCP lump (0x2B): Ambient reciprocal per cubemap
    - Shadow Environments lump (0x05): Shadow environment data
    - Shadow Mesh lumps (0x7C-0x7F): Shadow mesh geometry
    - CSM AABB lumps (0x63-0x64): Cascaded shadow map data
*/

#include "../remap.h"
#include "../bspfile_abstract.h"
#include "miniz.h"
#include <algorithm>
#include <cmath>
#include <unordered_map>
#include <functional>
#include <array>
#include <cstring>
#include <map>

/*
    EmitCubemaps
    Lump 0x2A: one sample per cubemap (int32 origin, guid 0). Each sample is a
    frame of the PAKFILE's materials/maps/<map>/cubemaps.hdr.vtf, which
    EmitCubemapPakfile() renders once the lighting occluders exist; mesh records
    and envmap_volume "cubemapID" index this table.

    Positions come from env_cubemap entities (an editor-only class). Without
    any, one cubemap is placed 64 units above the mean player spawn, or at the
    world centre.
*/
void ApexLegends::EmitCubemaps() {
    Sys_FPrintf(SYS_VRB, "--- EmitCubemaps ---\n");
    ApexLegends::Bsp::cubemaps.clear();

    std::vector<Vector3> origins;
    for (const entity_t &e : entities) {
        if (e.classname_is("env_cubemap")) origins.push_back(e.vectorForKey("origin"));
    }
    if (origins.empty()) {
        Vector3 sum(0, 0, 0);
        int count = 0;
        for (const entity_t &e : entities) {
            if (e.classname_is("info_player_start") || e.classname_prefixed("info_spawnpoint_human")) {
                sum += e.vectorForKey("origin");
                ++count;
            }
        }
        if (count) {
            origins.push_back(sum * (1.0f / count) + Vector3(0, 0, 64));
        } else {
            MinMax worldBounds;
            for (const Shared::Mesh_t &mesh : Shared::meshes) {
                worldBounds.extend(mesh.minmax.mins);
                worldBounds.extend(mesh.minmax.maxs);
            }
            origins.push_back(worldBounds.valid() ? (worldBounds.mins + worldBounds.maxs) * 0.5f : Vector3(0, 0, 0));
        }
    }
    if (origins.size() > 255) {
        Error("%zu cubemaps exceed the mesh record's 8-bit cubemap index", origins.size());
    }
    for (const Vector3 &origin : origins) {
        CubemapSample_t sample;
        sample.origin[0] = static_cast<int32_t>(std::lround(origin[0]));
        sample.origin[1] = static_cast<int32_t>(std::lround(origin[1]));
        sample.origin[2] = static_cast<int32_t>(std::lround(origin[2]));
        sample.guid = 0;
        ApexLegends::Bsp::cubemaps.push_back(sample);
    }
    for (const entity_t &e : entities) {
        const char *id = e.valueForKey("cubemapID");
        if (e.classname_is("envmap_volume") && id[0] && (atoi(id) < 0 || atoi(id) >= int(origins.size()))) {
            Sys_Warning("envmap_volume cubemapID %s is outside the %zu cubemaps\n", id, origins.size());
        }
    }
    Sys_Printf("  %zu cubemap samples\n", ApexLegends::Bsp::cubemaps.size());
}

/*
    EmitWorldLights
    Writes lump 0x36 (and the tweak list 0x55) the way retail S0-S3 maps do.
    Measured from retail mp_rr_aqueduct (359 records matched to their
    _env.ent entities):

    - order: emit_skyambient, emit_skylight, then local lights grouped as
      tweakable, realtime with shadows, realtime without shadows, static
      spots, static points (entity order within a group);
    - intensity = (c/255)^2.2 * brightness/255 per channel, x100000 when
      "_pbr_falloff" "1";
    - attenuation = 1 + linear*d + quadratic*d^2 through (0,1),
      (_fifty_percent_distance, 0.5) and (_zero_percent_distance, 0);
      radius = _zero_percent_distance;
    - stopdot/stopdot2 = cos(_inner_cone)/cos(_cone);
    - flags: 0x04 non-PBR or 0x20 PBR; 0x08 realtime (also set for
      script_tweakable); 0x10 realtime without shadows; 0x40 realtime_shadows
      "2"; 0x80 script_tweakable;
    - shadow_upres / shadow_filter_size are stored only for realtime lights
      with shadows; the sun uses flags 0x18 and the ambient 0.
*/
namespace {
Vector3 LinearLightColour(const char *value, float defaultBrightness) {
    float r = 255.0f, g = 255.0f, b = 255.0f, brightness = defaultBrightness;
    if (value && sscanf(value, "%f %f %f %f", &r, &g, &b, &brightness) < 3) {
        r = g = b = 255.0f;
    }
    const float scale = brightness / 255.0f;
    return Vector3(std::pow(r / 255.0f, 2.2f) * scale,
                   std::pow(g / 255.0f, 2.2f) * scale,
                   std::pow(b / 255.0f, 2.2f) * scale);
}

float FloatKey(const entity_t &e, const char *key, float fallback) {
    const char *value = e.valueForKey(key);
    return (value && value[0]) ? static_cast<float>(atof(value)) : fallback;
}

Vector3 LightDirection(const entity_t &e) {
    Vector3 angles = e.vectorForKey("angles");
    if (e.valueForKey("pitch")[0]) {
        angles[0] = -e.floatForKey("pitch");  // "pitch" is stored negated
    }
    return ApexLegends::vector3_from_angles(angles);
}

// Source-style aiming, as in the Titanfall writer: a light_spot with "target"
// points at that entity's origin; a missing or coincident target warns and
// falls back to the angles.
Vector3 SpotDirection(const entity_t &e) {
    const char *target = e.valueForKey("target");
    if (target && target[0]) {
        const Vector3 origin = e.vectorForKey("origin");
        if (const entity_t *aim = FindTargetEntity(target)) {
            const Vector3 delta = aim->vectorForKey("origin") - origin;
            const float length = vector3_length(delta);
            if (length > 1e-3f) return delta * (1.0f / length);
            Sys_FPrintf(SYS_WRN, "WARNING: light_spot at %s: target \"%s\" is at the light origin, using angles\n",
                        e.valueForKey("origin"), target);
        } else {
            Sys_FPrintf(SYS_WRN, "WARNING: light_spot at %s: missing target \"%s\", using angles\n",
                        e.valueForKey("origin"), target);
        }
    }
    return LightDirection(e);
}

// Order key for local lights; lower sorts first.
int LightGroup(const WorldLight_t &light) {
    if (light.flags & WORLDLIGHT_FLAG_TWEAK) return 0;
    if (light.flags & WORLDLIGHT_FLAG_REALTIME) return (light.flags & WORLDLIGHT_FLAG_NO_RT_SHADOWS) ? 2 : 1;
    return light.type == emit_spotlight ? 3 : 4;
}
}

void ApexLegends::EmitWorldLights() {
    Sys_FPrintf(SYS_VRB, "--- EmitWorldLights ---\n");
    ApexLegends::Bsp::worldLights.clear();
    ApexLegends::Bsp::tweakLights.clear();

    std::vector<WorldLight_t> ambients, suns;
    std::vector<std::pair<int, WorldLight_t>> locals;  // (group, light), stable-sorted by group

    for (const entity_t &e : entities) {
        const char *classname = e.classname();
        if (striEqual(classname, "light_environment")) {
            WorldLight_t ambient = {};
            ambient.origin = e.vectorForKey("origin");
            ambient.intensity = LinearLightColour(e.valueForKey("_ambient"), 255.0f);
            ambient.type = emit_skyambient;
            ambients.push_back(ambient);

            WorldLight_t sun = {};
            sun.origin = ambient.origin;
            sun.intensity = LinearLightColour(e.valueForKey("_light"), 255.0f);
            sun.normal = LightDirection(e);
            sun.type = emit_skylight;
            sun.flags = 0x18;
            sun.sun_highlight_size_or_vfog_boost = FloatKey(e, "sun_highlight_size", 0.0f);
            suns.push_back(sun);
            continue;
        }

        const bool spot = striEqual(classname, "light_spot") || striEqual(classname, "light_spotlight");
        if (!spot && !striEqual(classname, "light")) {
            continue;
        }

        WorldLight_t light = {};
        light.origin = e.vectorForKey("origin");
        light.type = spot ? emit_spotlight : emit_point;
        // Retail S0-S3 world lights never use the style field (style 0 in all
        // 31,262 records of six maps, 27 Nov 2026), so bake styled lights as
        // constant lights, as the Titanfall writers do.
        light.style = 0;
        if (const int style = e.intForKey("_style", "style"); style != 0)
            Sys_FPrintf(SYS_WRN, "WARNING: %s at %s has style %d; Respawn world lights have no light styles, baking it as a constant light\n",
                        e.classname(), e.valueForKey("origin"), style);
        light.normal = spot ? SpotDirection(e) : Vector3(1.0f, 0.0f, 0.0f);

        const bool pbr = FloatKey(e, "_pbr_falloff", 0.0f) != 0.0f;
        const bool tweakable = FloatKey(e, "script_tweakable", FloatKey(e, "tweakable", 0.0f)) != 0.0f;
        const bool realtime = FloatKey(e, "realtime", 0.0f) != 0.0f;
        const int realtimeShadows = static_cast<int>(FloatKey(e, "realtime_shadows", 0.0f));

        light.intensity = LinearLightColour(e.valueForKey("_light"), 255.0f) * (pbr ? 100000.0f : 1.0f);

        // Falloff: zero at d0, half at d50 (default 0.3 * d0, as retail's
        // "_half_bright_fraction"). "_distance" is the editor's radius key.
        float d0 = FloatKey(e, "_zero_percent_distance", FloatKey(e, "_distance", 512.0f));
        float d50 = FloatKey(e, "_fifty_percent_distance", FloatKey(e, "_half_bright_fraction", 0.3f) * d0);
        if (d0 <= 1.0f) d0 = 512.0f;
        if (d50 <= 0.0f || d50 >= d0) d50 = 0.3f * d0;
        const float det = d50 * d0 * d0 - d0 * d50 * d50;
        light.constant_attn = 1.0f;
        light.linear_attn = (-0.5f * d0 * d0 + d50 * d50) / det;
        light.quadratic_attn = (-d50 + 0.5f * d0) / det;
        light.radius = d0;

        if (spot) {
            const float inner = FloatKey(e, "_inner_cone", 30.0f);
            const float outer = FloatKey(e, "_cone", 45.0f);
            light.stopdot = std::cos(degrees_to_radians(inner));
            light.stopdot2 = std::cos(degrees_to_radians(std::max(inner, outer)));
            light.exponent = FloatKey(e, "_exponent", 1.0f);
        }

        int flags = pbr ? WORLDLIGHT_FLAG_PBR : WORLDLIGHT_FLAG_NON_PBR;
        if (tweakable) flags |= WORLDLIGHT_FLAG_TWEAK | WORLDLIGHT_FLAG_REALTIME;
        if (realtime) {
            flags |= WORLDLIGHT_FLAG_REALTIME;
            if (realtimeShadows == 0) flags |= WORLDLIGHT_FLAG_NO_RT_SHADOWS;
            if (realtimeShadows == 2) flags |= WORLDLIGHT_FLAG_RT_SHADOWS_2;
        }
        light.flags = flags;
        if (realtime && realtimeShadows != 0) {
            light.shadowUpresFactor = e.intForKey("shadow_upres");
            light.shadowFilterSize = e.intForKey("shadow_filter_size");
        }
        light.shadowBias = FloatKey(e, "shadow_bias", 0.0f);
        light.emitter_radius = FloatKey(e, "_emitter_radius", 0.0f);
        light.specular_intensity = FloatKey(e, "_specular_intensity", 1.0f);
        locals.emplace_back(LightGroup(light), light);
    }

    std::stable_sort(locals.begin(), locals.end(),
                     [](const auto &a, const auto &b) { return a.first < b.first; });
    for (const WorldLight_t &light : ambients) ApexLegends::Bsp::worldLights.push_back(light);
    for (const WorldLight_t &light : suns) ApexLegends::Bsp::worldLights.push_back(light);
    for (const auto &[group, light] : locals) ApexLegends::Bsp::worldLights.push_back(light);

    for (uint32_t i = 0; i < ApexLegends::Bsp::worldLights.size(); i++) {
        if (ApexLegends::Bsp::worldLights[i].flags & WORLDLIGHT_FLAG_TWEAK) {
            ApexLegends::Bsp::tweakLights.push_back(i);
        }
    }

    Sys_Printf("  %zu world lights (%zu environments, %zu point/spot, %zu tweakable)\n",
        ApexLegends::Bsp::worldLights.size(), ambients.size(), locals.size(),
        ApexLegends::Bsp::tweakLights.size());
}

/*
    HardwareLightIndex
    Index of a world light among the non-ambient world lights. RTL pages
    (0x7A) and light probes reference lights by this index; the sun of the
    first light_environment is 0.
*/
int ApexLegends::HardwareLightIndex(std::size_t worldLightIndex) {
    int ambientsBefore = 0;
    for (std::size_t i = 0; i < worldLightIndex && i < ApexLegends::Bsp::worldLights.size(); i++) {
        if (ApexLegends::Bsp::worldLights[i].type == emit_skyambient) ambientsBefore++;
    }
    return static_cast<int>(worldLightIndex) - ambientsBefore;
}

/*
    LocalLightFalloff
    Distance falloff of a point or spot light, 0 at and beyond its radius.
    Non-PBR lights use their stored attenuation polynomial. PBR lights are
    stored x100000, which only fits an inverse-square law, so they use a
    windowed inverse square; that shape is an approximation of the engine's
    shader, not a measurement.
*/
float ApexLegends::LocalLightFalloff(const WorldLight_t &light, float dist) {
    if (light.radius > 0.0f && dist >= light.radius) return 0.0f;
    if (light.flags & WORLDLIGHT_FLAG_PBR) {
        const float d = std::max(dist, 1.0f);
        float window = 1.0f;
        if (light.radius > 0.0f) {
            const float x = dist / light.radius, x4 = x * x * x * x;
            window = std::max(0.0f, 1.0f - x4);
            window *= window;
        }
        return window / (d * d);
    }
    const float value = light.constant_attn + light.linear_attn * dist + light.quadratic_attn * dist * dist;
    return std::clamp(value, 0.0f, 1.0f);
}

/*
    LocalLightSpot
    Cone factor of a light toward `dirFromLight` (unit vector from the light);
    1 for point lights.
*/
float ApexLegends::LocalLightSpot(const WorldLight_t &light, const Vector3 &dirFromLight) {
    if (light.type != emit_spotlight) return 1.0f;
    const float spotDot = vector3_dot(dirFromLight, light.normal);
    if (spotDot <= light.stopdot2) return 0.0f;
    if (spotDot >= light.stopdot || light.stopdot <= light.stopdot2) return 1.0f;
    float t = (spotDot - light.stopdot2) / (light.stopdot - light.stopdot2);
    if (light.exponent > 0.0f && light.exponent != 1.0f) t = std::pow(t, light.exponent);
    return t;
}

/*
    EmitCsmTree
    Cascaded shadow object tree (0x63) and its references (0x64), as in
    retail S3 mp_rr_aqueduct: the references are uint32 and name every
    shadow mesh by index (83 of 83) plus shadow-casting static props by
    object id (prop base from LEVEL_INFO + prop index; 1,891 of 5,863 props).
    Node bounds are in light space: z = -sun, x = normalize(sun.y, -sun.x, 0),
    y = z cross x (the rotation fitted on retail TF2 CSM trees). Nodes:
      word at +0x0C: child count | first child << 8 (22 bits) | bit 30 (0 for leaves)
      word at +0x1C: reference count | first reference << 8 (22 bits) | bit 30
    Same on S3-native World's Edge (211,364 nodes) and Firing Range (one root
    per shadow environment); 0x26 is the subtree total per node up to the
    last internal node.
    All static props are included, bounded by their editor copy.
*/
static void EmitCsmTree(const std::vector<MinMax> &shadowMeshBounds) {
    Vector3 sun(0, 0, -1);
    for (const WorldLight_t &light : ApexLegends::Bsp::worldLights) {
        if (light.type == emit_skylight) { sun = light.normal; break; }
    }
    const Vector3 z = vector3_normalised(sun * -1.0f);
    Vector3 x(sun.y(), -sun.x(), 0);
    x = vector3_length(x) < 1e-4f ? Vector3(1, 0, 0) : vector3_normalised(x);
    const Vector3 y = vector3_cross(z, x);

    std::vector<uint32_t> ids;
    std::vector<MinMax> boxes;
    auto add = [&](uint32_t id, const MinMax &bounds) {
        if (!bounds.valid()) return;
        MinMax light;
        for (int corner = 0; corner < 8; corner++) {
            const Vector3 p((corner & 1) ? bounds.maxs.x() : bounds.mins.x(),
                            (corner & 2) ? bounds.maxs.y() : bounds.mins.y(),
                            (corner & 4) ? bounds.maxs.z() : bounds.mins.z());
            light.extend(Vector3(vector3_dot(p, x), vector3_dot(p, y), vector3_dot(p, z)));
        }
        ids.push_back(id);
        boxes.push_back(light);
    };
    for (std::size_t i = 0; i < shadowMeshBounds.size(); i++) add(static_cast<uint32_t>(i), shadowMeshBounds[i]);
    const uint32_t propBase = ApexLegends::Bsp::levelInfo.empty() ? 0 : static_cast<uint32_t>(ApexLegends::Bsp::levelInfo[0].unk3);
    for (const auto &[propIndex, bounds] : ApexLegends::Bsp::staticPropShadowBounds) add(propBase + propIndex, bounds);

    if (ids.empty()) {
        ApexLegends::Bsp::csmAABBNodes.push_back({});
        return;
    }
    const ApexLegends::ObjTreeNode root = ApexLegends::BuildObjTree(boxes);

    std::size_t lastInternal = 0;
    std::function<void(const ApexLegends::ObjTreeNode &, std::size_t)> emit = [&](const ApexLegends::ObjTreeNode &node, std::size_t index) {
        std::size_t total = 0;
        std::function<void(const ApexLegends::ObjTreeNode &)> count = [&](const ApexLegends::ObjTreeNode &n) {
            total += n.refs.size();
            for (const ApexLegends::ObjTreeNode &child : n.children) count(child);
        };
        count(node);
        const uint32_t firstRef = static_cast<uint32_t>(ApexLegends::Bsp::csmObjRefsTotal.size());
        for (uint32_t r : node.refs) ApexLegends::Bsp::csmObjRefsTotal.push_back(ids[r]);
        if (node.refs.size() > 0xFF || firstRef >= ApexLegends::kTreeIndexLimit) Error("CSM tree node exceeds its 8-bit count or 22-bit reference offset");
        {
            CSMAABBNode_t &out = ApexLegends::Bsp::csmAABBNodes[index];
            out.mins = node.bounds.mins;
            out.maxs = node.bounds.maxs;
            out.child0 = 0;
            out.child1 = static_cast<uint32_t>(node.refs.size()) | (firstRef << 8) | 0x40000000u;
        }
        if (ApexLegends::Bsp::csmNumObjRefsTotalForAabb.size() <= index) ApexLegends::Bsp::csmNumObjRefsTotalForAabb.resize(index + 1);
        ApexLegends::Bsp::csmNumObjRefsTotalForAabb[index] = static_cast<uint32_t>(total);
        if (node.children.empty()) return;
        lastInternal = std::max(lastInternal, index);
        const std::size_t first = ApexLegends::Bsp::csmAABBNodes.size();
        if (node.children.size() > 0xFF || first + node.children.size() >= ApexLegends::kTreeIndexLimit) Error("CSM tree exceeds its 8-bit child count or 22-bit child index");
        ApexLegends::Bsp::csmAABBNodes[index].child0 = static_cast<uint32_t>(node.children.size()) | (static_cast<uint32_t>(first) << 8) | 0x40000000u;
        ApexLegends::Bsp::csmAABBNodes.resize(first + node.children.size());
        for (std::size_t i = 0; i < node.children.size(); i++) emit(node.children[i], first + i);
    };
    ApexLegends::Bsp::csmAABBNodes.emplace_back();
    emit(root, 0);
    // 0x26 holds subtree totals up to the last internal node (retail S3).
    ApexLegends::Bsp::csmNumObjRefsTotalForAabb.resize(lastInternal + 1);
}

/*
    EmitShadowMeshes
    Generates shadow mesh data from the world geometry.
    Shadow meshes are simplified versions of world geometry used for cascaded shadow maps.
    
    This function creates:
    - Shadow mesh opaque vertices (lump 0x7C) - vertex positions only
    - Shadow mesh indices (lump 0x7E) - triangle indices
    - Shadow meshes (lump 0x7F) - mesh descriptors
    - CSM AABB nodes (lump 0x63) - bounding volume hierarchy for shadow culling
    
    Must be called AFTER EmitMeshes() since we use the mesh data.
*/
void ApexLegends::EmitShadowMeshes() {
    Sys_FPrintf(SYS_VRB, "--- EmitShadowMeshes ---\n");
    
    // Clear any existing data
    ApexLegends::Bsp::shadowMeshOpaqueVerts.clear();
    ApexLegends::Bsp::shadowMeshAlphaVerts.clear();
    ApexLegends::Bsp::shadowMeshIndices.clear();
    ApexLegends::Bsp::shadowMeshes.clear();
    ApexLegends::Bsp::csmAABBNodes.clear();
    ApexLegends::Bsp::csmObjRefsTotal.clear();
    ApexLegends::Bsp::csmNumObjRefsTotalForAabb.clear();
    
    // We'll create one shadow mesh per world mesh (model 0)
    // For simplicity, we iterate the meshes from model 0 (worldspawn)
    
    if (ApexLegends::Bsp::models.empty()) {
        Sys_Printf("  No models, skipping shadow mesh generation\n");
        return;
    }
    
    const auto& worldModel = ApexLegends::Bsp::models[0];
    
    // Get the base vertex data - we need to collect vertices from the different vertex formats
    // For shadow meshes, we only need position data
    
    uint32_t totalTriangles = 0;
    uint32_t totalVertices = 0;
    
    // Calculate world bounds for CSM AABB using MinMax class
    MinMax worldBounds;
    std::vector<MinMax> shadowMeshBounds;
    
    // Iterate through world meshes and generate shadow geometry
    for (int32_t meshIdx = worldModel.meshIndex; meshIdx < worldModel.meshIndex + worldModel.meshCount; meshIdx++) {
        if (meshIdx < 0 || meshIdx >= static_cast<int32_t>(ApexLegends::Bsp::meshes.size())) {
            continue;
        }
        
        const auto& mesh = ApexLegends::Bsp::meshes[meshIdx];
        
        // Skip meshes with no triangles
        if (mesh.triCount == 0) {
            continue;
        }
        
        // Skip sky meshes; alpha-tested casters go to the alpha stream below
        int sharedIdx = meshIdx - worldModel.meshIndex;
        if (sharedIdx >= 0 && sharedIdx < static_cast<int>(Shared::meshes.size())
            && (Shared::meshes[sharedIdx].shaderInfo->compileFlags & (C_SKY | C_ALPHASHADOW))) {
            continue;
        }
        
        // Get the vertex offset from the material sort entry
        // The mesh's materialOffset indexes into the materialSorts array
        uint32_t vertexOffset = 0;
        if (mesh.materialOffset < ApexLegends::Bsp::materialSorts.size()) {
            vertexOffset = ApexLegends::Bsp::materialSorts[mesh.materialOffset].vertexOffset;
        }
        
        // Get the vertices for this mesh based on vertex type
        // The mesh references indices into the meshIndices array, which point to vertices
        uint32_t firstShadowVert = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size());
        uint32_t firstShadowIndex = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshIndices.size());
        
        // Map from original vertex index to shadow vertex index
        std::unordered_map<uint16_t, uint16_t> vertexRemap;
        MinMax shadowBounds;
        
        // Process indices for this mesh
        uint32_t indexStart = mesh.triOffset;
        uint32_t indexCount = mesh.triCount * 3;  // triCount is triangle count, need 3 indices per tri
        
        for (uint32_t i = 0; i < indexCount; i++) {
            if (indexStart + i >= ApexLegends::Bsp::meshIndices.size()) {
                break;
            }
            
            uint16_t origIdx = ApexLegends::Bsp::meshIndices[indexStart + i];
            
            // Check if we've already remapped this vertex
            auto it = vertexRemap.find(origIdx);
            if (it != vertexRemap.end()) {
                ApexLegends::Bsp::shadowMeshIndices.push_back(it->second);
            } else {
                // Add new shadow vertex
                uint16_t newIdx = static_cast<uint16_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size() - firstShadowVert);
                vertexRemap[origIdx] = newIdx;
                
                // Get the vertex position based on vertex type
                Vector3 pos(0, 0, 0);
                
                // The index in meshIndices is relative to the materialSort's vertexOffset
                // Add vertexOffset to get the actual vertex index in the vertex format array
                uint32_t actualIdx = vertexOffset + origIdx;
                
                // The vertex format structs (VertexLitBump_t, etc.) contain a vertexIndex
                // which points to the actual position in Titanfall::Bsp::vertices
                uint32_t positionIndex = 0;
                
                // Vertex type bits in mesh.flags:
                // S_VERTEX_LIT_FLAT  = 0x000
                // S_VERTEX_LIT_BUMP  = 0x200
                // S_VERTEX_UNLIT     = 0x400
                // S_VERTEX_UNLIT_TS  = 0x600
                switch (mesh.flags & 0x600) {
                    case 0x000:  // S_VERTEX_LIT_FLAT
                        if (actualIdx < ApexLegends::Bsp::vertexLitFlatVertices.size()) {
                            positionIndex = ApexLegends::Bsp::vertexLitFlatVertices[actualIdx].vertexIndex;
                        }
                        break;
                    case 0x200:  // S_VERTEX_LIT_BUMP
                        if (actualIdx < ApexLegends::Bsp::vertexLitBumpVertices.size()) {
                            positionIndex = ApexLegends::Bsp::vertexLitBumpVertices[actualIdx].vertexIndex;
                        }
                        break;
                    case 0x400:  // S_VERTEX_UNLIT
                        if (actualIdx < ApexLegends::Bsp::vertexUnlitVertices.size()) {
                            positionIndex = ApexLegends::Bsp::vertexUnlitVertices[actualIdx].vertexIndex;
                        }
                        break;
                    case 0x600:  // S_VERTEX_UNLIT_TS
                        if (actualIdx < ApexLegends::Bsp::vertexUnlitTSVertices.size()) {
                            positionIndex = ApexLegends::Bsp::vertexUnlitTSVertices[actualIdx].vertexIndex;
                        }
                        break;
                    default:
                        // Fallback: use index directly
                        positionIndex = origIdx;
                        break;
                }
                
                // Get the actual position from the vertices array
                if (positionIndex < Titanfall::Bsp::vertices.size()) {
                    pos = Titanfall::Bsp::vertices[positionIndex];
                }
                
                // Update world bounds
                worldBounds.extend(pos);
                shadowBounds.extend(pos);
                
                ApexLegends::Bsp::shadowMeshOpaqueVerts.push_back(pos);
                ApexLegends::Bsp::shadowMeshIndices.push_back(newIdx);
            }
        }
        
        // Create the shadow mesh entry if we added any geometry
        uint32_t shadowTriCount = (static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshIndices.size()) - firstShadowIndex) / 3;
        if (shadowTriCount > 0) {
            ShadowMesh_t shadowMesh = {};
            shadowMesh.firstVertex = firstShadowVert;
            shadowMesh.triangleCount = shadowTriCount;
            shadowMesh.drawType = 1;  // Opaque
            shadowMesh.materialSortIdx = 0xFFFF;  // No material
            
            ApexLegends::Bsp::shadowMeshes.push_back(shadowMesh);
            shadowMeshBounds.push_back(shadowBounds);
            totalTriangles += shadowTriCount;
        }
    }
    
    // Alpha-tested casters ("$compileflag alphashadow"), as retail S3 writes
    // them (World's Edge: 8 of 137 shadow meshes): after every opaque mesh, one
    // per material sort, drawType 0 with that sort's index, vertices in 0x7D as
    // position + texture UV (float32), indices continuing the shared 0x7E stream.
    std::map<uint16_t, std::vector<int32_t>> alphaBySort;
    for (int32_t meshIdx = worldModel.meshIndex; meshIdx < worldModel.meshIndex + worldModel.meshCount; meshIdx++) {
        const int sharedIdx = meshIdx - worldModel.meshIndex;
        if (meshIdx < 0 || meshIdx >= static_cast<int32_t>(ApexLegends::Bsp::meshes.size())
            || sharedIdx >= static_cast<int>(Shared::meshes.size())) continue;
        const uint32_t flags = Shared::meshes[sharedIdx].shaderInfo->compileFlags;
        if ((flags & C_ALPHASHADOW) && !(flags & C_SKY) && ApexLegends::Bsp::meshes[meshIdx].triCount)
            alphaBySort[static_cast<uint16_t>(ApexLegends::Bsp::meshes[meshIdx].materialOffset)].push_back(meshIdx);
    }
    for (const auto &[sort, meshList] : alphaBySort) {
        ShadowMesh_t *alpha = nullptr;
        MinMax alphaBounds;
        std::map<std::array<float, 5>, uint16_t> lookup;
        auto finish = [&]() {
            if (alpha) shadowMeshBounds.push_back(alphaBounds);
            alpha = nullptr; alphaBounds = MinMax(); lookup.clear();
        };
        for (int32_t meshIdx : meshList) {
            const auto &mesh = ApexLegends::Bsp::meshes[meshIdx];
            const uint32_t vertexOffset = mesh.materialOffset < ApexLegends::Bsp::materialSorts.size()
                ? ApexLegends::Bsp::materialSorts[mesh.materialOffset].vertexOffset : 0;
            for (uint32_t t = 0; t < mesh.triCount; t++) {
                if (!alpha || lookup.size() + 3 > 65535) {
                    finish();
                    ShadowMesh_t entry = {};
                    entry.firstVertex = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshAlphaVerts.size());
                    entry.drawType = 0;
                    entry.materialSortIdx = sort;
                    ApexLegends::Bsp::shadowMeshes.push_back(entry);
                    alpha = &ApexLegends::Bsp::shadowMeshes.back();
                }
                for (int k = 0; k < 3; k++) {
                    const uint32_t index = mesh.triOffset + t * 3 + k;
                    if (index >= ApexLegends::Bsp::meshIndices.size()) continue;
                    const uint32_t v = vertexOffset + ApexLegends::Bsp::meshIndices[index];
                    uint32_t position = 0;
                    Vector2 uv(0, 0);
                    switch (mesh.flags & 0x600) {
                        case 0x200: position = ApexLegends::Bsp::vertexLitBumpVertices[v].vertexIndex; uv = ApexLegends::Bsp::vertexLitBumpVertices[v].uv0; break;
                        case 0x400: position = ApexLegends::Bsp::vertexUnlitVertices[v].vertexIndex; uv = ApexLegends::Bsp::vertexUnlitVertices[v].uv0; break;
                        case 0x600: position = ApexLegends::Bsp::vertexUnlitTSVertices[v].vertexIndex; uv = ApexLegends::Bsp::vertexUnlitTSVertices[v].uv0; break;
                        default:    position = ApexLegends::Bsp::vertexLitFlatVertices[v].vertexIndex; uv = ApexLegends::Bsp::vertexLitFlatVertices[v].uv0; break;
                    }
                    const Vector3 pos = position < Titanfall::Bsp::vertices.size() ? Titanfall::Bsp::vertices[position] : Vector3(0, 0, 0);
                    const std::array<float, 5> key{pos.x(), pos.y(), pos.z(), uv.x(), uv.y()};
                    auto found = lookup.find(key);
                    if (found == lookup.end()) {
                        found = lookup.emplace(key, static_cast<uint16_t>(ApexLegends::Bsp::shadowMeshAlphaVerts.size() - alpha->firstVertex)).first;
                        ShadowMeshAlphaVertex_t vertex = {};
                        vertex.position = pos;
                        const float u = uv.x(), w = uv.y();
                        std::memcpy(&vertex.texCoord[0], &u, 4);
                        std::memcpy(&vertex.texCoord[1], &w, 4);
                        ApexLegends::Bsp::shadowMeshAlphaVerts.push_back(vertex);
                    }
                    ApexLegends::Bsp::shadowMeshIndices.push_back(found->second);
                    worldBounds.extend(pos);
                    alphaBounds.extend(pos);
                }
                alpha->triangleCount++;
                totalTriangles++;
            }
        }
        finish();
    }

    totalVertices = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size());

    EmitCsmTree(shadowMeshBounds);

    Sys_Printf("  %zu shadow meshes (%u tris, %u verts, %zu CSM nodes, %zu CSM refs)\n",
        ApexLegends::Bsp::shadowMeshes.size(), totalTriangles, totalVertices,
        ApexLegends::Bsp::csmAABBNodes.size(), ApexLegends::Bsp::csmObjRefsTotal.size());
}

/*
    EmitShadowEnvironments
    Generates the shadow environment data for each light_environment.
    The shadow environment defines the sun direction for cascaded shadow maps.
    
    Must be called AFTER EmitWorldLights() since we iterate through the worldLights
    to find emit_skylight entries which contain the sun direction.
*/
void ApexLegends::EmitShadowEnvironments() {
    Sys_FPrintf(SYS_VRB, "--- EmitShadowEnvironments ---\n");
    ApexLegends::Bsp::shadowEnvironments.clear();

    // Count light environments by finding emit_skyambient lights
    // (each light_environment creates one emit_skyambient + one emit_skylight)
    size_t numLightEnvironments = 0;
    for (const auto& light : ApexLegends::Bsp::worldLights) {
        if (light.type == emit_skyambient) {
            numLightEnvironments++;
        }
    }

    // Get the shadow mesh data counts for reference
    uint32_t numShadowMeshes = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshes.size());
    uint32_t numCSMNodes = static_cast<uint32_t>(ApexLegends::Bsp::csmAABBNodes.size());
    uint32_t numCSMObjRefs = static_cast<uint32_t>(ApexLegends::Bsp::csmObjRefsTotal.size());

    if (numLightEnvironments == 0) {
        // No light_environment entities - create a default one
        // This is required for the engine to work properly
        Sys_Printf("  No light_environment found, creating default shadow environment\n");
        
        ShadowEnvironment_t defaultEnv = {};
        defaultEnv.beginAabbs = 0;
        defaultEnv.beginObjRefs = 0;
        defaultEnv.beginShadowMeshes = 0;
        defaultEnv.endAabbs = numCSMNodes;
        defaultEnv.endObjRefs = numCSMObjRefs;
        defaultEnv.endShadowMeshes = numShadowMeshes;
        // Default sun direction (pointing down and slightly south-west)
        defaultEnv.shadowDir = Vector3(0.5227f, 0.2733f, -0.8072f);
        
        ApexLegends::Bsp::shadowEnvironments.push_back(defaultEnv);
    } else {
        // Create shadow environment for each light_environment
        // The shadowDir in the shadow environment should match the light's normal
        // (the direction light travels, i.e., from sun towards ground)
        
        for (const auto& light : ApexLegends::Bsp::worldLights) {
            if (light.type == emit_skylight) {
                ShadowEnvironment_t env = {};
                env.beginAabbs = 0;
                env.beginObjRefs = 0;
                env.beginShadowMeshes = 0;
                env.endAabbs = numCSMNodes;
                env.endObjRefs = numCSMObjRefs;
                env.endShadowMeshes = numShadowMeshes;
                
                // shadowDir is the direction light travels (from sun towards ground)
                // This matches the worldlight's normal direction
                env.shadowDir = light.normal;
                
                ApexLegends::Bsp::shadowEnvironments.push_back(env);
            }
        }
    }

    Sys_Printf("  %zu shadow environments\n", ApexLegends::Bsp::shadowEnvironments.size());
}


/*
    AssignMeshCubemaps
    Mesh record field [2] carries the cubemap index in its high byte for lit
    meshes (retail: 0x0302 = lit bump, cubemap 3). Runs after EmitCubemaps
    and picks the cubemap nearest the mesh's bounds centre.
*/
void ApexLegends::AssignMeshCubemaps() {
    // Cubemap names in lump 0x2A order (EmitCubemaps: env_cubemap entities in
    // entity order; a generated default has none).
    std::vector<std::string> names;
    for (const entity_t &e : entities)
        if (e.classname_is("env_cubemap")) names.push_back(e.valueForKey("targetname"));
    names.resize(ApexLegends::Bsp::cubemaps.size());
    const auto volumeCubemap = Titanfall2::EnvmapVolumeLookup(names);
    for (std::size_t i = 0; i < ApexLegends::Bsp::meshes.size(); i++) {
        ApexLegends::Mesh_t &mesh = ApexLegends::Bsp::meshes[i];
        const uint16_t pool = mesh.unknown[2] & 0xFF;
        if (pool == 0 || pool == 3) continue;  // unlit pools keep 0xFF
        uint16_t index = 0xFF;
        const int volume = i < ApexLegends::Bsp::meshBounds.size() ? volumeCubemap(ApexLegends::Bsp::meshBounds[i].origin) : -1;
        if (volume >= 0) {
            index = static_cast<uint16_t>(volume);
        } else if (!ApexLegends::Bsp::cubemaps.empty() && i < ApexLegends::Bsp::meshBounds.size()) {
            const Vector3 centre = ApexLegends::Bsp::meshBounds[i].origin;
            float best = FLT_MAX;
            for (std::size_t c = 0; c < ApexLegends::Bsp::cubemaps.size() && c < 0xFF; c++) {
                const CubemapSample_t &cube = ApexLegends::Bsp::cubemaps[c];
                const Vector3 delta = centre - Vector3(cube.origin[0], cube.origin[1], cube.origin[2]);
                const float d = vector3_dot(delta, delta);
                if (d < best) { best = d; index = static_cast<uint16_t>(c); }
            }
        }
        mesh.unknown[2] = static_cast<uint16_t>(pool | (index << 8));
    }
}
