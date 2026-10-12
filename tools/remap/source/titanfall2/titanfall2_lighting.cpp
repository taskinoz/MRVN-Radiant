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
    their compiled world lights; see docs/RESPAWN_LIGHTING.md.
*/

#include "../remap.h"
#include "../bspfile_abstract.h"
#include <chrono>
#include <cstdio>

namespace {
using Respawn::Bake::V3;
using Respawn::Bake::Light;
using Respawn::Bake::LightType;

// Retail world-light flags: realtime lights with baked shadow masks, static lights and suns.
constexpr int32_t FlagRealtime = 28;
constexpr int32_t FlagStatic = 4;
constexpr int32_t FlagSun = 24;

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
    return colour * (brightness / 255.0);
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
};

std::vector<PendingLight> pendingLights;
int environments = 0;
}  // namespace


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
            const bool gameplay = environments++ == 0;
            PendingLight ambient;
            ambient.light.type = LightType::Ambient;
            ambient.light.origin = origin;
            if (ColourForKey(e, "_ambient", ambient.light.intensity)) {
                ambient.record = BaseRecord(ambient.light, 5);
                pendingLights.push_back(ambient);
                if (gameplay)
                    Titanfall2::Bsp::ambient = ambient.light.intensity;
            }

            PendingLight sun;
            sun.light.type = LightType::Sun;
            sun.light.origin = origin;
            sun.light.direction = DirectionForEntity(e, -90);
            if (!ColourForKey(e, "_light", sun.light.intensity))
                sun.light.intensity = {1, 1, 1};
            // Only the first environment is baked; later ones (e.g. the menu stage) need volumes.
            sun.light.realtime = gameplay;
            sun.record = BaseRecord(sun.light, 3);
            sun.record.normal = Vector3(sun.light.direction.x, sun.light.direction.y, sun.light.direction.z);
            sun.record.flags = FlagSun;
            pendingLights.push_back(sun);
            if (!gameplay)
                Sys_FPrintf(SYS_WRN, "WARNING: Only the first light_environment is baked; the one at %s is recorded but unbaked\n",
                            e.valueForKey("origin"));
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
        SetFalloff(e, light, pending.record, quakeBrightness);
        pending.record.flags = light.realtime ? FlagRealtime : FlagStatic;

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
    int hardware = 0;
    for (PendingLight &pending : pendingLights) {
        if (pending.light.type != LightType::Ambient)
            pending.light.hardwareIndex = hardware++;
        Titanfall2::Bsp::worldLights.push_back(pending.record);
        Titanfall2::Bsp::bakeLights.push_back(pending.light);
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
            translucent |= (flags & C_TRANSLUCENT) != 0;
            visible |= (flags & C_NODRAW) == 0;
        }
        if (!visible || sky || translucent)
            continue;
        Respawn::Bake::Brush &out = brushes.emplace_back();
        for (const side_t &side : brush.sides)
            out.planes.push_back({side.plane.normal().x(), side.plane.normal().y(), side.plane.normal().z(), side.plane.dist()});
        out.mins = {brush.minmax.mins.x(), brush.minmax.mins.y(), brush.minmax.mins.z()};
        out.maxs = {brush.minmax.maxs.x(), brush.minmax.maxs.y(), brush.minmax.maxs.z()};
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

    const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - started).count();
    Sys_Printf("%9zu world lights (%d hardware)\n", Titanfall2::Bsp::worldLights.size(), hardware);
    Sys_Printf("%9zu occluding brushes\n", occluders.size());
    Sys_Printf("%9zu lightmap pages, %zu charts\n", pages.size(), Titanfall::Bsp::lightmapCharts.size());
    Sys_Printf("%9zu lit texels, %zu with realtime lights, %zu RTL pages\n", result.chartedTexels,
               result.realtimeTexels, Titanfall2::Bsp::lightmapRtlPages.size());
    Sys_Printf("%9.1f seconds baking\n", seconds);
}
