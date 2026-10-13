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
#include "titanfall.h"
#include "../respawn/encoding.h"

/*
    EmitTextureData()
    Emits texture data and returns its index
*/
uint32_t Titanfall::EmitTextureData(shaderInfo_t shader) {
    std::string  tex;
    try {
        tex = Respawn::textureName(shader.shader.c_str());
    } catch (const std::exception &error) {
        Error("EmitTextureData: \"%s\": %s", shader.shader.c_str(), error.what());
    }
    std::size_t  index;

    for (std::size_t i = 0; i < Titanfall::Bsp::textureData.size(); i++) {
        const auto &td = Titanfall::Bsp::textureData[i];
        const auto offset = Titanfall::Bsp::textureDataTable.at(td.name_index);
        if (Respawn::textureNameEquals(Titanfall::Bsp::textureDataData, offset, tex)) {
            return i;
        }
    }

    // Wasn't already saved, save it
    index = Titanfall::Bsp::textureData.size();

    // Add to Table
    StringOutputStream  data;
    data << tex.c_str();
    std::vector<char>  str = { data.begin(), data.end() + 1 };

    Titanfall::Bsp::textureDataTable.emplace_back(Titanfall::Bsp::textureDataData.size());
    Titanfall::Bsp::textureDataData.insert(Titanfall::Bsp::textureDataData.end(), str.begin(), str.end());

    Titanfall::TextureData_t &td = Titanfall::Bsp::textureData.emplace_back();
    td.name_index = Titanfall::Bsp::textureDataTable.size() - 1;
    td.sizeX = shader.shaderImage->width;
    td.sizeY = shader.shaderImage->height;
    td.visibleX = shader.shaderImage->width;
    td.visibleY = shader.shaderImage->height;
    td.flags = shader.surfaceFlags;

    return index;
}


/*
    EmitVertex
    Saves a vertex into Titanfall::vertices and returns its index
*/
uint32_t Titanfall::EmitVertex(Vector3 &vertex) {
    for (uint32_t i = 0; i < (uint32_t)Titanfall::Bsp::vertices.size(); i++) {
        if (VectorCompare(vertex, Titanfall::Bsp::vertices.at(i))) {
            return i;
        }
    }

    Titanfall::Bsp::vertices.emplace_back(vertex);
    return (uint32_t)Titanfall::Bsp::vertices.size() - 1;
}


/*
    EmitVertexNormal
    Saves a vertex normal into Titanfall::vertexNormals and returns its index
*/
uint32_t Titanfall::EmitVertexNormal(Vector3 &normal) {
    for (uint32_t i = 0; i < (uint32_t)Titanfall::Bsp::vertexNormals.size(); i++) {
        if (VectorCompare(normal, Titanfall::Bsp::vertexNormals.at(i)))
            return i;
    }

    Titanfall::Bsp::vertexNormals.emplace_back(normal);
    return (uint32_t)Titanfall::Bsp::vertexNormals.size() - 1;
}


void Titanfall::SetupGameLump() {
    Titanfall::Bsp::gameLumpHeader.version = 1;
    memcpy( &Titanfall::Bsp::gameLumpHeader.ident, "prps", 4 );
    Titanfall::Bsp::gameLumpHeader.gameConst = 786432;
}

/*
    EmitOcclusionMeshVertex
    Emits a vertex in occlusion vertices, checks for duplicates
*/
uint16_t Titanfall::EmitOcclusionMeshVertex( Vector3 vertex ) {
    for( std::size_t i = 0; i < Titanfall::Bsp::occlusionMeshVertices.size(); i++ ) {
        if( VectorCompare(vertex, Titanfall::Bsp::occlusionMeshVertices.at(i)) ) {
            return i;
        }
    }

    Titanfall::Bsp::occlusionMeshVertices.emplace_back(vertex);
    return Titanfall::Bsp::occlusionMeshVertices.size() - 1;
}

/*
    EmitOcclusionMeshes
    Emits mesh information for func_occluder
*/
void Titanfall::EmitOcclusionMeshes( const entity_t &entity ) {
    for( const brush_t &brush : entity.brushes ) {
        for( const side_t &side : brush.sides ) {
            // Skip bevels as they have no windings
            if( side.bevel )
                continue;

            // Skip degenerate windings as they contribute no faces
            if( side.winding.size() < 3 )
                continue;

            for (std::size_t i = 0; i < side.winding.size() - 2; i++) {
                for (int j = 0; j < 3; j++) {
                    int vertIndex = (j == 0) ? 0 : i + j;
                    uint16_t index = Titanfall::EmitOcclusionMeshVertex( side.winding.at(vertIndex) );
                    Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
                }
            }
        }
    }

    for( parseMesh_t *patch = entity.patches; patch != NULL; patch = patch->next ) {
        mesh_t patchMesh = patch->mesh;

        for( int x = 0; x < (patchMesh.width - 1); x++ ) {
            for( int y = 0; y < (patchMesh.height - 1); y++ ) {
                int vertIndex = x + y * patchMesh.width;

                uint16_t index;

                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex + patchMesh.width].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex + patchMesh.width + 1].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );

                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex + patchMesh.width + 1].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
                index = Titanfall::EmitOcclusionMeshVertex( patchMesh.verts[vertIndex + 1].xyz );
                Titanfall::Bsp::occlusionMeshIndices.emplace_back( index );
            }
        }
    }
}

/*
    EmitObjReferences
    Emits obj references and returns an index to the first one
*/
std::size_t Titanfall::EmitObjReferences(Shared::visNode_t &node) {
    // Stores which indicies were found
    std::list<std::size_t>  indicies;
    // Try to check for duplicates
    for (Shared::visRef_t &ref : node.refs) {
        for (std::size_t i = 0; i < Titanfall::Bsp::objReferences.size(); i++) {
            uint16_t &tf = Titanfall::Bsp::objReferences.at(i);
            if (tf == ref.index) {
                indicies.push_back(i);
            }
        }
    }
    indicies.sort();

    // We found all, now check if they're next to each other
    if (indicies.size() == node.refs.size()) {
        std::size_t  lastIndex = -1;
        for (std::size_t &i : indicies) {
            if (lastIndex == -1) {
                lastIndex = i;
                continue;
            }

            if (i != lastIndex + 1) {
                lastIndex = -1;
                break;
            }
        }

        if (lastIndex != -1) {
            return indicies.front();
        }
    }

    for (Shared::visRef_t &ref : node.refs) {
        Titanfall::ObjReferenceBounds_t &rb = Titanfall::Bsp::objReferenceBounds.emplace_back();
        rb.maxs = ref.minmax.maxs;
        rb.mins = ref.minmax.mins;

        Titanfall::Bsp::objReferences.emplace_back(ref.index);
    }

    return Titanfall::Bsp::objReferences.size() - node.refs.size();
}


/*
    GetTotalVisRefCount
    Calculates the total number of obj refs under a vistree node
*/
uint16_t GetTotalVisRefCount(Shared::visNode_t node) {
    uint16_t  count = node.refs.size();

    for (Shared::visNode_t &n : node.children) {
        count += GetTotalVisRefCount(n);
    }

    return count;
}


/*
    GetTotalVisNodeChildCount
    Calculates the total child count of node
*/
uint16_t GetTotalVisNodeChildCount(Shared::visNode_t node) {
    uint16_t  count = node.children.size();

    for (Shared::visNode_t &n : node.children) {
        count += GetTotalVisNodeChildCount(n);
    }

    return count;
}


/*
    EmitVisChildrenOfTreeNode
    Emits children of a vis tree node
*/
int Titanfall::EmitVisChildrenOfTreeNode(Shared::visNode_t node) {
    int  index = Titanfall::Bsp::cellAABBNodes.size();  // Index of first child of node

    for (std::size_t i = 0; i < node.children.size(); i++) {
        Shared::visNode_t &n = node.children.at(i);

        Titanfall::CellAABBNode_t &bn = Titanfall::Bsp::cellAABBNodes.emplace_back();
        bn.maxs = n.minmax.maxs;
        bn.mins = n.minmax.mins;
        bn.childCount = n.children.size();
        bn.totalRefCount = GetTotalVisRefCount(n);

        if (n.refs.size()) {
            bn.objRef = Titanfall::EmitObjReferences(n);
            bn.objRefCount = n.refs.size();
        }
    }

    for (std::size_t i = 0; i < node.children.size(); i++) {
        int  firstChild = EmitVisChildrenOfTreeNode(node.children.at(i));

        Titanfall::CellAABBNode_t &bn = Titanfall::Bsp::cellAABBNodes.at(index + i);
        bn.firstChild = firstChild;
    }

    return index;
}


/*
    EmitVisTree
    Emits vistree
*/
void Titanfall::EmitVisTree() {
    Shared::visNode_t &root = Shared::visRoot;

    Titanfall::CellAABBNode_t &bn = Titanfall::Bsp::cellAABBNodes.emplace_back();
    bn.maxs = root.minmax.maxs;
    bn.mins = root.minmax.mins;
    bn.firstChild = Titanfall::Bsp::cellAABBNodes.size();
    bn.childCount = root.children.size();
    bn.totalRefCount = GetTotalVisRefCount(root);
    if (root.refs.size()) {
        bn.objRef = EmitObjReferences(root);
        bn.objRefCount = root.refs.size();
    }

    EmitVisChildrenOfTreeNode(Shared::visRoot);
}


/*
    EmitVertexUnlit
    Saves a vertex into Titanfall::Bsp::vertexUnlitVertices
*/
void Titanfall::EmitVertexUnlit(Shared::Vertex_t &vertex) {
    Titanfall::VertexUnlit_t &ul = Titanfall::Bsp::vertexUnlitVertices.emplace_back();
    ul.vertexIndex = Titanfall::EmitVertex(vertex.xyz);
    ul.normalIndex = Titanfall::EmitVertexNormal(vertex.normal);
    ul.textureUV   = vertex.textureUV;
    ul.colour      = vertex.colour;
}


/*
    EmitVertexLitFlat
    Saves a vertex into Titanfall::Bsp::vertexLitFlatVertices
*/
void Titanfall::EmitVertexLitFlat(Shared::Vertex_t &vertex) {
    Titanfall::VertexLitFlat_t &lf = Titanfall::Bsp::vertexLitFlatVertices.emplace_back();
    lf.vertexIndex  = Titanfall::EmitVertex(vertex.xyz);
    lf.normalIndex  = Titanfall::EmitVertexNormal(vertex.normal);
    lf.textureUV    = vertex.textureUV;
    lf.colour       = vertex.colour;
    lf.lightmapUV   = vertex.lightmapUV;
    lf.lightmapStep = vertex.lightmapStep;
}


/*
    EmitVertexLitBump
    Saves a vertex into Titanfall::Bsp::vertexLitBumpVertices
*/
void Titanfall::EmitVertexLitBump(Shared::Vertex_t &vertex, uint32_t tangent) {
    Titanfall::VertexLitBump_t &lv = Titanfall::Bsp::vertexLitBumpVertices.emplace_back();
    lv.vertexIndex  = Titanfall::EmitVertex(vertex.xyz);
    lv.normalIndex  = Titanfall::EmitVertexNormal(vertex.normal);
    lv.textureUV    = vertex.textureUV;
    lv.colour       = vertex.colour;
    lv.lightmapUV   = vertex.lightmapUV;
    lv.lightmapStep = vertex.lightmapStep;
    lv.tangentIndex[0] = tangent;
    lv.tangentIndex[1] = 0;
}


/*
    EmitVertexUnlitTS
    Saves a vertex into Titanfall::Bsp::vertexUnlitTSVertices
*/
void Titanfall::EmitVertexUnlitTS(Shared::Vertex_t &vertex, uint32_t tangent) {
    Titanfall::VertexUnlitTS_t &ul = Titanfall::Bsp::vertexUnlitTSVertices.emplace_back();
    ul.vertexIndex = Titanfall::EmitVertex(vertex.xyz);
    ul.normalIndex = Titanfall::EmitVertexNormal(vertex.normal);
    ul.textureUV   = vertex.textureUV;
    ul.colour      = vertex.colour;
    ul.tangentIndex[0] = tangent;
    ul.tangentIndex[1] = 0;
}


/*
    EmitVertexBlinnPhong
    Saves a vertex into Titanfall::Bsp::vertexBlinnPhongVertices
*/
void Titanfall::EmitVertexBlinnPhong(Shared::Vertex_t &vertex) {
    Titanfall::VertexBlinnPhong_t &bp = Titanfall::Bsp::vertexBlinnPhongVertices.emplace_back();
    bp.vertexIndex = Titanfall::EmitVertex(vertex.xyz);
    bp.normalIndex = Titanfall::EmitVertexNormal(vertex.normal);
    bp.textureUV   = vertex.textureUV;
    bp.colour      = vertex.colour;
    bp.lightmapUV  = vertex.lightmapUV;
    // TODO: tangentQuaternion
}


/*
    MeshTangents()
    Tangent references for normal-mapped vertices, as retail Coliseum/Glitch
    store them: the vertex-normal index of a unit tangent along +dP/du with the
    normal component removed, and bit 31 set when the bitangent runs against
    +dP/dv. The second tangent word is always zero.
*/
static std::vector<uint32_t> MeshTangents(const Shared::Mesh_t &mesh) {
    std::vector<Vector3>  du(mesh.vertices.size(), Vector3(0, 0, 0)), dv(mesh.vertices.size(), Vector3(0, 0, 0));
    for (std::size_t i = 0; i + 2 < mesh.triangles.size(); i += 3) {
        const uint16_t  t[3] = {mesh.triangles[i], mesh.triangles[i + 1], mesh.triangles[i + 2]};
        const Shared::Vertex_t &a = mesh.vertices.at(t[0]), &b = mesh.vertices.at(t[1]), &c = mesh.vertices.at(t[2]);
        const Vector3  e1 = b.xyz - a.xyz, e2 = c.xyz - a.xyz;
        const Vector2  d1 = b.textureUV - a.textureUV, d2 = c.textureUV - a.textureUV;
        const float  det = d1.x() * d2.y() - d1.y() * d2.x();
        if (std::fabs(det) < 1e-12f)
            continue;
        const Vector3  s = (e1 * d2.y() - e2 * d1.y()) / det;
        const Vector3  u = (e2 * d1.x() - e1 * d2.x()) / det;
        for (uint16_t k : t) {
            du[k] += s;
            dv[k] += u;
        }
    }

    std::vector<uint32_t>  words;
    for (std::size_t i = 0; i < mesh.vertices.size(); i++) {
        const Vector3  n = mesh.vertices[i].normal;
        Vector3  tangent = du[i] - n * static_cast<float>(vector3_dot(n, du[i]));
        if (vector3_length(tangent) < 1e-6) {  // no usable UV gradient
            const Vector3  axis = std::fabs(n.z()) < 0.9f ? Vector3(0, 0, 1) : Vector3(0, 1, 0);
            tangent = vector3_cross(axis, n);
        }
        tangent = vector3_normalised(tangent);
        const bool  mirrored = vector3_dot(vector3_cross(n, tangent), dv[i]) < 0;
        words.push_back(Titanfall::EmitVertexNormal(tangent) | (mirrored ? 0x80000000u : 0u));
    }
    return words;
}


/*
    EmitMeshes()
    writes the mesh list to the bsp
*/
void Titanfall::EmitMeshes(const entity_t &e) {
    // ALSO: TextureData, TextureDataStringData, TextureDataStringTable, MaterialSort,
    // -- VertexReservedX, Vertices, VertexNormals & MeshBounds
    // NOTE: we don't actually build meshes from const entity_t &e
    // -- Shared::meshes has every mesh from brushes & patches built & merged before EmitMeshes get called

    // Emit Bsp::meshes
    for (const Shared::Mesh_t &mesh : Shared::meshes) {
        if (mesh.vertices.empty() || mesh.vertices.size() > 65536 || mesh.triangles.size() / 3 > 65535)
            Error("Mesh vertex or triangle count exceeds its 16-bit field");
        Titanfall::Mesh_t &m = Titanfall::Bsp::meshes.emplace_back();
        m.const0 = 4294967040;  // :)
        m.flags = mesh.shaderInfo->surfaceFlags;
        // Engine surface/decal queries iterate through this index inclusively.
        m.vertexCount = mesh.vertices.size() - 1;
        m.triOffset = Titanfall::Bsp::meshIndices.size();
        m.triCount = mesh.triangles.size() / 3;

        int vertexOffset = 0;

        if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_VERTEX_UNLIT_TS)) {
            m.vertexType = 3;
            vertexOffset = Titanfall::Bsp::vertexUnlitTSVertices.size();
        } else if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags,S_VERTEX_LIT_BUMP)) {
            m.vertexType = 2;
            vertexOffset = Titanfall::Bsp::vertexLitBumpVertices.size();
        } else if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_VERTEX_UNLIT)) {
            m.vertexType = 1;
            vertexOffset = Titanfall::Bsp::vertexUnlitVertices.size();
        } else {
            m.vertexType = 0;
            vertexOffset = Titanfall::Bsp::vertexLitFlatVertices.size();
        }

        // Emit texture related structs
        uint32_t  textureIndex = Titanfall::EmitTextureData(*mesh.shaderInfo);
        // Lit meshes sample the lightmap page their material sort points at.
        const bool  baked = Shared::lightmapsEnabled && (m.vertexType == 0 || m.vertexType == 2)
                         && mesh.lightmapPage >= 0;
        m.materialOffset = Titanfall::EmitMaterialSort(textureIndex, vertexOffset, mesh.vertices.size(),
                                                       baked ? mesh.lightmapPage : -1);
        int materialSortOffset = Titanfall::Bsp::materialSorts.at(m.materialOffset).vertexOffset;
        // Both surface queries and triangle indices add the material-sort base.
        m.vertexOffset = vertexOffset - materialSortOffset;
        MinMax  aabb;

        // Save vertices and vertexnormals
        const std::vector<uint32_t>  tangents = (m.vertexType == 2 || m.vertexType == 3)
                                              ? MeshTangents(mesh) : std::vector<uint32_t>();
        for (std::size_t i = 0; i < mesh.vertices.size(); i++) {
            Shared::Vertex_t  vertex = mesh.vertices.at(i);

            aabb.extend(vertex.xyz);

            if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_VERTEX_UNLIT_TS)) {
                Titanfall::EmitVertexUnlitTS(vertex, tangents.at(i));
            } else if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_VERTEX_LIT_BUMP)) {
                Titanfall::EmitVertexLitBump(vertex, tangents.at(i));
            } else if (CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_VERTEX_UNLIT)) {
                Titanfall::EmitVertexUnlit(vertex);
            } else {
                Titanfall::EmitVertexLitFlat(vertex);
            }
        }

        // Save triangles
        for (uint16_t triangle : mesh.triangles) {
            // The pool offset can exceed 16 bits; indices are relative to the sort.
            const int index = triangle + vertexOffset - materialSortOffset;
            if (index < 0 || index > 65535)
                Error("Mesh index exceeds the 16-bit material-sort range");
            Titanfall::Bsp::meshIndices.emplace_back(index);
        }
        // The runtime reads triangles in pairs: like retail (Angel City, Homestead),
        // follow odd-sized meshes with a degenerate triangle so every mesh starts on
        // a six-index boundary. Unpadded, grenade decals read the next mesh's indices
        // and crashed at engine.dll+0xae8d3. triCount keeps the real count.
        if (m.triCount & 1) {
            const uint16_t last = Titanfall::Bsp::meshIndices.back();
            Titanfall::Bsp::meshIndices.insert(Titanfall::Bsp::meshIndices.end(), 3, last);
        }

        // Save MeshBounds
        Titanfall::MeshBounds_t &mb = Titanfall::Bsp::meshBounds.emplace_back();
        mb.origin = (aabb.maxs + aabb.mins) / 2;
        mb.extents = (aabb.maxs - aabb.mins) / 2;
        mb.radius = vector3_length(mb.extents);
        mb.tanYaw = 0.0f;

        if (baked) {
            Respawn::Bake::Chart &chart = Titanfall::Bsp::lightmapCharts.emplace_back();
            chart.page = mesh.lightmapPage;
            // Textured sky (e.g. Quake sky faces drawn as world geometry) glows
            // at a constant level instead of being lit, like a sky dome.
            if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_SKY))
                chart.constant = 1.0;
            // Bounce albedo: the texture's average colour, linearised and kept to a
            // plausible diffuse range (q3map2 averages 0-255 pixels, or a 0-1 colour).
            const Color4f &average = mesh.shaderInfo->averageColor;
            const float range = std::max({average[0], average[1], average[2]}) > 1.0f ? 255.0f : 1.0f;
            if (average[0] + average[1] + average[2] > 0.0f) {
                auto linear = [&](float c) { return std::clamp(std::pow(c / range, 2.2), 0.02, 0.9); };
                chart.albedo = {linear(average[0]), linear(average[1]), linear(average[2])};
            }
            for (const Shared::Vertex_t &vertex : mesh.vertices) {
                chart.positions.push_back({vertex.xyz.x(), vertex.xyz.y(), vertex.xyz.z()});
                chart.normals.push_back({vertex.normal.x(), vertex.normal.y(), vertex.normal.z()});
                chart.luxels.push_back({vertex.lightmapUV.x(), vertex.lightmapUV.y()});
            }
            chart.triangles.assign(mesh.triangles.begin(), mesh.triangles.end());
            Titanfall::Bsp::lightmapVertexRanges.push_back({m.vertexType == 2, static_cast<std::size_t>(vertexOffset),
                                                           mesh.vertices.size(), static_cast<std::uint32_t>(mesh.lightmapPage)});
        }
    }
}


/*
    EmitMaterialSort()
    Tries to create a material sort of the last texture
*/
uint16_t Titanfall::EmitMaterialSort(uint32_t index, int offset, int count, int lightmapHeader) {
    if (index > 32767)
        Error("Material-sort texture index exceeds its signed 16-bit field");
    /* Check if the material sort we need already exists */
    std::size_t pos = 0;
    for (Titanfall::MaterialSort_t &ms : Titanfall::Bsp::materialSorts) {
        if (ms.textureData == index && ms.lightmapHeader == lightmapHeader
         && offset >= ms.vertexOffset && offset - ms.vertexOffset + count <= 65536) {
            return pos;
        }

        pos++;
    }

    if (pos > 65535)
        Error("Material-sort index exceeds 16 bits");
    Titanfall::MaterialSort_t &ms = Titanfall::Bsp::materialSorts.emplace_back();
    ms.textureData = index;
    ms.lightmapHeader = lightmapHeader;
    ms.cubemap = -1;
    ms.vertexOffset = offset;

    return pos;
}

/*
    EmitLevelInfoWorldspawn()
*/
void Titanfall::EmitLevelInfoWorldspawn() {
    Titanfall::LevelInfo_t &li = Titanfall::Bsp::levelInfo.emplace_back();

    // Mest indicies
    li.firstDecalMeshIndex = 0;
    for (Shared::Mesh_t &mesh : Shared::meshes) {
        if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_DECAL)) { break; }
            li.firstDecalMeshIndex++;
    }

    // TODO: start from firstDecalMeshIndex
    li.firstTransMeshIndex = 0;
    for (Shared::Mesh_t &mesh : Shared::meshes) {
        if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_TRANSLUCENT)) { break; }
            li.firstTransMeshIndex++;
    }

    // TODO: start from firstTransMeshIndex
    li.firstSkyMeshIndex = 0;
    for (Shared::Mesh_t &mesh : Shared::meshes) {
        if (CHECK_FLAG(mesh.shaderInfo->compileFlags, C_SKY) && CHECK_FLAG(mesh.shaderInfo->surfaceFlags, S_SKY)) { break; }
            li.firstSkyMeshIndex++;
    }

    if( li.firstTransMeshIndex > li.firstSkyMeshIndex )
        li.firstTransMeshIndex = li.firstSkyMeshIndex;

    if( li.firstDecalMeshIndex > li.firstTransMeshIndex )
        li.firstDecalMeshIndex = li.firstTransMeshIndex;
}

/*
    EmitStaticProp()
    Emits a static prop
*/
void Titanfall::EmitStaticProp(entity_t &e) {
    const char *model = e.valueForKey("model");
    int16_t pathIdx = -1;
    MinMax minmax;

    std::vector<const AssMeshWalker*> meshes = LoadModelWalker( model, 0 );
    if(meshes.empty()) {
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
        Titanfall::Bsp::gameLumpPathHeader.numPaths++;
        Titanfall::GameLumpPath_t &path = Titanfall::Bsp::gameLumpPaths.emplace_back();
        strncpy(path.path, model, 127);
        pathIdx = Titanfall::Bsp::gameLumpPaths.size() - 1;
    }

    Titanfall::Bsp::gameLumpPropHeader.numProps++;
    Titanfall::Bsp::gameLumpPropHeader.unk1++;
    Titanfall::GameLumpProp_t &prop = Titanfall::Bsp::gameLumpProps.emplace_back();
    Vector3 origin;
    Vector3 angles;
    if(!e.read_keyvalue(origin, "origin")) {
        origin.x() = 0.0f;
        origin.y() = 0.0f;
        origin.z() = 0.0f;
    }
    if(!e.read_keyvalue(angles, "angles")) {
        angles.x() = 0.0f;
        angles.y() = 0.0f;
        angles.z() = 0.0f;
    }

    prop.origin = origin;
    prop.angles = angles;
    prop.scale = 1.0f;
    prop.modelName = pathIdx;
    prop.solid = 6;
    prop.flags = 4;
    prop.envCubemap = -1;
    prop.forcedFadeScale = -1.0f;
    prop.cpuLevel[0] = -1.0f;
    prop.cpuLevel[1] = -1.0f;
    prop.gpuLevel[0] = -1.0f;
    prop.gpuLevel[1] = -1.0f;
    prop.lightingOrigin.x() = 1.0f;
    prop.lightingOrigin.y() = 1.0f;
    prop.lightingOrigin.z() = 1.0f;
    prop.disableX360 = -1;

    for ( const auto mesh : meshes )
    {
        mesh->forEachFace( [&minmax, &origin]( const Vector3 ( &xyz )[3], const Vector2 ( &st )[3] ){
                        minmax.extend(xyz[0] + origin);
            minmax.extend(xyz[1] + origin);
            minmax.extend(xyz[2] + origin);
                } );
    }

    Shared::visRef_t &ref = Shared::visRefs.emplace_back();

    ref.minmax = minmax;
    ref.index = Titanfall::Bsp::models.at(0).meshCount + Titanfall::Bsp::gameLumpProps.size() - 1;
}

/*
    EmitLevelInfo()
*/
void Titanfall::EmitLevelInfo() {
    Titanfall::LevelInfo_t &li = Titanfall::Bsp::levelInfo.back();

    li.propCount = Titanfall::Bsp::gameLumpPropHeader.numProps;
    // TODO: unk2 sun vector from last light_environment
    li.unk2 = { 0.1, 0.8, -0.6 };  // placeholder
}
