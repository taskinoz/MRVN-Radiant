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

/*
    EmitCubemaps
    Emits cubemap sample positions from env_cubemap entities
    
    The engine uses these positions to capture environment reflections at runtime
    via the buildcubemaps command. Each cubemap sample has:
    - origin: Position where the cubemap will be captured (stored as int32 in lump)
    - guid: Asset GUID for pre-baked cubemaps (0 = runtime capture required)
    
    Lumps:
    - 0x2A (CUBEMAPS): Array of CubemapSample_t (16 bytes each)
    - 0x2B (CUBEMAPS_AMBIENT_RCP): Array of floats, one per cubemap (reciprocal of ambient)
    
    If no env_cubemap entities exist, creates a single default at world center
*/
void ApexLegends::EmitCubemaps() {
    Sys_FPrintf(SYS_VRB, "--- EmitCubemaps ---\n");
    
    ApexLegends::Bsp::cubemaps.clear();
    
    // Lump 0x2A stores cubemap samples — one per VTF frame in the
    // pakfile cubemap atlas.  Multiple envmap_volume entities can
    // share the same cubemapID index into this table.
    // The default VTF has 25 frames, so we emit 25 samples.
    constexpr int VTF_FRAME_COUNT = 25;
    
    // Calculate world center for sample positions
    MinMax worldBounds;
    for (const Shared::Mesh_t &mesh : Shared::meshes) {
        worldBounds.extend(mesh.minmax.mins);
        worldBounds.extend(mesh.minmax.maxs);
    }
    Vector3 center = worldBounds.valid()
        ? (worldBounds.mins + worldBounds.maxs) * 0.5f
        : Vector3(0, 0, 0);
    
    for (int i = 0; i < VTF_FRAME_COUNT; i++) {
        CubemapSample_t sample;
        sample.origin[0] = static_cast<int32_t>(center[0]);
        sample.origin[1] = static_cast<int32_t>(center[1]);
        sample.origin[2] = static_cast<int32_t>(center[2]);
        sample.guid = 0;
        ApexLegends::Bsp::cubemaps.push_back(sample);
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
        light.style = e.intForKey("style");
        light.normal = spot ? LightDirection(e) : Vector3(1.0f, 0.0f, 0.0f);

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
        
        // Skip sky meshes
        int sharedIdx = meshIdx - worldModel.meshIndex;
        if (sharedIdx >= 0 && sharedIdx < static_cast<int>(Shared::meshes.size())
            && (Shared::meshes[sharedIdx].shaderInfo->compileFlags & C_SKY)) {
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
            totalTriangles += shadowTriCount;
        }
    }
    
    totalVertices = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size());
    
    // Create CSM object references - one reference per shadow mesh
    // The CSM system uses this to know which meshes to render for shadows
    for (uint32_t i = 0; i < ApexLegends::Bsp::shadowMeshes.size(); i++) {
        ApexLegends::Bsp::csmObjRefsTotal.push_back(i);
    }

    // Force large bounds to disable culling for debugging
    Vector3 largeMin(-50000.0f, -50000.0f, -50000.0f);
    Vector3 largeMax(50000.0f, 50000.0f, 50000.0f);
    
    // Create a single root CSM AABB node that encompasses all geometry
    if (!ApexLegends::Bsp::shadowMeshOpaqueVerts.empty()) {
        // Create root node with world bounds
        CSMAABBNode_t rootNode = {};

        //TODO: Use actual world bounds once CSM culling is verified working
        rootNode.mins = largeMin; //worldBounds.mins;
        rootNode.maxs = largeMax; //worldBounds.maxs;
        
        // CSM AABB node format (based on engine decompilation):
        // child0 (offset 0x0C):
        //   - Bits 0-7: Number of child nodes (0 for leaf)
        //   - Bits 8-31: First child node index
        // child1 (offset 0x1C):
        //   - Bits 0-7: Object ref count (for leaf nodes when child0 low byte is 0)
        //   - Bits 8-30: First obj ref index
        //
        // For a leaf node: child0 = 0, child1 = (startIndex << 8) | count
        
        uint32_t objRefCount = static_cast<uint32_t>(ApexLegends::Bsp::csmObjRefsTotal.size());
        uint32_t startIndex = 0;
        
        rootNode.child0 = 0;  // 0 children (leaf node)
        rootNode.child1 = (startIndex << 8) | (objRefCount & 0xFF);  // start index in high bits, count in low byte
        
        ApexLegends::Bsp::csmAABBNodes.push_back(rootNode);
        
        // numObjRefsTotalForAabb is used for internal nodes (when child0 low byte > 0)
        // For leaf nodes the count comes from child1's low byte, but we still need
        // an entry in this array for each node
        ApexLegends::Bsp::csmNumObjRefsTotalForAabb.push_back(objRefCount);
    }
    
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
    for (std::size_t i = 0; i < ApexLegends::Bsp::meshes.size(); i++) {
        ApexLegends::Mesh_t &mesh = ApexLegends::Bsp::meshes[i];
        const uint16_t pool = mesh.unknown[2] & 0xFF;
        if (pool == 0 || pool == 3) continue;  // unlit pools keep 0xFF
        uint16_t index = 0xFF;
        if (!ApexLegends::Bsp::cubemaps.empty() && i < ApexLegends::Bsp::meshBounds.size()) {
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
