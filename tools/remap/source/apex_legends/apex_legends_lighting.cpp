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

/*
    Light environments and their volumes, as retail S3 mp_rr_canyonlands_staging
    has them: light_environment "lightEnvironmentIndex" "*N" (entity order
    without the key); environment 0 owns everything outside any volume, and a
    light_environment_volume brush entity ("lightEnvironmentIndex" "*1") claims
    its region for that environment. World lights, shadow environments and CSM
    trees follow environment order.
*/
struct LightEnvironment {
    int index;
    const entity_t *entity;
};

std::vector<LightEnvironment> LightEnvironments() {
    std::vector<LightEnvironment> list;
    for (const entity_t &e : entities) {
        if (!striEqual(e.classname(), "light_environment")) continue;
        const char *value = e.valueForKey("lightEnvironmentIndex");
        list.push_back({value[0] == '*' ? atoi(value + 1) : static_cast<int>(list.size()), &e});
    }
    std::stable_sort(list.begin(), list.end(), [](const auto &a, const auto &b) { return a.index < b.index; });
    for (std::size_t slot = 0; slot < list.size(); slot++) {
        if (list[slot].index != static_cast<int>(slot))
            Sys_Warning("light_environment indices should run from *0 without gaps (found *%d at slot %zu)\n", list[slot].index, slot);
    }
    return list;
}

struct EnvironmentVolume {
    std::size_t slot;
    std::vector<std::vector<Plane3>> brushes;  // world space, inside when n.p <= d

    bool contains(const Vector3 &p) const {
        for (const auto &brush : brushes) {
            bool inside = !brush.empty();
            for (const Plane3 &plane : brush) {
                if (plane.a * p.x() + plane.b * p.y() + plane.c * p.z() > plane.d + 1e-3) { inside = false; break; }
            }
            if (inside) return true;
        }
        return false;
    }
};

std::vector<EnvironmentVolume> EnvironmentVolumes(const std::vector<LightEnvironment> &environments) {
    std::vector<EnvironmentVolume> volumes;
    for (const entity_t &e : entities) {
        if (!striEqual(e.classname(), "light_environment_volume")) continue;
        const char *value = e.valueForKey("lightEnvironmentIndex");
        const int index = value[0] == '*' ? atoi(value + 1) : 1;
        const auto found = std::find_if(environments.begin(), environments.end(),
                                        [&](const LightEnvironment &env) { return env.index == index; });
        if (found == environments.end()) {
            Sys_Warning("light_environment_volume at %s names light environment *%d, which does not exist\n", e.valueForKey("origin"), index);
            continue;
        }
        // Brushes are in world space here (the compiler later sets "origin" to
        // the model centre); decompiled "*trigger_brush" keys are relative to it.
        const Vector3 origin = e.vectorForKey("origin");
        EnvironmentVolume volume{static_cast<std::size_t>(found - environments.begin()), {}};
        for (const brush_t &brush : e.brushes) {
            std::vector<Plane3> planes;
            for (const side_t &side : brush.sides) {
                planes.push_back(side.plane);
            }
            volume.brushes.push_back(std::move(planes));
        }
        // Decompiled maps keep the volume as "*trigger_brush_B_plane_P" "nx ny nz d" keys.
        for (int b = 0; e.brushes.empty(); b++) {
            std::vector<Plane3> planes;
            for (int s = 0;; s++) {
                char key[64];
                snprintf(key, sizeof(key), "*trigger_brush_%d_plane_%d", b, s);
                const char *text = e.valueForKey(key);
                if (!text[0]) break;
                Plane3 plane{0, 0, 0, 0};
                sscanf(text, "%lf %lf %lf %lf", &plane.a, &plane.b, &plane.c, &plane.d);
                plane.d += plane.a * origin.x() + plane.b * origin.y() + plane.c * origin.z();
                planes.push_back(plane);
            }
            if (planes.empty()) break;
            volume.brushes.push_back(std::move(planes));
        }
        if (volume.brushes.empty())
            Sys_Warning("light_environment_volume at %s has no brushes\n", e.valueForKey("origin"));
        volumes.push_back(std::move(volume));
    }
    return volumes;
}

// Environment slot owning a shadow caster: the first volume holding its centre point, else 0.
std::size_t CasterEnvironment(const std::vector<EnvironmentVolume> &volumes, const Vector3 &centre) {
    for (const EnvironmentVolume &volume : volumes) {
        if (volume.contains(centre)) return volume.slot;
    }
    return 0;
}

// Per environment slot: [begin, end) of shadow meshes, CSM nodes and CSM references.
struct ShadowEnvironmentRange {
    uint32_t meshes[2], nodes[2], refs[2];
    Vector3 sun;
};
std::vector<ShadowEnvironmentRange> shadowEnvironmentRanges;

struct EnvironmentCache {
    bool ready = false;
    std::vector<LightEnvironment> environments;
    std::vector<EnvironmentVolume> volumes;
};
EnvironmentCache &Environments() {
    static EnvironmentCache cache;
    if (!cache.ready) {
        cache.environments = LightEnvironments();
        cache.volumes = EnvironmentVolumes(cache.environments);
        cache.ready = true;
    }
    return cache;
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

    for (const LightEnvironment &environment : Environments().environments) {
        const entity_t &e = *environment.entity;
        {
            WorldLight_t ambient = ZeroedRecord<WorldLight_t>();
            ambient.origin = e.vectorForKey("origin");
            ambient.intensity = LinearLightColour(e.valueForKey("_ambient"), 255.0f);
            ambient.type = emit_skyambient;
            ambients.push_back(ambient);

            WorldLight_t sun = ZeroedRecord<WorldLight_t>();
            sun.origin = ambient.origin;
            sun.intensity = LinearLightColour(e.valueForKey("_light"), 255.0f);
            sun.normal = LightDirection(e);
            sun.type = emit_skylight;
            sun.flags = 0x18;
            sun.sun_highlight_size_or_vfog_boost = FloatKey(e, "sun_highlight_size", 0.0f);
            suns.push_back(sun);
        }
    }

    for (const entity_t &e : entities) {
        const char *classname = e.classname();
        const bool spot = striEqual(classname, "light_spot") || striEqual(classname, "light_spotlight");
        if (!spot && !striEqual(classname, "light")) {
            continue;
        }

        WorldLight_t light = ZeroedRecord<WorldLight_t>();
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
    Light environment queries for the bakes: lightmaps, probes and cubemaps
    inside a light_environment_volume use that environment's sun and ambient,
    as its shadow environment does.
*/

std::size_t ApexLegends::LightEnvironmentCount() {
    return Environments().environments.size();
}

const entity_t *ApexLegends::LightEnvironmentEntity(std::size_t slot) {
    const auto &environments = Environments().environments;
    return slot < environments.size() ? environments[slot].entity : nullptr;
}

std::size_t ApexLegends::LightEnvironmentAt(const Vector3 &point) {
    const auto &volumes = Environments().volumes;
    return volumes.empty() ? 0 : CasterEnvironment(volumes, point);
}

const WorldLight_t *ApexLegends::EnvironmentWorldLight(std::size_t slot, int32_t type) {
    // EmitWorldLights writes every ambient, then every sun, in environment order.
    const WorldLight_t *first = nullptr;
    std::size_t seen = 0;
    for (const WorldLight_t &light : ApexLegends::Bsp::worldLights) {
        if (light.type != type) continue;
        if (!first) first = &light;
        if (seen++ == slot) return &light;
    }
    return first;
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
static void EmitCsmTree(const std::vector<std::pair<uint32_t, MinMax>> &casters, const Vector3 &sun, std::size_t &lastInternal) {
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
    for (const auto &[id, bounds] : casters) add(id, bounds);

    if (ids.empty()) {
        ApexLegends::Bsp::csmAABBNodes.push_back(ZeroedRecord<CSMAABBNode_t>());
        return;
    }
    const ApexLegends::ObjTreeNode root = ApexLegends::BuildObjTree(boxes);

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
    const std::size_t rootIndex = ApexLegends::Bsp::csmAABBNodes.size();
    ApexLegends::Bsp::csmAABBNodes.push_back(ZeroedRecord<CSMAABBNode_t>());
    emit(root, rootIndex);
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
    shadowEnvironmentRanges.clear();
    
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
    
    // Casters are grouped by light environment (retail Firing Range: shadow
    // meshes 0-5 for *0, 6-29 for *1), opaque then alpha within each. World
    // meshes span regions, so each triangle goes to the environment whose
    // volume holds its centroid and a mesh is split where it crosses one.
    const std::vector<LightEnvironment> &environments = Environments().environments;
    const std::vector<EnvironmentVolume> &volumes = Environments().volumes;
    const std::size_t slots = std::max<std::size_t>(environments.size(), 1);

    // Position (and texture UV) of the vertex at meshIndices[index].
    auto vertexOf = [](const ApexLegends::Mesh_t &mesh, uint32_t index, Vector2 *uv) -> Vector3 {
        const uint32_t base = mesh.materialOffset < ApexLegends::Bsp::materialSorts.size()
            ? ApexLegends::Bsp::materialSorts[mesh.materialOffset].vertexOffset : 0;
        const uint32_t v = base + ApexLegends::Bsp::meshIndices[index];
        uint32_t position = UINT32_MAX;
        Vector2 coord(0, 0);
        auto take = [&](const auto &vertices) {
            if (v < vertices.size()) { position = vertices[v].vertexIndex; coord = vertices[v].uv0; }
        };
        switch (mesh.flags & 0x600) {  // S_VERTEX_LIT_FLAT 0x000, LIT_BUMP 0x200, UNLIT 0x400, UNLIT_TS 0x600
            case 0x200: take(ApexLegends::Bsp::vertexLitBumpVertices); break;
            case 0x400: take(ApexLegends::Bsp::vertexUnlitVertices); break;
            case 0x600: take(ApexLegends::Bsp::vertexUnlitTSVertices); break;
            default:    take(ApexLegends::Bsp::vertexLitFlatVertices); break;
        }
        if (uv) *uv = coord;
        return position < Titanfall::Bsp::vertices.size() ? Titanfall::Bsp::vertices[position] : Vector3(0, 0, 0);
    };
    auto triangleComplete = [](const ApexLegends::Mesh_t &mesh, uint32_t t) {
        return mesh.triOffset + t * 3 + 2 < ApexLegends::Bsp::meshIndices.size();
    };

    std::vector<int32_t> opaqueMeshes;
    std::map<uint16_t, std::vector<int32_t>> alphaBySort;
    std::unordered_map<int32_t, std::vector<uint16_t>> triangleEnvironments;
    for (int32_t meshIdx = worldModel.meshIndex; meshIdx < worldModel.meshIndex + worldModel.meshCount; meshIdx++) {
        if (meshIdx < 0 || meshIdx >= static_cast<int32_t>(ApexLegends::Bsp::meshes.size())) continue;
        const ApexLegends::Mesh_t &mesh = ApexLegends::Bsp::meshes[meshIdx];
        if (mesh.triCount == 0) continue;
        const int sharedIdx = meshIdx - worldModel.meshIndex;
        const bool known = sharedIdx >= 0 && sharedIdx < static_cast<int>(Shared::meshes.size());
        const uint32_t flags = known ? Shared::meshes[sharedIdx].shaderInfo->compileFlags : 0;
        if (flags & C_SKY) continue;
        // Alpha-tested casters ("$compileflag alphashadow") go to the alpha stream.
        if (flags & C_ALPHASHADOW) alphaBySort[static_cast<uint16_t>(mesh.materialOffset)].push_back(meshIdx);
        else opaqueMeshes.push_back(meshIdx);
        if (!volumes.empty()) {
            std::vector<uint16_t> &owners = triangleEnvironments[meshIdx];
            for (uint32_t t = 0; t < mesh.triCount && triangleComplete(mesh, t); t++) {
                const uint32_t first = mesh.triOffset + t * 3;
                const Vector3 centroid = (vertexOf(mesh, first, nullptr) + vertexOf(mesh, first + 1, nullptr)
                                          + vertexOf(mesh, first + 2, nullptr)) * (1.0f / 3.0f);
                owners.push_back(static_cast<uint16_t>(CasterEnvironment(volumes, centroid)));
            }
        }
    }
    auto triangleEnvironment = [&](int32_t meshIdx, uint32_t t) -> std::size_t {
        if (volumes.empty()) return 0;
        const std::vector<uint16_t> &owners = triangleEnvironments[meshIdx];
        return t < owners.size() ? owners[t] : 0;
    };

    shadowEnvironmentRanges.assign(slots, {});
    for (std::size_t slot = 0; slot < slots; slot++) {
        shadowEnvironmentRanges[slot].meshes[0] = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshes.size());
        shadowEnvironmentRanges[slot].sun = slot < environments.size() ? LightDirection(*environments[slot].entity)
                                                                         : Vector3(0.5227f, 0.2733f, -0.8072f);

        // Opaque: one shadow mesh per world mesh (drawType 1, no material),
        // positions in 0x7C with mesh-local uint16 indices in 0x7E.
        for (int32_t meshIdx : opaqueMeshes) {
            const ApexLegends::Mesh_t &mesh = ApexLegends::Bsp::meshes[meshIdx];
            const uint32_t firstShadowVert = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size());
            std::unordered_map<uint16_t, uint16_t> vertexRemap;
            MinMax shadowBounds;
            uint32_t shadowTriCount = 0;
            for (uint32_t t = 0; t < mesh.triCount && triangleComplete(mesh, t); t++) {
                if (triangleEnvironment(meshIdx, t) != slot) continue;
                for (int k = 0; k < 3; k++) {
                    const uint32_t index = mesh.triOffset + t * 3 + k;
                    const uint16_t origIdx = ApexLegends::Bsp::meshIndices[index];
                    auto it = vertexRemap.find(origIdx);
                    if (it == vertexRemap.end()) {
                        const Vector3 pos = vertexOf(mesh, index, nullptr);
                        it = vertexRemap.emplace(origIdx, static_cast<uint16_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size() - firstShadowVert)).first;
                        worldBounds.extend(pos);
                        shadowBounds.extend(pos);
                        ApexLegends::Bsp::shadowMeshOpaqueVerts.push_back(pos);
                    }
                    ApexLegends::Bsp::shadowMeshIndices.push_back(it->second);
                }
                shadowTriCount++;
            }
            if (shadowTriCount > 0) {
                ShadowMesh_t shadowMesh = ZeroedRecord<ShadowMesh_t>();
                shadowMesh.firstVertex = firstShadowVert;
                shadowMesh.triangleCount = shadowTriCount;
                shadowMesh.drawType = 1;  // Opaque
                shadowMesh.materialSortIdx = 0xFFFF;  // No material
                ApexLegends::Bsp::shadowMeshes.push_back(shadowMesh);
                shadowMeshBounds.push_back(shadowBounds);
                totalTriangles += shadowTriCount;
            }
        }

        // Alpha-tested, as retail S3 writes them (World's Edge: 8 of 137 shadow
        // meshes): after the opaque meshes, one per material sort, drawType 0
        // with that sort's index, vertices in 0x7D as position + texture UV
        // (float32), indices continuing the shared 0x7E stream.
        for (const auto &[sort, meshList] : alphaBySort) {
            ShadowMesh_t *alpha = nullptr;
            MinMax alphaBounds;
            std::map<std::array<float, 5>, uint16_t> lookup;
            auto finish = [&]() {
                if (alpha) shadowMeshBounds.push_back(alphaBounds);
                alpha = nullptr; alphaBounds = MinMax(); lookup.clear();
            };
            for (int32_t meshIdx : meshList) {
                const ApexLegends::Mesh_t &mesh = ApexLegends::Bsp::meshes[meshIdx];
                for (uint32_t t = 0; t < mesh.triCount && triangleComplete(mesh, t); t++) {
                    if (triangleEnvironment(meshIdx, t) != slot) continue;
                    if (!alpha || lookup.size() + 3 > 65535) {
                        finish();
                        ShadowMesh_t entry = ZeroedRecord<ShadowMesh_t>();
                        entry.firstVertex = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshAlphaVerts.size());
                        entry.drawType = 0;
                        entry.materialSortIdx = sort;
                        ApexLegends::Bsp::shadowMeshes.push_back(entry);
                        alpha = &ApexLegends::Bsp::shadowMeshes.back();
                    }
                    for (int k = 0; k < 3; k++) {
                        Vector2 uv(0, 0);
                        const Vector3 pos = vertexOf(mesh, mesh.triOffset + t * 3 + k, &uv);
                        const std::array<float, 5> key{pos.x(), pos.y(), pos.z(), uv.x(), uv.y()};
                        auto found = lookup.find(key);
                        if (found == lookup.end()) {
                            found = lookup.emplace(key, static_cast<uint16_t>(ApexLegends::Bsp::shadowMeshAlphaVerts.size() - alpha->firstVertex)).first;
                            ShadowMeshAlphaVertex_t vertex = ZeroedRecord<ShadowMeshAlphaVertex_t>();
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
        shadowEnvironmentRanges[slot].meshes[1] = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshes.size());
    }


    totalVertices = static_cast<uint32_t>(ApexLegends::Bsp::shadowMeshOpaqueVerts.size());

    // One CSM tree per environment with absolute node and reference indices
    // (retail Firing Range: *1's root is node 9, its references start at 7);
    // 0x26 holds subtree totals up to the last internal node of all trees.
    const uint32_t propBase = ApexLegends::Bsp::levelInfo.empty() ? 0 : static_cast<uint32_t>(ApexLegends::Bsp::levelInfo[0].unk3);
    std::size_t lastInternal = 0;
    for (std::size_t slot = 0; slot < slots; slot++) {
        ShadowEnvironmentRange &range = shadowEnvironmentRanges[slot];
        std::vector<std::pair<uint32_t, MinMax>> casters;
        for (uint32_t m = range.meshes[0]; m < range.meshes[1]; m++) casters.emplace_back(m, shadowMeshBounds[m]);
        for (const auto &[propIndex, bounds] : ApexLegends::Bsp::staticPropShadowBounds) {
            const std::size_t owner = volumes.empty() || !bounds.valid() ? 0 : CasterEnvironment(volumes, (bounds.mins + bounds.maxs) * 0.5f);
            if (owner == slot) casters.emplace_back(propBase + propIndex, bounds);
        }
        range.nodes[0] = static_cast<uint32_t>(ApexLegends::Bsp::csmAABBNodes.size());
        range.refs[0] = static_cast<uint32_t>(ApexLegends::Bsp::csmObjRefsTotal.size());
        EmitCsmTree(casters, range.sun, lastInternal);
        range.nodes[1] = static_cast<uint32_t>(ApexLegends::Bsp::csmAABBNodes.size());
        range.refs[1] = static_cast<uint32_t>(ApexLegends::Bsp::csmObjRefsTotal.size());
    }
    ApexLegends::Bsp::csmNumObjRefsTotalForAabb.resize(lastInternal + 1);

    Sys_Printf("  %zu shadow meshes (%u tris, %u verts, %zu CSM nodes, %zu CSM refs)\n",
        ApexLegends::Bsp::shadowMeshes.size(), totalTriangles, totalVertices,
        ApexLegends::Bsp::csmAABBNodes.size(), ApexLegends::Bsp::csmObjRefsTotal.size());
}

/*
    EmitShadowEnvironments
    Lump 0x05: one record per light environment, in lightEnvironmentIndex
    order, with the [begin, end) ranges of CSM nodes, CSM references and
    shadow meshes that EmitShadowMeshes() grouped for it, and its sun
    direction (the direction light travels). A map without a
    light_environment gets one default environment.
*/
void ApexLegends::EmitShadowEnvironments() {
    Sys_FPrintf(SYS_VRB, "--- EmitShadowEnvironments ---\n");
    ApexLegends::Bsp::shadowEnvironments.clear();
    if (shadowEnvironmentRanges.empty()) {
        // EmitShadowMeshes() found no models; keep one environment over nothing.
        shadowEnvironmentRanges.push_back({{0, 0}, {0, 0}, {0, 0}, Vector3(0.5227f, 0.2733f, -0.8072f)});
    }
    if (Environments().environments.empty())
        Sys_Printf("  No light_environment found, creating default shadow environment\n");
    for (const ShadowEnvironmentRange &range : shadowEnvironmentRanges) {
        ShadowEnvironment_t env = ZeroedRecord<ShadowEnvironment_t>();
        env.beginAabbs = range.nodes[0];
        env.beginObjRefs = range.refs[0];
        env.beginShadowMeshes = range.meshes[0];
        env.endAabbs = range.nodes[1];
        env.endObjRefs = range.refs[1];
        env.endShadowMeshes = range.meshes[1];
        env.shadowDir = range.sun;
        ApexLegends::Bsp::shadowEnvironments.push_back(env);
        Sys_FPrintf(SYS_VRB, "  environment %zu: %u shadow meshes, %u CSM nodes, %u CSM references\n",
                    ApexLegends::Bsp::shadowEnvironments.size() - 1, range.meshes[1] - range.meshes[0],
                    range.nodes[1] - range.nodes[0], range.refs[1] - range.refs[0]);
    }
    Sys_Printf("  %zu shadow environments\n",ApexLegends::Bsp::shadowEnvironments.size());
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
