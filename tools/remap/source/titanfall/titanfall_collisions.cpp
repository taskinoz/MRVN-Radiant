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
#include "../bspfile_abstract.h"
#include "titanfall.h"
#include "../respawn/encoding.h"
#include <algorithm>
#include <tuple>

namespace {
struct PatchCollision {
    MinMax bounds;
    uint16_t header;
    int contents;
    bool modelOnly;
};

// A cell's primitives, emitted as geo sets of up to GroupSize nearby primitives.
// Retail geo sets with more than one primitive store the index of their first
// entry in CM_PRIMITIVES (0x59), with per-primitive bounds in 0x5A.
struct PendingPrimitive { MinMax bounds; int index; int contents; uint8_t type; };
constexpr std::size_t GroupSize = 8;

Titanfall::CMBound_t EncodeBounds(const MinMax &minmax) {
    Titanfall::CMBound_t bound{};
    bound.unknown1 = 128;
    try {
        for (int axis = 0; axis < 3; ++axis) {
            const auto encoded = Respawn::quantizeBoundsAxis(minmax.mins[axis], minmax.maxs[axis]);
            bound.origin[axis] = encoded.origin;
            bound.extents[axis] = encoded.extent;
        }
    } catch (const std::exception &error) {
        Error("%s", error.what());
    }
    return bound;
}

// Each patch becomes triangle-collision headers of at most MaxTriangles. Headers
// of 1-3 triangles use the loader's node-free path; larger ones carry
// 4 * ((n + 3) / 6) nodes, each holding the header's packed bounds, with
// per-triangle lowest/highest-Z vertex flags. This follows apex-to-titanfall-2's
// native_triangle_collision.py, which verified the flags against all 662,080
// Homestead triangles and tested the node layout in game. Triangles keep their own
// three vertices so the 10-bit base and 7-bit deltas stay in range.
constexpr std::size_t MaxTriangles = 300;

uint32_t TriangleFlags(const std::array<Vector3, 3> &v) {
    int low = 0, high = 0;
    for (int k = 1; k < 3; ++k) {
        if (v[k].z() < v[low].z()) low = k;
        if (v[k].z() > v[high].z()) high = k;
    }
    const int options[2] = {1 & ~low, 2 & ~low};
    if (low == high) high = options[0];
    const int which = options[0] == high ? 0 : 1;
    return uint32_t((low | (which << 2)) << 4);
}

void EmitTricollHeader(const shaderInfo_t &shader, int contents, bool modelOnly,
                       const std::vector<std::array<Vector3, 3>> &triangles, std::vector<PatchCollision> &result) {
    if (Titanfall::Bsp::tricollHeaders.size() > 65535)
        Error("Tricoll header index exceeds its collision primitive field");
    PatchCollision out;
    for (const auto &tri : triangles)
        for (const Vector3 &point : tri) {
            for (int axis = 0; axis < 3; ++axis)
                if (!std::isfinite(point[axis])) Error("Nonfinite patch collision vertex");
            out.bounds.extend(point);
        }
    out.header = Titanfall::Bsp::tricollHeaders.size();
    out.contents = contents;
    out.modelOnly = modelOnly;
    const uint32_t texture = Titanfall::EmitTextureData(shader);
    if (texture > 32767) Error("Tricoll texture index exceeds its signed 16-bit field");
    Titanfall::TricollHeader_t header{};
    header.texdata = texture;
    header.texinfoFlags = static_cast<int16_t>(shader.surfaceFlags & 0xffff);
    header.numVerts = static_cast<int16_t>(triangles.size() * 3);
    header.numTris = static_cast<int16_t>(triangles.size());
    header.firstVert = Titanfall::Bsp::vertices.size();
    header.firstTri = Titanfall::Bsp::tricollTriangles.size();
    header.firstNode = Titanfall::Bsp::tricollNodes.size();
    header.org = Vector3(0);
    header.scale = 1;
    for (std::size_t i = 0; i < triangles.size(); ++i) {
        Titanfall::Bsp::vertices.insert(Titanfall::Bsp::vertices.end(), triangles[i].begin(), triangles[i].end());
        Titanfall::TricollTriangle_t word{};
        word.idx0 = static_cast<uint32_t>(i * 3);
        word.idx1 = 1;
        word.idx2 = 2;
        word.unk = TriangleFlags(triangles[i]);
        Titanfall::Bsp::tricollTriangles.push_back(word);
        Titanfall::Bsp::tricollBevelStarts.push_back(0);
    }
    const std::size_t nodes = triangles.size() <= 3 ? 0 : 4 * ((triangles.size() + 3) / 6);
    if (nodes) {
        const Titanfall::CMBound_t box = EncodeBounds(out.bounds);
        Titanfall::Bsp::tricollNodes.insert(Titanfall::Bsp::tricollNodes.end(), nodes, box);
    }
    Titanfall::Bsp::tricollHeaders.push_back(header);
    result.push_back(out);
}

std::vector<PatchCollision> EmitPatchCollision(const entity_t &entity) {
    std::vector<PatchCollision> result;
    if (g_game->bspVersion != 37 && g_game->bspVersion != 29) return result;  // TF2 and TF1: same tricoll layouts
    for (const parseMesh_t *patch = entity.patches; patch; patch = patch->next) {
        const shaderInfo_t &shader = *patch->shaderInfo;
        int contents = shader.contentFlags;
        const std::string key = "_remap_contents_" + std::to_string(patch->brushNum);
        const char *overrideValue = entity.valueForKey(key.c_str());
        if (overrideValue[0]) {
            char *end = nullptr;
            const auto value = std::strtoull(overrideValue, &end, 10);
            if (*end || value > 0xffffffffull) Error("Invalid recovered triangle contents");
            contents = static_cast<int>(value);
        }
        // Respawn shaders encode solidity in contentFlags, unlike Q3's C_SOLID.
        if (!contents || ((shader.compileFlags & C_SKY) && !overrideValue[0])) continue;
        const bool modelOnly = (shader.compileFlags & C_SKY) != 0;
        const mesh_t &mesh = patch->mesh;
        std::vector<std::array<Vector3, 3>> triangles;
        for (int y = 0; y + 1 < mesh.height; ++y) for (int x = 0; x + 1 < mesh.width; ++x) {
            const int first = x + y * mesh.width;
            const Vector3 points[] = {mesh.verts[first].xyz, mesh.verts[first + mesh.width].xyz,
                                      mesh.verts[first + mesh.width + 1].xyz, mesh.verts[first + 1].xyz};
            for (const auto &tri : {std::array<unsigned, 3>{0, 1, 2}, std::array<unsigned, 3>{0, 2, 3}}) {
                if (vector3_length(vector3_cross(points[tri[1]] - points[tri[0]], points[tri[2]] - points[tri[0]])) > 1e-6)
                    triangles.push_back({points[tri[0]], points[tri[1]], points[tri[2]]});
                if (triangles.size() == MaxTriangles) {
                    EmitTricollHeader(shader, contents, modelOnly, triangles, result);
                    triangles.clear();
                }
            }
        }
        if (!triangles.empty())
            EmitTricollHeader(shader, contents, modelOnly, triangles, result);
    }
    return result;
}

// Geo sets for primitive groups. A group of one primitive is stored inline in its
// geo set; a larger group is one CM_PRIMITIVES range, and its geo set word is
// (first << 8) | contents, as in retail, where every primitive in a set shares
// the set's contents. Groups are built once, so primitives are not duplicated.
struct PrimitiveGroup { MinMax bounds; std::vector<PendingPrimitive> members; uint32_t first = 0; };

std::vector<PrimitiveGroup> GroupPrimitives(std::vector<PendingPrimitive> primitives, float cellSize) {
    const auto key = [cellSize](const PendingPrimitive &p) {
        const Vector3 c = (p.bounds.mins + p.bounds.maxs) * 0.5f;
        return std::make_tuple(p.contents, (int64_t)floor(c.x() / cellSize), (int64_t)floor(c.y() / cellSize), c.z());
    };
    std::sort(primitives.begin(), primitives.end(), [&](const PendingPrimitive &a, const PendingPrimitive &b) { return key(a) < key(b); });
    std::vector<PrimitiveGroup> groups;
    for (std::size_t i = 0; i < primitives.size(); ++i) {
        const auto k = key(primitives[i]);
        if (groups.empty() || groups.back().members.size() == GroupSize ||
            std::get<0>(key(groups.back().members.front())) != std::get<0>(k) ||
            std::get<1>(key(groups.back().members.front())) != std::get<1>(k) ||
            std::get<2>(key(groups.back().members.front())) != std::get<2>(k))
            groups.emplace_back();
        PrimitiveGroup &group = groups.back();
        group.members.push_back(primitives[i]);
        group.bounds.extend(primitives[i].bounds.mins);
        group.bounds.extend(primitives[i].bounds.maxs);
    }
    return groups;
}

// Writes each multi-primitive group's CM_PRIMITIVES range.
void AllocateGroups(std::vector<PrimitiveGroup> &groups) {
    for (PrimitiveGroup &group : groups) {
        if (group.members.size() == 1) continue;
        group.first = static_cast<uint32_t>(Titanfall::Bsp::cmPrimitives.size());
        if (group.first + group.members.size() > 65536)
            Error("Collision primitive index exceeds 16 bits");
        for (const PendingPrimitive &p : group.members) {
            if (p.index < 0 || p.index > 65535) Error("Collision shape index exceeds 16 bits");
            Titanfall::CMPrimitive_t &primitive = Titanfall::Bsp::cmPrimitives.emplace_back();
            primitive.uniqueContentsIndex = Titanfall::EmitUniqueContents(p.contents);
            primitive.collisionShapeIndex = p.index;
            primitive.collisionShapeType = p.type;
            Titanfall::Bsp::cmPrimitiveBounds.push_back(EncodeBounds(p.bounds));
        }
    }
}

void EmitGroupGeoSet(const PrimitiveGroup &group) {
    if (group.members.size() == 1) {
        const PendingPrimitive &only = group.members.front();
        Titanfall::EmitGeoSet(only.bounds, only.index, only.contents);
        Titanfall::Bsp::cmGeoSets.back().collisionShapeType = only.type;
        return;
    }
    Titanfall::CMGeoSet_t &set = Titanfall::Bsp::cmGeoSets.emplace_back();
    set.straddleGroup = 0;
    set.primitiveCount = static_cast<uint16_t>(group.members.size());
    set.uniqueContentsIndex = Titanfall::EmitUniqueContents(group.members.front().contents);
    set.collisionShapeIndex = group.first;
    set.collisionShapeType = 0;
    Titanfall::Bsp::cmGeoSetBounds.push_back(EncodeBounds(group.bounds));
}

// Model cells: every primitive belongs to the one cell, so group them directly.
void EmitPrimitiveGroups(std::vector<PendingPrimitive> &pending) {
    std::vector<PrimitiveGroup> groups = GroupPrimitives(pending, 1e30f);
    AllocateGroups(groups);
    for (const PrimitiveGroup &group : groups)
        EmitGroupGeoSet(group);
    pending.clear();
}
} // namespace

/*
    EmitCollisionGrid()
    Emits brushes of entity into bsp
*/
void Titanfall::EmitCollisionGrid( entity_t &e ) {
    std::vector<brush_t*> gridBrushes;
    std::vector<brush_t*> modelBrushes;

    MinMax gridSize;
    const auto patches = EmitPatchCollision(e);
    bool gridPatches = false;
    for (const auto &patch : patches) if (!patch.modelOnly) { gridSize.extend(patch.bounds); gridPatches = true; }

    // Sort brushes
    for( brush_t &brush : e.brushes ) {
        int skySides = 0;

        for( const side_t &side : brush.sides ) {
            if( side.bevel )
                continue;

            if( CHECK_FLAG(side.shaderInfo->compileFlags,C_SKY) )
                skySides++;
        }

        if( skySides ) {
            modelBrushes.emplace_back( &brush );
            continue;
        }

        gridBrushes.emplace_back( &brush );
        gridSize.extend( brush.minmax );
    }

    //Sys_Warning( "Grid brushes: %li\n", gridBrushes.size() );
    //Sys_Warning( "Model brushes: %li\n", modelBrushes.size() );

    // Emit grid brushes
    // Sky-only or patch-only worlds have no ordinary grid-brush bounds.
    if (gridBrushes.empty() && !gridPatches)
        gridSize.extend(Vector3(0, 0, 0));
    // Other models may already have emitted brushes; only index our own.
    const std::size_t firstBrush = Titanfall::Bsp::cmBrushes.size();
    for( brush_t *brush : gridBrushes )
        Titanfall::EmitBrush( *brush );

    // Worldspawn size
    Vector3 size = gridSize.maxs - gridSize.mins;

    // Choose scale
    // The limit seems to be 128x128, try to use size of 256 or higher
    float scale = 256;
    int x, y;
    x = ceil(size.x() / scale) + 2;
    y = ceil(size.y() / scale) + 2;
    while( x > 128 || y > 128 ) {
        scale += 16;
        x = ceil(size.x() / scale) + 2;
        y = ceil(size.y() / scale) + 2;
    }
    // Every primitive joins a GeoSet group in each cell it touches, and the cell
    // ranges are 16 bits. Large maps with big brushes overflow at the smallest
    // scale, so coarsen the grid until the estimated total fits.
    std::vector<PendingPrimitive> gridPrimitives;
    for (std::size_t index = 0; index < gridBrushes.size(); index++) {
        const Titanfall::CMBrush_t &brush = Titanfall::Bsp::cmBrushes.at(firstBrush + index);
        MinMax bounds;
        bounds.mins = brush.origin - brush.extents;
        bounds.maxs = brush.origin + brush.extents;
        gridPrimitives.push_back({bounds, brush.index, gridBrushes.at(index)->contentFlags, 0});
    }
    for (const auto &patch : patches)
        if (!patch.modelOnly) gridPrimitives.push_back({patch.bounds, patch.header, patch.contents, 0x40});
    const auto estimateGeoSets = [&gridPrimitives](float cellSize) {
        std::size_t total = Titanfall::Bsp::cmGeoSets.size();
        for (const PrimitiveGroup &group : GroupPrimitives(gridPrimitives, cellSize)) {
            const MinMax &b = group.bounds;
            total += (std::size_t)(floor(b.maxs.x() / cellSize) - floor(b.mins.x() / cellSize) + 1) *
                     (std::size_t)(floor(b.maxs.y() / cellSize) - floor(b.mins.y() / cellSize) + 1);
        }
        return total;
    };
    while (estimateGeoSets(scale) > 60000 && scale < 65536) {
        scale *= 1.25f;
        x = ceil(size.x() / scale) + 2;
        y = ceil(size.y() / scale) + 2;
    }
    Sys_FPrintf( SYS_VRB, "       Grid scale is: %f\n", scale );

    Titanfall::CMGrid_t &grid = Titanfall::Bsp::cmGrid.emplace_back();
    grid.scale = scale;
    grid.xOffset = floor(gridSize.mins.x() / grid.scale) - 1;
    grid.yOffset = floor(gridSize.mins.y() / grid.scale) - 1;
    grid.xCount = ceil(size.x() / grid.scale) + 2;
    grid.yCount = ceil(size.y() / grid.scale) + 2;
    grid.straddleGroupCount = 0;
    grid.brushSidePlaneOffset = 1;  // 1 plane for Cells/Portals

    // Group the grid's primitives once, then give each cell every group it overlaps.
    std::vector<PrimitiveGroup> groups = GroupPrimitives(gridPrimitives, grid.scale);
    AllocateGroups(groups);
    std::vector<std::vector<uint32_t>> cellGroups(std::size_t(grid.xCount) * grid.yCount);
    for (uint32_t g = 0; g < groups.size(); ++g) {
        const MinMax &b = groups[g].bounds;
        const int x0 = std::max(0, (int)floor(b.mins.x() / grid.scale) - grid.xOffset);
        const int x1 = std::min(grid.xCount - 1, (int)floor(b.maxs.x() / grid.scale) - grid.xOffset);
        const int y0 = std::max(0, (int)floor(b.mins.y() / grid.scale) - grid.yOffset);
        const int y1 = std::min(grid.yCount - 1, (int)floor(b.maxs.y() / grid.scale) - grid.yOffset);
        for (int y = y0; y <= y1; ++y)
            for (int x = x0; x <= x1; ++x) cellGroups[std::size_t(y) * grid.xCount + x].push_back(g);
    }

    // Make GridCells
    for (int32_t y = 0; y < grid.yCount; y++) {
        for (int32_t x = 0; x < grid.xCount; x++) {
            MinMax cellMinmax;
            cellMinmax.mins = Vector3((x + grid.xOffset) * grid.scale,
                                      (y + grid.yOffset) * grid.scale,
                                       gridSize.mins.z());
            cellMinmax.maxs = Vector3((x + grid.xOffset + 1) * grid.scale,
                                      (y + grid.yOffset + 1) * grid.scale,
                                       gridSize.maxs.z());

            // Sys_Printf("Worldspawn: %f %f %f : %f %f %f\n",
            //            Titanfall::Bsp::models[0].minmax.mins.x(),
            //            Titanfall::Bsp::models[0].minmax.mins.y(),
            //            Titanfall::Bsp::models[0].minmax.mins.z(),
            //            Titanfall::Bsp::models[0].minmax.maxs.x(),
            //            Titanfall::Bsp::models[0].minmax.maxs.y(),
            //            Titanfall::Bsp::models[0].minmax.maxs.z());
            // Sys_Printf("Cell      : %f %f %f : %f %f %f\n",
            //            cellMinmax.mins.x(), cellMinmax.mins.y(), cellMinmax.mins.z(),
            //            cellMinmax.maxs.x(), cellMinmax.maxs.y(), cellMinmax.maxs.z());

            if (Titanfall::Bsp::cmGeoSets.size() > 65535)
                Error("Collision grid-cell start exceeds 16 bits");
            Titanfall::CMGridCell_t &cell = Titanfall::Bsp::cmGridCells.emplace_back();
            cell.start = Titanfall::Bsp::cmGeoSets.size();

            for (uint32_t g : cellGroups[std::size_t(y) * grid.xCount + x])
                EmitGroupGeoSet(groups[g]);

            if (Titanfall::Bsp::cmGeoSets.size() - cell.start > 65535)
                Error("Collision grid-cell count exceeds 16 bits");
            cell.count = Titanfall::Bsp::cmGeoSets.size() - cell.start;
        }
    }

    std::size_t numGeoSets, numPrimitives;
    numGeoSets = Titanfall::Bsp::cmGeoSets.size();
    numPrimitives = Titanfall::Bsp::cmPrimitives.size();
    Sys_FPrintf( SYS_VRB, "       Grid ( %i : %i ) has %li GeoSets and %li Primitives\n", grid.xCount, grid.yCount, numGeoSets, numPrimitives );

    // Emit model brushes
    for( brush_t *brush : modelBrushes )
        Titanfall::EmitBrush( *brush );

    if (Titanfall::Bsp::cmGeoSets.size() > 65535)
        Error("Collision model-cell start exceeds 16 bits");
    Titanfall::CMGridCell_t &cell = Titanfall::Bsp::cmGridCells.emplace_back();
    cell.start = Titanfall::Bsp::cmGeoSets.size();

    std::vector<PendingPrimitive> pending;
    for( std::size_t i = 0; i < modelBrushes.size(); i++ ) {
        Titanfall::CMBrush_t &brush = Titanfall::Bsp::cmBrushes.at(firstBrush + gridBrushes.size() + i);

        MinMax brushMinmax;
        brushMinmax.mins = brush.origin - brush.extents;
        brushMinmax.maxs = brush.origin + brush.extents;

        pending.push_back({brushMinmax, brush.index, modelBrushes.at(i)->contentFlags, 0});
    }
    // Like sky brushes, recovered sky collision belongs to the global world
    // cell. Duplicating map-sized sky triangles into every XY cell overflows
    // native 16-bit cell ranges even for small retail maps.
    for (const auto &patch : patches) if (patch.modelOnly) pending.push_back({patch.bounds, patch.header, patch.contents, 0x40});
    EmitPrimitiveGroups(pending);

    numGeoSets = Titanfall::Bsp::cmGeoSets.size() - numGeoSets;
    numPrimitives = Titanfall::Bsp::cmPrimitives.size() - numPrimitives;
    Sys_FPrintf( SYS_VRB, "       Worldspawn model has %li GeoSets and %li Primitives\n", numGeoSets, numPrimitives );

    if (Titanfall::Bsp::cmGeoSets.size() - cell.start > 65535)
        Error("Collision model-cell count exceeds 16 bits");
    cell.count = Titanfall::Bsp::cmGeoSets.size() - cell.start;
}

/*
    EmitModelGridCell()
    Emits brushes of entity into bsp
*/
void Titanfall::EmitModelGridCell( entity_t &e ) {
    const auto patches = EmitPatchCollision(e);
    std::size_t offset = Titanfall::Bsp::cmBrushes.size();

    for( brush_t &brush : e.brushes )
        Titanfall::EmitBrush( brush );

    if (Titanfall::Bsp::cmGeoSets.size() > 65535)
        Error("Collision model-cell start exceeds 16 bits");
    Titanfall::CMGridCell_t &cell = Titanfall::Bsp::cmGridCells.emplace_back();
    cell.start = Titanfall::Bsp::cmGeoSets.size();

    std::vector<PendingPrimitive> pending;
    std::size_t i = 0;
    for( brush_t &b : e.brushes ) {
        Titanfall::CMBrush_t &brush = Titanfall::Bsp::cmBrushes.at(offset + i);

        MinMax brushMinmax;
        brushMinmax.mins = brush.origin - brush.extents;
        brushMinmax.maxs = brush.origin + brush.extents;

        pending.push_back({brushMinmax, brush.index, b.contentFlags, 0});

        i++;
    }

    for (const auto &patch : patches) pending.push_back({patch.bounds, patch.header, patch.contents, 0x40});
    EmitPrimitiveGroups(pending);
    if (Titanfall::Bsp::cmGeoSets.size() - cell.start > 65535)
        Error("Collision model-cell count exceeds 16 bits");
    cell.count = Titanfall::Bsp::cmGeoSets.size() - cell.start;
}

/*
    EmitGeoSet()
    Emits a geo set into bsp
*/
void Titanfall::EmitGeoSet(MinMax minmax, int index, int flags) {
    if (index < 0 || index > 65535)
        Error("Collision shape index exceeds 16 bits");
    Titanfall::CMGeoSet_t &set = Titanfall::Bsp::cmGeoSets.emplace_back();
    set.straddleGroup = 0;
    set.primitiveCount = 1;
    set.uniqueContentsIndex = Titanfall::EmitUniqueContents(flags);
    set.collisionShapeIndex = index;

    Titanfall::Bsp::cmGeoSetBounds.push_back(EncodeBounds(minmax));
}

/*
    EmitBrushSideProperty()
    Returns a brush side property for the side's texture. The texture index
    only has 9 bits; later textures fall back to texture 0 instead of failing.
*/
static uint16_t EmitBrushSideProperty(const shaderInfo_t &shader) {
    const uint32_t texture = Titanfall::EmitTextureData(shader);
    if (texture <= 0x1ff)
        return texture;

    static bool warned = false;
    if (!warned) {
        Sys_FPrintf(SYS_WRN, "WARNING: Collision side texture index %u exceeds its 9-bit field; "
                             "sides using texture 512 or later fall back to texture 0\n", texture);
        warned = true;
    }
    return 0;
}

/*
    EmitBrush()
    Emits a brush into bsp
*/
void Titanfall::EmitBrush(brush_t &brush) {
    // TODO: The core structs ( entity_t, brush_t parseMest_t, shaderInfo_t, etc... ) need to be rewritten
    // to avoid this
    for( side_t &side : brush.sides ) {
        if( !side.bevel && !brush.recoveredContents )
            brush.contentFlags |= side.shaderInfo->contentFlags;
            // TODO: collect shader contentClearFlags & mask at the end
    }


    if (Titanfall::Bsp::cmBrushes.size() > 65535)
        Error("Collision brush index exceeds 16 bits");
    Titanfall::CMBrush_t &b = Titanfall::Bsp::cmBrushes.emplace_back();

    b.extents = brush.minmax.extents();
    b.origin = brush.minmax.origin();
    b.index = Titanfall::Bsp::cmBrushes.size() - 1;
    b.planeCount = 0;
    b.unknown = 0;
    // All brushes need this prefix, including boxes after non-axial brushes.
    // It also locates the side properties at 6 * brush.index + sidePlaneIndex.
    b.sidePlaneIndex = Titanfall::Bsp::cmBrushSidePlaneOffsets.size();

    std::vector<side_t>  axialSides;
    std::vector<side_t>  cuttingSides;
    for (const side_t &side : brush.sides) {
        Vector3 normal = side.plane.normal();
        SnapNormal(normal);
        if ((normal[0] == -1.0f || normal[0] == 1.0f || (normal[0] == 0.0f && normal[1] == 0.0f)
          || normal[1] == -1.0f || normal[1] == 1.0f || (normal[1] == 0.0f && normal[2] == 0.0f)
          || normal[2] == -1.0f || normal[2] == 1.0f || (normal[2] == 0.0f && normal[0] == 0.0f)) && !side.bevel) {
            // Axial
            axialSides.emplace_back(side);
        }
        // Not Axial
        cuttingSides.emplace_back(side);
    }

    // -X +X -Y +Y -Z +Z
    // Retail Glitch/Angel City brushes discard axial slots on the side their
    // cutting planes face; that only agrees with negative-first ordering.
    // Sloped brushes can have missing axial faces; these must have null shaders.
    side_t sortedAxialSides[6]{};
    sortedAxialSides[0].plane=Plane3(-1, 0, 0, 0);
    sortedAxialSides[1].plane=Plane3(+1, 0, 0, 0);
    sortedAxialSides[2].plane=Plane3(0, -1, 0, 0);
    sortedAxialSides[3].plane=Plane3(0, +1, 0, 0);
    sortedAxialSides[4].plane=Plane3(0, 0, -1, 0);
    sortedAxialSides[5].plane=Plane3(0, 0, +1, 0);
    // The bsp brushes are AABBs + cutting planes
    // Surface flags are indexed first for AABB ( first 6 planes ) then for the rest
    // Radiant brushes are made purely of planes so we dont have a guarantee that we'll get the
    // Axial ones which define the AABB, that's why we first sort them
    for (const side_t &side : axialSides) {
        Vector3 normal = side.plane.normal();
        SnapNormal(normal);

        if (normal[0] == -1.0f) {
            sortedAxialSides[0] = side;
        } else if (normal[0] == 1.0f) {
            sortedAxialSides[1] = side;
        }

        if (normal[1] == -1.0f) {
            sortedAxialSides[2] = side;
        } else if (normal[1] == 1.0f) {
            sortedAxialSides[3] = side;
        }

        if (normal[2] == -1.0f) {
            sortedAxialSides[4] = side;
        } else if (normal[2] == 1.0f) {
            sortedAxialSides[5] = side;
        }
    }

    for (int i = 0; i < 6; i++) {
        side_t side = sortedAxialSides[i];
        if (side.shaderInfo != nullptr) {
            Titanfall::Bsp::cmBrushSideProperties.emplace_back(EmitBrushSideProperty(*side.shaderInfo));
        } else {
            Titanfall::Bsp::cmBrushSideProperties.emplace_back(MASK_DISCARD);
            // TODO: ensure BrushSideProperty indexes tools/toolsnodraw
            // -- either always emit nodraw as the first TextureData, or EmitTextureData here & now
        }

        Vector3  s_axis, t_axis;
        ComputeAxisBase(side.plane.normal(), s_axis, t_axis);
        auto &tv = Titanfall::Bsp::cmBrushSideTexVecs.emplace_back();
        tv.s_axis = s_axis;  tv.s_offset = side.texMat[0][2];
        tv.t_axis = t_axis;  tv.t_offset = side.texMat[1][2];
    }

#if 1
    for (const side_t &side : cuttingSides) {
        Vector3 normal = side.plane.normal();
        SnapNormal(normal);
        if (normal[0] == -1.0f || normal[0] == 1.0f || (normal[0] == 0.0f && normal[1] == 0.0f)
            || normal[1] == -1.0f || normal[1] == 1.0f || (normal[1] == 0.0f && normal[2] == 0.0f)
            || normal[2] == -1.0f || normal[2] == 1.0f || (normal[2] == 0.0f && normal[0] == 0.0f) || side.bevel) {
            continue;  // axial, only test non-axial edges
        }

        Titanfall::EmitPlane(side.plane);
        if (b.planeCount == 255)
            Error("Collision brush has more than 255 non-axial sides");
        b.planeCount++;
        Titanfall::Bsp::cmBrushSideProperties.emplace_back(EmitBrushSideProperty(*side.shaderInfo));

        uint16_t &so = Titanfall::Bsp::cmBrushSidePlaneOffsets.emplace_back();
        so = 0;

        Vector3  s_axis, t_axis;
        ComputeAxisBase(normal, s_axis, t_axis);
        auto &tv = Titanfall::Bsp::cmBrushSideTexVecs.emplace_back();
        tv.s_axis = s_axis;  tv.s_offset = side.texMat[0][2];
        tv.t_axis = t_axis;  tv.t_offset = side.texMat[1][2];
    }

    if (b.planeCount) {
        b.unknown = b.planeCount;
        b.sidePlaneIndex = Titanfall::Bsp::cmBrushSidePlaneOffsets.size() - b.planeCount;
    }
#endif
}

/*
    EmitUniqueContents()
    Emits collision flags and returns index to them
*/
int Titanfall::EmitUniqueContents(int flags) {
    for( int i = 0; i < Titanfall::Bsp::cmUniqueContents.size(); i++ ) {
        if( Titanfall::Bsp::cmUniqueContents.at(i) == flags )
            return i;
    }

    if (Titanfall::Bsp::cmUniqueContents.size() >= 256)
        Error("Collision contents index exceeds 8 bits");
    Titanfall::Bsp::cmUniqueContents.emplace_back( flags );

    return Titanfall::Bsp::cmUniqueContents.size() - 1;
}
