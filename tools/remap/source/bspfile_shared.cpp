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

#include "remap.h"
#include "bspfile_abstract.h"
#include "respawn/lightmap.h"
#include "respawn/csg.h"
#include <cmath>
#include <limits>
#include <map>
#include <tuple>

namespace {
// Original RSM1 scene interchange, not a Respawn engine format. Used by the
// bounded decompiler to preserve recovered render vertices independently of
// collision brushes. See docs/respawn/RESPAWN_DECOMPILE.md. "_remap_props" holds
// extra render-only geometry (converted props) drawn alongside the brushes.
void ReadRecoveredMeshes(const entity_t &entity, const char *key, int &meshIndex) {
    const char *path = entity.valueForKey(key);
    if (!path[0]) return;
    MemBuffer data = vfsLoadFile(path);
    if (!data || data.size() > 256u * 1024u * 1024u) Error("Missing or oversized recovered mesh %s", path);
    std::size_t cursor = 0;
    auto read = [&](void *out, std::size_t size) {
        if (size > data.size() - cursor) Error("Truncated recovered mesh %s", path);
        std::memcpy(out, static_cast<const unsigned char *>(data.data()) + cursor, size); cursor += size;
    };
    auto u32 = [&]() { uint32_t value; read(&value, 4); return value; };
    auto number = [&]() { float value; read(&value, 4); if (!std::isfinite(value)) Error("Nonfinite recovered mesh vertex"); return value; };
    if (u32() != 0x314d5352) Error("Expected RSM1 recovered mesh %s", path);
    const uint32_t count = u32();
    // Charts are lightmap islands, merged into far fewer BSP meshes later; this only bounds the file.
    if (count > 4u * 1024u * 1024u) Error("Too many recovered mesh charts");
    for (uint32_t m = 0; m < count; ++m) {
        const uint32_t length = u32();
        if (!length || length > 255) Error("Invalid recovered mesh material length");
        std::string material(length, '\0'); read(material.data(), length);
        if (material.find('\0') != std::string::npos) Error("Embedded NUL in recovered material");
        const uint32_t nv = u32(), ni = u32();
        if (!nv || nv > 65535 || !ni || ni > 63000 || ni % 3) Error("Invalid recovered mesh counts");
        Shared::Mesh_t &mesh = Shared::meshes.emplace_back();
        mesh.shaderInfo = ShaderInfoForShader(material.c_str());
        Shared::Island_t island; island.mesh = meshIndex;
        for (uint32_t v = 0; v < nv; ++v) {
            Shared::Vertex_t vertex{};
            for (int a = 0; a < 3; ++a) vertex.xyz[a] = number();
            for (int a = 0; a < 3; ++a) vertex.normal[a] = number();
            if (vector3_length(vertex.normal) < 1e-6) Error("Zero recovered mesh normal");
            for (int a = 0; a < 2; ++a) vertex.textureUV[a] = number();
            read(&vertex.colour, 4);
            // RSM1 lightmap coordinates are in 16-unit luxels.
            for (int a = 0; a < 2; ++a) vertex.lightmapUV[a] = number() * 16.0f / Shared::luxelSize;
            vertex.lightmapStep = Vector2(0, 0);
            mesh.vertices.push_back(vertex); mesh.minmax.extend(vertex.xyz); island.bounds.extend(vertex.lightmapUV);
        }
        for (uint32_t i = 0; i < ni; ++i) {
            const uint32_t index = u32();
            if (index >= nv) Error("Recovered mesh index outside vertex pool");
            mesh.triangles.push_back(index);
        }
        if ((mesh.shaderInfo->surfaceFlags & 0x600) < 0x400) Shared::islands.push_back(island);
        ++meshIndex;
    }
    if (cursor != data.size()) Error("Unexpected recovered mesh tail %s", path);
}
// Merges meshes sharing a material, lightmap page and grid cell, in material order.
// Sky stays one mesh: splitting a dome by cell gains no culling.
void ClusterMeshes(float size) {
    using Key = std::tuple<std::string, int, int, int, int>;
    std::map<Key, std::vector<Shared::Mesh_t>> clusters;
    for (Shared::Mesh_t &mesh : Shared::meshes) {
        const Vector3 centre = (mesh.minmax.mins + mesh.minmax.maxs) * 0.5f;
        const bool sky = CHECK_FLAG(mesh.shaderInfo->compileFlags, C_SKY);
        Key key{mesh.shaderInfo->shader.c_str(), mesh.lightmapPage,
                sky ? 0 : static_cast<int>(std::floor(centre.x() / size)),
                sky ? 0 : static_cast<int>(std::floor(centre.y() / size)),
                sky ? 0 : static_cast<int>(std::floor(centre.z() / size))};
        std::vector<Shared::Mesh_t> &group = clusters[key];
        if (group.empty() || group.back().triangles.size() + mesh.triangles.size() > 63000
         || group.back().vertices.size() + mesh.vertices.size() > 60000) {
            group.push_back(std::move(mesh));
            continue;
        }
        Shared::Mesh_t &out = group.back();
        const std::size_t base = out.vertices.size();
        for (uint16_t triIndex : mesh.triangles)
            out.triangles.emplace_back(static_cast<uint16_t>(triIndex + base));
        out.vertices.insert(out.vertices.end(), mesh.vertices.begin(), mesh.vertices.end());
        out.minmax.extend(mesh.minmax);
    }
    Shared::meshes.clear();
    for (auto &[key, group] : clusters)
        for (Shared::Mesh_t &mesh : group)
            Shared::meshes.push_back(std::move(mesh));
}
} // namespace


/*
    MakeMeshes()
    Makes the initial shared meshes for a given entity
*/
void Shared::MakeMeshes(const entity_t &e) {
    // Multiple entities can have meshes, make sure we clear before making new meshes
    Shared::meshes.clear();
    Shared::islands.clear();
    // Large maps need coarser lightmaps to fit their pages and mesh budget.
    if (e.floatForKey("_remap_luxelsize") > 0.0f)
        Shared::luxelSize = e.floatForKey("_remap_luxelsize");
    Shared::lightmapByMaterial = e.boolForKey("_remap_lightmap_by_material");

    // Solid, visible brushes hide faces buried in or flush against them (see
    // respawn/csg.h). Clip, trigger and translucent brushes hide nothing.
    std::vector<Respawn::Csg::Solid>  solids;
    int brush_order = 0;
    for (const brush_t &brush : e.brushes) {
        bool visible = false, translucent = false;
        int contents = 0;
        for (const side_t &side : brush.sides) {
            if (side.bevel || !side.shaderInfo)
                continue;
            visible |= !(side.shaderInfo->compileFlags & C_NODRAW);
            translucent |= (side.shaderInfo->compileFlags & C_TRANSLUCENT) != 0;
            contents |= side.shaderInfo->contentFlags;
        }
        // Render-only brushes ("$contentflag nonsolid", e.g. Source func_illusionary)
        // do not hide faces they touch, as they never did in their source engine.
        const bool nonsolid = !(contents & CONTENTS_SOLID);
        if (visible && !translucent && !nonsolid) {
            Respawn::Csg::Solid &solid = solids.emplace_back();
            // Bevel sides carry no side.plane; their plane lives in mapplanes.
            for (const side_t &side : brush.sides) {
                const Plane3f &plane = mapplanes[side.planenum].plane;
                solid.planes.push_back({{plane.normal().x(), plane.normal().y(), plane.normal().z()}, plane.dist()});
            }
            solid.mins = {brush.minmax.mins.x(), brush.minmax.mins.y(), brush.minmax.mins.z()};
            solid.maxs = {brush.minmax.maxs.x(), brush.minmax.maxs.y(), brush.minmax.maxs.z()};
            solid.order = brush_order;
        }
        brush_order++;
    }
    std::size_t hidden_faces = 0, split_faces = 0;

    int mesh_index = 0;
    const bool recoveredMeshes = e.valueForKey("_remap_mesh")[0] != 0;
    brush_order = 0;
    // Loop through brushes
    for (const brush_t &brush : e.brushes) {
        if (recoveredMeshes) break; // these brushes represent collision only
        const int owner = brush_order++;
        // Loop through sides
        for (const side_t &side : brush.sides) {
            // Skip bevels & check flags
            if (side.bevel
             || side.shaderInfo->compileFlags & C_NODRAW) {
                continue;
            }

            // Check for degenerate windings
            if (side.winding.size() < 3) {
                Sys_FPrintf(SYS_WRN, "        Skipping degenerate winding!\n");
                continue;
            }

            Respawn::Csg::Polygon face;
            for (const Vector3 &vertex : side.winding)
                face.push_back({vertex.x(), vertex.y(), vertex.z()});
            const Respawn::Csg::Plane facePlane{{side.plane.normal().x(), side.plane.normal().y(), side.plane.normal().z()},
                                                side.plane.dist()};
            const std::vector<Respawn::Csg::Polygon> fragments = Respawn::Csg::visibleFragments(face, facePlane, owner, solids);
            if (fragments.empty())
                hidden_faces++;
            else if (fragments.size() > 1 || fragments[0].size() != face.size())
                split_faces++;

            for (const Respawn::Csg::Polygon &fragment : fragments) {
                winding_t winding;
                for (const Respawn::Csg::Point &p : fragment)
                    winding.push_back(Vector3(p[0], p[1], p[2]));

                Shared::Mesh_t &mesh = Shared::meshes.emplace_back();
                mesh.shaderInfo = side.shaderInfo;
                Shared::Island_t  island;

                Vector3 normal = side.plane.normal();

                // Loop through vertices
                for (const Vector3 &vertex : winding) {
                    // Extend AABB
                    mesh.minmax.extend(vertex);

                    // Texturing
                    // This is taken from surface.cpp, It somewhat works
                    // TODO: Make this work better
                    Vector2  textureUV, lightmapUV;
                    Vector3  vTranslated, texX, texY;
                    float    x, y;
                    ComputeAxisBase(side.plane.normal(), texX, texY);
                    vTranslated = vertex + e.originbrush_origin;
                    // st vectors -> uv coords
                    x = vector3_dot(vTranslated, texX);
                    y = vector3_dot(vTranslated, texY);
                    // TODO: scale lightmapUV by side.luxelScale
                    lightmapUV = {x / Shared::luxelSize, y / Shared::luxelSize};
                    if (g_brushType == EBrushType::Bp) {
                        textureUV[0] = side.texMat[0][0] * x + side.texMat[0][1] * y + side.texMat[0][2];
                        textureUV[1] = side.texMat[1][0] * x + side.texMat[1][1] * y + side.texMat[1][2];
                    } else {
                        // Quake and Valve 220 maps carry st vectors instead of a texture matrix.
                        textureUV[0] = (side.vecs[0][3] + vector3_dot(side.vecs[0].vec3(), vTranslated)) / side.shaderInfo->shaderWidth;
                        textureUV[1] = (side.vecs[1][3] + vector3_dot(side.vecs[1].vec3(), vTranslated)) / side.shaderInfo->shaderHeight;
                    }

                    Shared::Vertex_t &sv = mesh.vertices.emplace_back();
                    sv.xyz          = vertex;
                    sv.normal       = normal;
                    sv.textureUV    = textureUV;
                    sv.colour       = {0xFF, 0xFF, 0xFF, 0xFF};
                    sv.lightmapUV   = lightmapUV;
                    sv.lightmapStep = {0.0f, 0.0f};  // unused

                    island.bounds.extend(lightmapUV);
                }

                if ((mesh.shaderInfo->surfaceFlags & 0x600) < 0x400) {  // mesh is lit
                    island.mesh = mesh_index;
                    Shared::islands.push_back(island);
                } else {
                    mesh.lightmapPage = -1;
                }

                // Create triangles for side
                for (std::size_t i = 0; i < winding.size() - 2; i++) {
                    for (int j = 0; j < 3; j++) {
                        int vert_index = (j == 0) ? 0 : i + j;
                        mesh.triangles.emplace_back(vert_index);
                    }
                }

                mesh_index++;
            }
        }
    }
    if (hidden_faces || split_faces)
        Sys_FPrintf(SYS_VRB, "%9zu hidden brush faces removed, %zu partly hidden faces trimmed\n", hidden_faces, split_faces);

    // Loop through patches
    parseMesh_t *patch;
    patch = e.patches;
    while (patch != NULL && !recoveredMeshes) {
        mesh_t patchMesh = patch->mesh;

        // Collision-only patches (nodraw) have no render material.
        if (CHECK_FLAG(patch->shaderInfo->compileFlags, C_NODRAW)) {
            patch = patch->next;
            continue;
        }

        // Map control points carry positions and UVs, not initialized normals.
        // The Respawn path bypasses Q3's DrawSurfaceForMesh normal generation.
        MakeMeshNormals(patchMesh);
        const int vertexCount = patchMesh.width * patchMesh.height;
        std::vector<Vector3> patchNormals(vertexCount);
        std::vector<int> validNormals;
        for (int i = 0; i < vertexCount; ++i) {
            auto& normal = patchNormals[i];
            normal = patchMesh.verts[i].normal;
            const double length = vector3_length(normal);
            if (std::isfinite(length) && length > 1e-6) {
                normal /= length;
                validNormals.push_back(i);
            }
        }
        // A collapsed grid edge can leave a control point with no local fan.
        // Borrow the closest usable grid normal without changing geometry.
        Vector3 fallbackNormal(0,0,1);
        if (validNormals.empty()) {
            bool found = false;
            for (int y = 0; y + 1 < patchMesh.height && !found; ++y) {
                for (int x = 0; x + 1 < patchMesh.width && !found; ++x) {
                    const int a = x + y * patchMesh.width;
                    const int quad[] = {a,a+patchMesh.width,a+patchMesh.width+1,a+1};
                    for (int t = 0; t < 2; ++t) {
                        const auto& p0 = patchMesh.verts[quad[0]].xyz;
                        const auto& p1 = patchMesh.verts[quad[t+1]].xyz;
                        const auto& p2 = patchMesh.verts[quad[t+2]].xyz;
                        auto normal = vector3_cross(p2-p0,p1-p0);
                        if (VectorNormalize(normal) > 1e-6) {fallbackNormal=normal;found=true;break;}
                    }
                }
            }
        }
        for (int i = 0; i < vertexCount; ++i) {
            const auto& normal = patchNormals[i];
            const double length = vector3_length(normal);
            if (std::isfinite(length) && length > 1e-6) continue;
            int closest = -1;
            double distance = std::numeric_limits<double>::infinity();
            for (const int candidate : validNormals) {
                const auto delta = patchMesh.verts[i].xyz - patchMesh.verts[candidate].xyz;
                const double squared = vector3_dot(delta,delta);
                if (squared < distance) {distance=squared;closest=candidate;}
            }
            patchNormals[i] = closest >= 0 ? patchNormals[closest] : fallbackNormal;
        }

        Shared::Mesh_t &mesh = Shared::meshes.emplace_back();
        mesh.shaderInfo = patch->shaderInfo;
        Shared::Island_t  island;

        // Unwrap the grid by average column/row arc length so curved patches
        // don't fold over themselves in lightmap space.
        const int  pw = patchMesh.width, ph = patchMesh.height;
        std::vector<float>  columnU(pw, 0.0f), rowV(ph, 0.0f);
        for (int x = 1; x < pw; x++) {
            float  sum = 0.0f;
            for (int y = 0; y < ph; y++)
                sum += vector3_length(patchMesh.verts[x + y * pw].xyz - patchMesh.verts[x - 1 + y * pw].xyz);
            columnU[x] = columnU[x - 1] + sum / ph / Shared::luxelSize;
        }
        for (int y = 1; y < ph; y++) {
            float  sum = 0.0f;
            for (int x = 0; x < pw; x++)
                sum += vector3_length(patchMesh.verts[x + y * pw].xyz - patchMesh.verts[x + (y - 1) * pw].xyz);
            rowV[y] = rowV[y - 1] + sum / pw / Shared::luxelSize;
        }

        // Get vertices
        for (int index = 0; index < (patchMesh.width * patchMesh.height); index++) {
            Shared::Vertex_t &vertex = mesh.vertices.emplace_back();

            vertex.xyz          = patchMesh.verts[index].xyz;
            vertex.normal       = patchNormals[index];
            vertex.textureUV    = patchMesh.verts[index].st;
            vertex.colour       = {0xFF, 0xFF, 0xFF, 0xFF};  // TODO: patchMesh.verts[index].colour
            Vector2  lightmapUV = {columnU[index % pw], rowV[index / pw]};
            vertex.lightmapUV   = lightmapUV;
            vertex.lightmapStep = {0.0f, 0.0f};  // unused

            mesh.minmax.extend(vertex.xyz);
            island.bounds.extend(lightmapUV);
        }

        if ((mesh.shaderInfo->surfaceFlags & 0x600) < 0x400) {  // mesh is lit
            island.mesh = mesh_index;
            Shared::islands.push_back(island);
        } else {
            mesh.lightmapPage = -1;
        }

        // Make triangles
        for (int x = 0; x < (patchMesh.width - 1); x++) {
            for (int y = 0; y < (patchMesh.height - 1); y++) {
                int index = x + y * patchMesh.width;

                mesh.triangles.emplace_back(index);
                mesh.triangles.emplace_back(index + patchMesh.width);
                mesh.triangles.emplace_back(index + patchMesh.width + 1);

                mesh.triangles.emplace_back(index);
                mesh.triangles.emplace_back(index + patchMesh.width + 1);
                mesh.triangles.emplace_back(index + 1);
            }
        }

        patch = patch->next;
        mesh_index++;
    }

    ReadRecoveredMeshes(e, "_remap_mesh", mesh_index);
    ReadRecoveredMeshes(e, "_remap_props", mesh_index);

    // Recalculate lightmapUVs for all vertices
    if (Shared::lightmapsEnabled)
        Shared::MakeLightmapUVs();

    // Block worlds have thousands of disjoint faces, so the AABB merge below leaves
    // too many meshes and materials interleaved. "_meshcluster" instead groups by
    // material, lightmap page and grid cell, keeping each material's meshes adjacent.
    const float meshCluster = e.floatForKey("_meshcluster");
    if (meshCluster > 0.0f)
        ClusterMeshes(meshCluster);

    // Combine all meshes based on shaderInfo and AABB tests
    std::size_t index = 0;
    std::size_t iterationsSinceCombine = 0;
    while (true) {
        // std::out_of_range can't comprehend this
        if (index >= Shared::meshes.size()) {
            index = 0;
        }

        // No more meshes to combine; break from the loop
        if (meshCluster > 0.0f || iterationsSinceCombine >= Shared::meshes.size()) {
            break;
        }

        // Get mesh which we then compare to the rest, maybe combine, maybe not
        Shared::Mesh_t &mesh1 = Shared::meshes.at(index);
        for (std::size_t i = 0; i < Shared::meshes.size(); i++) {
            if (index == i) { continue; }  // We don't want to compare the same mesh

            Shared::Mesh_t &mesh2 = Shared::meshes.at(i);

            if (mesh1.triangles.size() + mesh2.triangles.size() > 63000
             || mesh1.lightmapPage != mesh2.lightmapPage
             || !striEqual(mesh1.shaderInfo->shader.c_str(), mesh2.shaderInfo->shader.c_str())
             || !mesh1.minmax.test(mesh2.minmax)) {
                continue;
            }

            // All tests passed! We can combine these meshes
            for (uint16_t &triIndex : mesh2.triangles) {
                mesh1.triangles.emplace_back(triIndex + mesh1.vertices.size());
            }
            mesh1.vertices.insert(mesh1.vertices.end(), mesh2.vertices.begin(), mesh2.vertices.end());
            mesh1.minmax.extend(mesh2.minmax);

            // Delete mesh we combined as to not create duplicates
            Shared::meshes.erase(Shared::meshes.begin() + i);
            iterationsSinceCombine = 0;
            break;
        }

        iterationsSinceCombine++;
        index++;
    }

    // sort meshes
    std::vector<Shared::Mesh_t>  opaque_meshes;
    std::vector<Shared::Mesh_t>  decal_meshes;
    std::vector<Shared::Mesh_t>  trans_meshes;
    std::vector<Shared::Mesh_t>  sky_meshes;

    for (Shared::Mesh_t &mesh : Shared::meshes) {
        if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_SKY) && CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_SKY)) {
            sky_meshes.push_back(mesh);
            // Respawn does this on their skyboxes, seems to work even when kept
            REMOVE_FLAG(mesh.shaderInfo->surfaceFlags, S_MESH_UNKNOWN);
        } else if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_DECAL)) {
            decal_meshes.push_back(mesh);
        } else if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_TRANSLUCENT)) {
            trans_meshes.push_back(mesh);
        } else {
            opaque_meshes.push_back(mesh);
        }
    }

    // rebuild Shared::meshes from the sorted groups
    Shared::meshes.clear();
    #define COPY_MESHES(x)  Shared::meshes.insert(Shared::meshes.end(), x.begin(), x.end())
    COPY_MESHES(opaque_meshes);
    COPY_MESHES(decal_meshes);
    COPY_MESHES(trans_meshes);
    COPY_MESHES(sky_meshes);
    #undef COPY_MESHES

    // TODO: pack lightmaps for lit meshes
}


void Shared::MakeVisReferences() {
    /* Meshes */
    for (std::size_t i = 0; i < Shared::meshes.size(); i++) {
        Shared::Mesh_t &mesh = Shared::meshes.at(i);
        Shared::visRef_t &ref = Shared::visRefs.emplace_back();

        ref.minmax = mesh.minmax;
        ref.minmax.mins -= Vector3(1.0f);
        ref.minmax.maxs += Vector3(1.0f);
        ref.index = i;
    }

    /* Props */
    Sys_Printf("%9zu shared vis references\n", Shared::visRefs.size());
}


/*
    CalculateSAH
    calculates the surface-area-heurestic for a BVHx Tree
*/
float CalculateSAH(std::vector<Shared::visRef_t> &refs, MinMax &parent, int &axis, float *pos) {
    // NOTE [Fifty]: I plan on rewriting this soon
    const int type = 2;
    MinMax childMinMaxs[type] = {};
    std::size_t childRefCounts[type] = {};

    // Count and create AABBs from references
    for (Shared::visRef_t &ref : refs) {
        float refPos = ref.minmax.maxs[axis];

        // Since this function supports any number of children we need to
        // First node handling
        if (refPos < pos[0]) {
            childRefCounts[0]++;
            childMinMaxs[0].extend(ref.minmax);
            continue;
        }

        // Middle nodes
        for (int separator = 1; separator < type - 1; separator++) {
            if (refPos > pos[separator - 1] && refPos < pos[separator]) {
                childRefCounts[separator]++;
                childMinMaxs[separator].extend(ref.minmax);
            }
        }

        // Last node handling
        childRefCounts[type - 1]++;
        childMinMaxs[type - 1].extend(ref.minmax);
    }

    float parentArea = parent.area();

    float cost = .5f;
    for (int i = 0; i < type; i++) {
        if (childRefCounts[i] != 0) {
            float childArea = childMinMaxs[i].area();
            cost += childRefCounts[i] * childArea;
        }
    }

    cost /= parentArea;
    // Sys_Printf("%f\n", cost);

    return cost;
}


/*
    MakeVisTree
    Creates a node and either stops or tries to create children
*/
Shared::visNode_t Shared::MakeVisTree(std::vector<Shared::visRef_t> refs, float parentCost) {
    Shared::visNode_t  node;

    // Create MinMax of our node
    MinMax minmax;
    for (Shared::visRef_t &ref : refs) {
        minmax.extend(ref.minmax);
    }

    node.minmax = minmax;

    // A conservative object BVH: each reference has one owner, so subtree
    // totals match runtime traversal exactly. Spatial SAH duplication made
    // overlapping planar material meshes disappear as the camera turned.
    // Stay well inside the byte-sized direct-reference field.
    if (refs.size() <= 64) {
        node.refs = std::move(refs);
        return node;
    }
    int axis = 0;
    for (int a = 1; a < 3; ++a)
        if (minmax.maxs[a] - minmax.mins[a] > minmax.maxs[axis] - minmax.mins[axis]) axis = a;
    std::stable_sort(refs.begin(), refs.end(), [axis](const Shared::visRef_t &a, const Shared::visRef_t &b) {
        return a.minmax.mins[axis] + a.minmax.maxs[axis] < b.minmax.mins[axis] + b.minmax.maxs[axis];
    });
    const auto middle = refs.begin() + refs.size() / 2;
    node.children.emplace_back(Shared::MakeVisTree(std::vector<Shared::visRef_t>(refs.begin(), middle), 1e30f));
    node.children.emplace_back(Shared::MakeVisTree(std::vector<Shared::visRef_t>(middle, refs.end()), 1e30f));
    return node;
}


/*
    MergeVisTree
    Walks the tree and tries to merge as many nodes as it can
    This gives us a shallower tree which should reduce mesh flickering
*/
void Shared::MergeVisTree(Shared::visNode_t &node) {
    float originalSAH = 0;
    for (Shared::visNode_t &child : node.children) {
        originalSAH = child.minmax.area();
    }
    originalSAH /= node.minmax.area();

    int timeout = 0;

    float newSAH = 1e30f;
    // Try to merge as many children as we can
    // Both the timeout and the "/ 10" are arbitrary
    while (originalSAH / 10 < newSAH) {
        std::vector<visNode_t> children;
        children = node.children;
        node.children.clear();

        for (Shared::visNode_t &child : children) {
            if (child.children.size() == 0 || child.refs.size() != 0) {
                node.children.push_back(child);
                continue;
            }

            for (Shared::visNode_t &c : child.children) {
                node.children.push_back(c);
            }
        }

        newSAH = 0;
        for (Shared::visNode_t &child : node.children) {
            newSAH = child.minmax.area();
        }
        newSAH /= node.minmax.area();

        timeout++;
        if (timeout > 10) {
            break;
        }
    }

    for (Shared::visNode_t &child : node.children) {
        if (child.children.size() != 0) {
            MergeVisTree(child);
        }
    }
}


/*
    MakeLightmapUVs()
    recalculate lightmap uvs for Shared::meshes
*/
namespace {
Shared::Vertex_t LerpVertex(const Shared::Vertex_t &a, const Shared::Vertex_t &b, float t) {
    Shared::Vertex_t v = a;
    v.xyz = a.xyz + (b.xyz - a.xyz) * t;
    v.normal = a.normal + (b.normal - a.normal) * t;
    if (vector3_length(v.normal) > 1e-6f) v.normal = vector3_normalised(v.normal);
    v.textureUV = a.textureUV + (b.textureUV - a.textureUV) * t;
    v.lightmapUV = a.lightmapUV + (b.lightmapUV - a.lightmapUV) * t;
    v.lightmapStep = a.lightmapStep + (b.lightmapStep - a.lightmapStep) * t;
    for (int c = 0; c < 4; ++c)
        v.colour[c] = static_cast<uint8_t>(std::lround(a.colour[c] + (b.colour[c] - a.colour[c]) * t));
    return v;
}

// Clip a polygon to lightmap-space u (axis 0) or v (axis 1) >= or <= a line.
std::vector<Shared::Vertex_t> ClipLightmap(const std::vector<Shared::Vertex_t> &poly, int axis, float line, bool keepAbove) {
    std::vector<Shared::Vertex_t> out;
    for (std::size_t i = 0; i < poly.size(); ++i) {
        const Shared::Vertex_t &a = poly[i], &b = poly[(i + 1) % poly.size()];
        const float da = (a.lightmapUV[axis] - line) * (keepAbove ? 1 : -1);
        const float db = (b.lightmapUV[axis] - line) * (keepAbove ? 1 : -1);
        if (da >= 0) out.push_back(a);
        if ((da >= 0) != (db >= 0)) out.push_back(LerpVertex(a, b, da / (da - db)));
    }
    return out;
}

/*
    An island larger than a lightmap page used to be shrunk as a whole, losing
    resolution over the entire face or patch. Instead, cut it on a page-sized
    grid in lightmap space: each tile becomes its own mesh and island at full
    resolution. Cuts add vertices where a grid line crosses the island's edges.
*/
std::size_t SplitOversizedIslands(float limit) {
    std::size_t split = 0;
    const std::size_t count = Shared::islands.size();
    for (std::size_t i = 0; i < count; ++i) {
        const Shared::Island_t island = Shared::islands[i];
        Shared::Mesh_t &source = Shared::meshes.at(island.mesh);
        if (CHECK_FLAG(source.shaderInfo->compileFlags, C_SKY)) continue;  // sky shells shrink to a constant
        const Vector2 size = island.bounds.maxs - island.bounds.mins;
        if (std::max(size.x(), size.y()) <= limit) continue;
        const int tilesX = static_cast<int>(std::ceil(size.x() / limit)), tilesY = static_cast<int>(std::ceil(size.y() / limit));
        std::map<std::pair<int, int>, Shared::Mesh_t> tiles;
        for (std::size_t t = 0; t + 2 < source.triangles.size(); t += 3) {
            const std::vector<Shared::Vertex_t> tri = {source.vertices[source.triangles[t]], source.vertices[source.triangles[t + 1]],
                                                       source.vertices[source.triangles[t + 2]]};
            for (int ty = 0; ty < tilesY; ++ty) for (int tx = 0; tx < tilesX; ++tx) {
                const float u0 = island.bounds.mins.x() + tx * limit, v0 = island.bounds.mins.y() + ty * limit;
                std::vector<Shared::Vertex_t> poly = tri;
                if (tx > 0) poly = ClipLightmap(poly, 0, u0, true);
                if (tx + 1 < tilesX && poly.size() >= 3) poly = ClipLightmap(poly, 0, u0 + limit, false);
                if (ty > 0 && poly.size() >= 3) poly = ClipLightmap(poly, 1, v0, true);
                if (ty + 1 < tilesY && poly.size() >= 3) poly = ClipLightmap(poly, 1, v0 + limit, false);
                if (poly.size() < 3) continue;
                Shared::Mesh_t &tile = tiles[{tx, ty}];
                if (tile.vertices.empty()) { tile.shaderInfo = source.shaderInfo; tile.lightmapPage = source.lightmapPage; }
                if (tile.vertices.size() + poly.size() > 65535) Error("Lightmap tile exceeds 16-bit mesh indices");
                const uint16_t base = static_cast<uint16_t>(tile.vertices.size());
                for (const auto &v : poly) { tile.vertices.push_back(v); tile.minmax.extend(v.xyz); }
                for (std::size_t k = 1; k + 1 < poly.size(); ++k) {
                    tile.triangles.push_back(base);
                    tile.triangles.push_back(static_cast<uint16_t>(base + k));
                    tile.triangles.push_back(static_cast<uint16_t>(base + k + 1));
                }
            }
        }
        if (tiles.size() < 2) continue;
        bool first = true;
        for (auto &[key, tile] : tiles) {
            Shared::Island_t part;
            for (const auto &v : tile.vertices) part.bounds.extend(v.lightmapUV);
            if (first) {
                part.mesh = island.mesh;
                Shared::meshes[island.mesh] = std::move(tile);
                Shared::islands[i] = part;
                first = false;
            } else {
                part.mesh = static_cast<int>(Shared::meshes.size());
                Shared::meshes.push_back(std::move(tile));
                Shared::islands.push_back(part);
            }
        }
        ++split;
    }
    return split;
}
} // namespace

void Shared::MakeLightmapUVs() {
    // Lightmap UVs stay in texel units here; writers normalize them once page
    // sizes are final.
    const float  limit = Shared::lightmapPageSize - 2.0f * Shared::lightmapGutter - 2.0f;
    if (const std::size_t split = SplitOversizedIslands(limit))
        Sys_Printf("%9zu lightmap islands larger than a page split into page-sized tiles\n", split);

    // Shelf packing wastes far less space with islands sorted tallest first.
    std::vector<const Shared::Island_t*>  order;
    for (const Shared::Island_t &island : Shared::islands)
        order.push_back(&island);
    // Meshes split per material and page, so maps with hundreds of materials can
    // pack material by material: each material then spans one or two pages.
    std::stable_sort(order.begin(), order.end(), [](const Shared::Island_t *a, const Shared::Island_t *b) {
        if (Shared::lightmapByMaterial) {
            const int order = std::strcmp(Shared::meshes.at(a->mesh).shaderInfo->shader.c_str(),
                                          Shared::meshes.at(b->mesh).shaderInfo->shader.c_str());
            if (order) return order < 0;
        }
        const float  ha = a->bounds.maxs.y() - a->bounds.mins.y(), hb = b->bounds.maxs.y() - b->bounds.mins.y();
        return ha > hb;
    });

    for (const Shared::Island_t *pIsland : order) {
        const Shared::Island_t &island = *pIsland;
        Shared::Mesh_t &mesh = Shared::meshes.at(island.mesh);
        Vector2  mins = island.bounds.mins, maxs = island.bounds.maxs;

        // Self-lit sky faces (e.g. the enclosing sky shell) bake to a constant,
        // so they need almost no lightmap resolution.
        if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_SKY)) {
            const float  sky = 1.0f / 64.0f;
            for (Shared::Vertex_t &vertex : mesh.vertices)
                vertex.lightmapUV = vertex.lightmapUV * sky;
            mins = mins * sky;
            maxs = maxs * sky;
        }

        // Shrink islands larger than a page instead of failing.
        const float  extent = std::max(maxs.x() - mins.x(), maxs.y() - mins.y());
        if (extent > limit) {
            const float  scale = limit / extent;
            for (Shared::Vertex_t &vertex : mesh.vertices)
                vertex.lightmapUV = vertex.lightmapUV * scale;
            mins = mins * scale;
            maxs = maxs * scale;
        }

        Respawn::LightmapPlacement  placement{};
        try {
            placement = Shared::lightmapAtlas.place({mins.x(), mins.y(), maxs.x(), maxs.y()});
        } catch (const std::exception &error) {
            Error("Lightmap packing failed: %s", error.what());
        }
        mesh.lightmapPage = placement.page;
        const Vector2  offset(static_cast<float>(placement.offsetX), static_cast<float>(placement.offsetY));
        for (Shared::Vertex_t &vertex : mesh.vertices)
            vertex.lightmapUV = vertex.lightmapUV + offset;
    }
}
