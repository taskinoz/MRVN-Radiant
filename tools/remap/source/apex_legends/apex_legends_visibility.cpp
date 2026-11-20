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
    Apex Legends Visibility/Cell Lumps

    This file handles visibility and cell-related BSP lumps:
    - Cell AABB Nodes lump (0x77): BVH nodes for visibility culling
    - Object References lump (0x78): Object reference indices
    - Object Reference Bounds lump (0x79): Bounds per object reference
    - Cell AABB Num Obj Refs Total lump (0x25): Cumulative obj ref count per node
    - Cell AABB Fade Dists lump (0x27): Fade distances for LOD/streaming
*/

#include <functional>
#include <unordered_map>
#include "../remap.h"
#include "../bspfile_abstract.h"
#include "../model.h"

/*
    EmitVisTree
    Object visibility tree: cell AABB nodes (0x77), object references (0x78),
    their bounds (0x79), per-internal-node subtree totals (0x25) and a u16 per
    node (0x27). Layout measured from retail S3 mp_rr_aqueduct:
    - one root per cell at node index = cell index (one cell here: node 0);
    - internal nodes first, then leaves; a node's children are contiguous and
      either all internal or all leaves (never mixed);
    - word at +0x0C: child count | first child << 8 | (0x40 << 24 if internal);
      word at +0x1C: own reference count | first reference << 8 | 0x40 << 24;
    - references are in depth-first order, so a subtree's references are
      contiguous from its node's first reference; 0x25[i] is the subtree total;
    - 0x27 is 0xFFFF or 0 per node in retail; 0xFFFF is written.
    Object ids: world meshes by index, static props from the 64-aligned prop
    base (LEVEL_INFO). The fork wrote one +/-50000 root holding every
    reference in an 8-bit count, which drops objects past 255.
*/
namespace {
struct VisTreeNode {
    MinMax bounds;
    std::vector<uint32_t> refs;          // indices into the id/bounds tables
    std::vector<VisTreeNode> children;
};

VisTreeNode ConvertVisNode(const Shared::visNode_t &node) {
    VisTreeNode out;
    out.bounds = node.minmax;
    for (const Shared::visRef_t &ref : node.refs) out.refs.push_back(ref.index);
    for (const Shared::visNode_t &child : node.children) out.children.push_back(ConvertVisNode(child));
    return out;
}

bool IsLeafNode(const VisTreeNode &node) { return node.children.empty(); }

// No child block mixes leaves and internal nodes: wrap leaf children of a
// node that also has internal children in single-child internal nodes.
void NormaliseVisNode(VisTreeNode &node) {
    for (VisTreeNode &child : node.children) NormaliseVisNode(child);
    bool anyInternal = false, anyLeaf = false;
    for (const VisTreeNode &child : node.children) (IsLeafNode(child) ? anyLeaf : anyInternal) = true;
    if (!(anyInternal && anyLeaf)) return;
    for (VisTreeNode &child : node.children) {
        if (!IsLeafNode(child)) continue;
        VisTreeNode wrapper;
        wrapper.bounds = child.bounds;
        wrapper.children.push_back(std::move(child));
        child = std::move(wrapper);
    }
}
}

void ApexLegends::EmitVisTree() {
    ApexLegends::Bsp::cellAABBNodes.clear();
    ApexLegends::Bsp::objReferences.clear();
    ApexLegends::Bsp::objReferenceBounds.clear();
    ApexLegends::Bsp::cellAABBNumObjRefsTotal.clear();
    ApexLegends::Bsp::cellAABBFadeDists.clear();

    // Object table: world meshes, then static props.
    std::vector<uint32_t> ids;
    std::vector<MinMax> bounds;
    std::vector<Shared::visRef_t> refs;
    auto add = [&](uint32_t id, const MinMax &box) {
        if (!box.valid()) return;
        if (refs.size() >= 0xFFFF) Error("More than 65535 visibility objects");
        Shared::visRef_t &ref = refs.emplace_back();
        ref.index = static_cast<uint16_t>(ids.size());
        ref.minmax = box;
        ids.push_back(id);
        bounds.push_back(box);
    };
    for (std::size_t i = 0; i < Shared::meshes.size(); i++) {
        MinMax box = Shared::meshes[i].minmax;
        box.mins -= Vector3(1.0f);
        box.maxs += Vector3(1.0f);
        add(static_cast<uint32_t>(i), box);
    }
    const uint32_t firstPropObjID = (static_cast<uint32_t>(Shared::meshes.size()) + 63) & ~63u;
    for (const auto &[propIndex, box] : ApexLegends::Bsp::staticPropShadowBounds) add(firstPropObjID + propIndex, box);

    VisTreeNode root;
    if (!refs.empty()) {
        Shared::visNode_t shared = Shared::MakeVisTree(refs, 1e30f);
        root = ConvertVisNode(shared);
    }
    // The root must be internal so that it sits at node 0 with 0x25[0].
    if (IsLeafNode(root)) {
        VisTreeNode leaf = std::move(root);
        root = VisTreeNode();
        root.bounds = leaf.bounds;
        root.children.push_back(std::move(leaf));
    }
    if (!root.bounds.valid()) {
        root.bounds.extend(Vector3(-1, -1, -1));
        root.bounds.extend(Vector3(1, 1, 1));
    }
    NormaliseVisNode(root);

    // Node indices: internal nodes breadth-first from the root, then leaf
    // blocks in the order their parents were visited.
    std::vector<const VisTreeNode *> internal{&root}, leaves;
    std::vector<std::pair<std::size_t, bool>> firstChild;  // per internal node: block start, leaf block?
    for (std::size_t i = 0; i < internal.size(); i++) {
        const VisTreeNode &node = *internal[i];
        const bool leafBlock = IsLeafNode(node.children.front());
        firstChild.emplace_back(leafBlock ? leaves.size() : internal.size(), leafBlock);
        for (const VisTreeNode &child : node.children) (leafBlock ? leaves : internal).push_back(&child);
    }
    const std::size_t leafBase = internal.size();
    const std::size_t nodeCount = internal.size() + leaves.size();
    if (nodeCount > 0xFFFF) Error("Visibility tree has more than 65535 nodes");

    // References depth-first; each node's own references precede its subtree's.
    std::unordered_map<const VisTreeNode *, std::pair<uint32_t, uint32_t>> span;  // first ref, subtree total
    std::function<void(const VisTreeNode &)> order = [&](const VisTreeNode &node) {
        const uint32_t first = static_cast<uint32_t>(ApexLegends::Bsp::objReferences.size());
        for (uint32_t r : node.refs) {
            ApexLegends::Bsp::objReferences.push_back(static_cast<int32_t>(ids[r]));
            Titanfall::ObjReferenceBounds_t &rb = ApexLegends::Bsp::objReferenceBounds.emplace_back();
            rb.mins = bounds[r].mins;
            rb.maxs = bounds[r].maxs;
        }
        for (const VisTreeNode &child : node.children) order(child);
        span[&node] = {first, static_cast<uint32_t>(ApexLegends::Bsp::objReferences.size()) - first};
    };
    order(root);
    if (ApexLegends::Bsp::objReferences.size() > 0xFFFF) Error("Visibility tree has more than 65535 references");

    ApexLegends::Bsp::cellAABBNodes.resize(nodeCount);
    auto write = [&](const VisTreeNode &node, std::size_t index, bool isInternal, std::size_t internalIndex) {
        ApexLegends::CellAABBNode_t &out = ApexLegends::Bsp::cellAABBNodes[index];
        out.mins = node.bounds.mins;
        out.maxs = node.bounds.maxs;
        if (node.refs.size() > 0xFF) Error("Visibility node has more than 255 references");
        out.objRefCount = static_cast<uint32_t>(node.refs.size());
        out.objRefOffset = span[&node].first;
        out.objRefFlags = 0x40;
        if (isInternal) {
            const auto &[start, leafBlock] = firstChild[internalIndex];
            out.childCount = static_cast<uint32_t>(node.children.size());
            out.firstChild = static_cast<uint32_t>(leafBlock ? leafBase + start : start);
            out.childFlags = 0x40;
        } else {
            out.childCount = 0;
            out.firstChild = 0;
            out.childFlags = 0;
        }
    };
    for (std::size_t i = 0; i < internal.size(); i++) {
        write(*internal[i], i, true, i);
        ApexLegends::Bsp::cellAABBNumObjRefsTotal.push_back(span[internal[i]].second);
    }
    for (std::size_t i = 0; i < leaves.size(); i++) write(*leaves[i], leafBase + i, false, 0);
    ApexLegends::Bsp::cellAABBFadeDists.assign(nodeCount, 0xFFFF);

    Sys_Printf("  vis tree: %zu nodes (%zu internal), %zu object references\n",
               nodeCount, internal.size(), ApexLegends::Bsp::objReferences.size());
}

/*
    EmitObjReferences
    Emits object references to the BSP
    
    This function emits object references for a visibility node.
*/
std::size_t ApexLegends::EmitObjReferences(Shared::visNode_t &node) {
    for (Shared::visRef_t &ref : node.refs) {
        Titanfall::ObjReferenceBounds_t &rb = ApexLegends::Bsp::objReferenceBounds.emplace_back();
        rb.maxs = ref.minmax.maxs;
        rb.mins = ref.minmax.mins;

        ApexLegends::Bsp::objReferences.emplace_back(ref.index);
    }

    return ApexLegends::Bsp::objReferences.size() - node.refs.size();
}

/*
    EmitVisChildrenOfTreeNode
    Emits visibility tree children recursively
    
    This function builds the visibility tree structure by recursively
    emitting child nodes.
*/
int ApexLegends::EmitVisChildrenOfTreeNode(Shared::visNode_t node) {
    int index = ApexLegends::Bsp::cellAABBNodes.size();  // Index of first child of node

    for (std::size_t i = 0; i < node.children.size(); i++) {
        Shared::visNode_t &n = node.children.at(i);

        ApexLegends::CellAABBNode_t &bn = ApexLegends::Bsp::cellAABBNodes.emplace_back();
        bn.maxs = n.minmax.maxs;
        bn.mins = n.minmax.mins;
        bn.childCount = n.children.size();
        bn.firstChild = 0;  // Will be set later if there are children
        bn.childFlags = 0x40;
        
        // Initialize objRef fields - must be explicitly zeroed
        bn.objRefCount = 0;
        bn.objRefOffset = 0;
        bn.objRefFlags = 0;

        if (n.refs.size()) {
            bn.objRefOffset = ApexLegends::EmitObjReferences(n);
            bn.objRefCount = n.refs.size();
            bn.objRefFlags = 0x40;
        }
    }

    for (std::size_t i = 0; i < node.children.size(); i++) {
        int firstChild = ApexLegends::EmitVisChildrenOfTreeNode(node.children.at(i));

        ApexLegends::CellAABBNode_t &bn = ApexLegends::Bsp::cellAABBNodes.at(index + i);
        if (node.children.at(i).children.size() > 0) {
            bn.firstChild = firstChild;
        }
    }

    return index;
}
