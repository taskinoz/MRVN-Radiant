/* -------------------------------------------------------------------------------

   Copyright (C) 2022-2023 MRVN-Radiant and contributors.
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

#include "../remap.h"
#include "../model.h"
#include "../bspfile_abstract.h"
#include "titanfall2.h"
#include <cmath>

/*
    SetUpGameLump()
*/
void Titanfall2::SetUpGameLump() {
    Titanfall2::Bsp::gameLumpHeader.version = 1;
    memcpy( &Titanfall2::Bsp::gameLumpHeader.ident, "prps", 4 );
    Titanfall2::Bsp::gameLumpHeader.gameConst = 851968;
}

/*
    EmitStaticProp()
    Emits a static prop
*/
void Titanfall2::EmitStaticProp(entity_t &e) {
    const char *model = e.valueForKey("model");
    int pathIdx = -1;
    MinMax minmax;
    if (std::strlen(model) >= 128)
        Error("Static prop model path exceeds the 127-byte sprp name limit");

    std::vector<const AssMeshWalker*> meshes = LoadModelWalker( model, 0 );
    // Game-only models (e.g. skybox vistas) need no editor copy: bound them by
    // "_cullradius" around the origin instead.
    const float cullRadius = e.floatForKey("_cullradius");
    if(meshes.empty() && cullRadius <= 0.0f) {
        Sys_Warning("Failed to load model: %s\n", model);
        return;
    }

    Sys_Printf("Emitting static prop: %s\n", model);

    for(std::size_t i = 0; i < Titanfall::Bsp::gameLumpPaths.size(); i++) {
        Titanfall::GameLumpPath_t &path = Titanfall::Bsp::gameLumpPaths.at(i);

        if(!string_compare_nocase(path.path, model)) {
            pathIdx = i;
            break;
        }
    }

    if(pathIdx == -1) {
        if (Titanfall::Bsp::gameLumpPaths.size() > 65535)
            Error("Static prop model index exceeds the unsigned 16-bit sprp field");
        Titanfall2::Bsp::gameLumpPathHeader.numPaths++;
        Titanfall::GameLumpPath_t &path = Titanfall::Bsp::gameLumpPaths.emplace_back();
        strncpy(path.path, model, 127);
        pathIdx = Titanfall::Bsp::gameLumpPaths.size() - 1;
    }

    Titanfall2::Bsp::gameLumpPropHeader.numProps++;
    Titanfall2::Bsp::gameLumpPropHeader.unk0++;
    Titanfall2::Bsp::gameLumpPropHeader.unk1++;
    Titanfall2::GameLumpProp_t &prop = Titanfall2::Bsp::gameLumpProps.emplace_back();
    Vector3 origin;
    Vector3 angles(0);
    if(!e.read_keyvalue(origin, "origin")) {
        origin.x() = 0.0f;
        origin.y() = 0.0f;
        origin.z() = 0.0f;
    }
    if(!e.read_keyvalue(angles, "angles") && !e.read_keyvalue(angles.y(), "angle")) {
        angles.x() = 0.0f;
        angles.y() = 0.0f;
        angles.z() = 0.0f;
    }

    prop.origin = origin;
    prop.angles = angles;
    for (int axis = 0; axis < 3; ++axis)
        if (!std::isfinite(origin[axis]) || !std::isfinite(angles[axis]))
            Error("Static prop origin and angles must be finite");
    float scale = 1.0f;
    e.read_keyvalue(scale, "modelscale");
    Vector3 vectorScale;
    if (e.read_keyvalue(vectorScale, "modelscale_vec")) {
        if (vectorScale.x() != vectorScale.y() || vectorScale.x() != vectorScale.z())
            Error("TF2 sprp v13 stores only a uniform model scale");
        scale = vectorScale.x();
    }
    if (!std::isfinite(scale) || scale == 0.0f)
        Error("Static prop model scale must be finite and nonzero");
    prop.scale = scale;
    prop.modelName = pathIdx;
    prop.solid = 6;
    prop.flags = 84;
    if (e.valueForKey("solid")[0])
        prop.solid = e.intForKey("solid");
    if (e.valueForKey("flags")[0])
        prop.flags = e.intForKey("flags");
    const int skin = e.intForKey("skin");
    if (skin < 0 || skin > 65535)
        Error("Static prop skin exceeds its unsigned 16-bit sprp field");
    prop.skin = skin;
    prop.envCubemap = 0xffff;
    prop.fade_scale = -1.0f;
    prop.cpu_level[0] = -1.0f;
    prop.cpu_level[1] = -1.0f;
    prop.gpu_level[0] = -1.0f;
    prop.gpu_level[1] = -1.0f;
    prop.unk.x() = 1.0f;
    prop.unk.y() = 0.0f;
    prop.unk.z() = 0.0f;
    std::fill(std::begin(prop.diffuse_modulation), std::end(prop.diffuse_modulation), 255);
    if (e.valueForKey("_remap_prop_fade_scale")[0]) {
        prop.fade_scale = e.floatForKey("_remap_prop_fade_scale");
        if (!std::isfinite(prop.fade_scale)) Error("Nonfinite recovered prop fade scale");
    }
    auto unsignedField = [&](const char *name, uint16_t &field) {
        if (!e.valueForKey(name)[0]) return;
        const int value = e.intForKey(name);
        if (value < 0 || value > 65535) Error("Recovered prop field exceeds 16 bits: %s", name);
        field = value;
    };
    unsignedField("_remap_prop_cubemap", prop.envCubemap);
    int channels[4];
    if (e.valueForKey("_remap_prop_rgba")[0]) {
        if (sscanf(e.valueForKey("_remap_prop_rgba"), "%d %d %d %d", &channels[0], &channels[1], &channels[2], &channels[3]) != 4)
            Error("Malformed recovered prop RGBA");
        for (int i = 0; i < 4; ++i) {
            if (channels[i] < 0 || channels[i] > 255) Error("Recovered prop RGBA exceeds byte range");
            prop.diffuse_modulation[i] = channels[i];
        }
    }
    if (e.valueForKey("_remap_prop_levels")[0]) {
        if (sscanf(e.valueForKey("_remap_prop_levels"), "%d %d %d %d", &channels[0], &channels[1], &channels[2], &channels[3]) != 4)
            Error("Malformed recovered prop CPU/GPU levels");
        for (int i = 0; i < 4; ++i) if (channels[i] < -128 || channels[i] > 127) Error("Recovered prop level exceeds signed byte range");
        prop.cpu_level[0] = channels[0]; prop.cpu_level[1] = channels[1];
        prop.gpu_level[0] = channels[2]; prop.gpu_level[1] = channels[3];
    }
    unsignedField("_remap_prop_collision_add", prop.collision_flags[0]);
    unsignedField("_remap_prop_collision_remove", prop.collision_flags[1]);
    if (prop.flags & 2) {
        e.read_keyvalue(prop.unk, "_remap_prop_lighting_origin");
        for (int axis = 0; axis < 3; ++axis) if (!std::isfinite(prop.unk[axis])) Error("Nonfinite enabled prop lighting origin");
    }

    if (meshes.empty()) {
        minmax.extend(origin - Vector3(cullRadius, cullRadius, cullRadius));
        minmax.extend(origin + Vector3(cullRadius, cullRadius, cullRadius));
    }
    // Use the same pitch/yaw/roll conversion as the existing model compiler.
    // Visibility must enclose the rotated, scaled placement, not its untransformed mesh.
    Matrix4 transform(g_matrix4_identity);
    matrix4_transform_by_euler_xyz_degrees(transform, origin, angles_pyr2rpy(angles), Vector3(scale));
    for ( const auto mesh : meshes )
    {
        mesh->forEachFace( [&minmax, &transform]( const Vector3 ( &xyz )[3], const Vector2 ( &st )[3] ){
            minmax.extend(matrix4_transformed_point(transform, xyz[0]));
            minmax.extend(matrix4_transformed_point(transform, xyz[1]));
            minmax.extend(matrix4_transformed_point(transform, xyz[2]));
		} );
    }

    Shared::visRef_t &ref = Shared::visRefs.emplace_back();

    ref.minmax = minmax;
    // TF2's object namespace reserves whole 64-entry blocks for non-sky world
    // meshes. Sky/submodel meshes do not occupy object-reference slots. Using
    // meshCount here made mp_box resolve props as invalid render instances.
    const uint32_t propBase = (Titanfall::Bsp::levelInfo.at(0).firstSkyMeshIndex + 63u) & ~63u;
    const std::size_t object = propBase + Titanfall2::Bsp::gameLumpProps.size() - 1;
    if (object > 65535) Error("TF2 static prop object reference exceeds 16 bits");
    ref.index = object;
}

/*
    EmitLevelInfo()
*/
void Titanfall2::EmitLevelInfo() {
    Titanfall::LevelInfo_t &li = Titanfall::Bsp::levelInfo.back();

    li.propCount = Titanfall2::Bsp::gameLumpPropHeader.numProps;
    // TODO: unk2 sun vector from last light_environment
    li.unk2 = { 0.1, 0.8, -0.6 };  // placeholder
}
