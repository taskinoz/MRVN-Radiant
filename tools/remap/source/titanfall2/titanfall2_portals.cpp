/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Original TF2 serialization over NetRadiant's existing brush BSP/portal builder.
 * Record facts and retail measurements: docs/respawn/RESPAWN_TRICOLL_PORTALS.md.
 */
#include "../remap.h"
#include "../bspfile_shared.h"
#include "titanfall2.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <functional>
#include <map>
#include <set>
#include <tuple>
#include <unordered_map>
#include <unordered_set>

namespace {
namespace B = Titanfall::Bsp;
using Key = std::tuple<long long, long long, long long>;
using Pair = std::pair<uint16_t, uint16_t>;

uint32_t PortalPlane(const Plane3f &plane) {
    for (std::size_t i = 0; i < B::planes.size(); ++i) {
        const auto &p = B::planes[i];
        if (p.a == plane.a && p.b == plane.b && p.c == plane.c && p.d == plane.d) return i;
    }
    B::planes.push_back(plane);
    return B::planes.size() - 1;
}

Titanfall::IndexSet_t IndexSet(const std::array<int16_t, 8> &v) {
    return {v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]};
}

struct PortalGeometry {
    std::map<Key, uint16_t> points;
    std::map<Pair, uint16_t> edges;
    std::vector<std::vector<int16_t>> incident{1};

    uint16_t Vertex(const Vector3 &p) {
        Key key{std::llround(p.x() * 1024.0), std::llround(p.y() * 1024.0), std::llround(p.z() * 1024.0)};
        auto found = points.find(key);
        if (found != points.end()) return found->second;
        if (B::portalVertices_stub.size() > 32767) Error("Portal vertex index exceeds signed intersection field");
        const uint16_t id = B::portalVertices_stub.size();
        B::portalVertices_stub.push_back(p);
        incident.emplace_back();
        points.emplace(key, id);
        return id;
    }

    uint16_t Edge(uint16_t a, uint16_t b) {
        const Pair key = std::minmax(a, b);
        auto found = edges.find(key);
        uint16_t id;
        if (found == edges.end()) {
            if (edges.size() > 32767) Error("Portal edge index exceeds signed intersection field");
            id = edges.size();
            edges.emplace(key, id);
            B::portalEdges_stub.push_back(key.first);
            B::portalEdges_stub.push_back(key.second);
            incident[a].push_back(id);
            incident[b].push_back(id);
        } else id = found->second;
        return (id << 1) | (a > b ? 1 : 0);
    }

    Titanfall::Portal_t Polygon(const winding_t &winding, const Plane3f &plane) {
        if (winding.size() < 3 || winding.size() > 255) Error("Portal polygon vertex count is outside 3..255");
        std::vector<Vector3> points(winding.begin(), winding.end());
        Vector3 area(0);
        for (std::size_t i = 1; i + 1 < points.size(); ++i)
            area += vector3_cross(points[i] - points[0], points[i + 1] - points[0]);
        const double facing = vector3_dot(area, plane.normal());
        if (!std::isfinite(facing) || std::abs(facing) < 1e-8) Error("Degenerate portal polygon");
        // Retail polygons retain positive plane winding for BOTH directed records.
        if (facing < 0) std::reverse(points.begin(), points.end());
        Titanfall::Portal_t out{};
        out.refCount = points.size();
        if (B::portalVertexReferences_stub.size() + points.size() > 65535) Error("Portal reference offset exceeds 16 bits");
        out.firstRef = B::portalVertexReferences_stub.size();
        out.plane = PortalPlane(plane);
        std::vector<uint16_t> vertices;
        for (const auto &p : points) vertices.push_back(Vertex(p));
        for (std::size_t i = 0; i < vertices.size(); ++i) {
            const auto previous = vertices[(i + vertices.size() - 1) % vertices.size()];
            if (previous == vertices[i]) Error("Portal polygon has a collapsed edge");
            B::portalVertexReferences_stub.push_back(vertices[i]);
            // Each reference describes the edge arriving at this polygon vertex.
            B::portalEdgeReferences_stub.push_back(Edge(previous, vertices[i]));
        }
        return out;
    }

    void Finish() {
        // The native edge table represents maximal collinear segments. Brush
        // splits produce overlapping subsegments; retaining those separately
        // can overflow the eight incidence slots even for a simple doorway.
        using Line = std::array<long long, 6>;
        struct Segment { double lo, hi; uint16_t a, b, old; bool reverse; };
        std::map<Line, std::vector<Segment>> lines;
        for (std::size_t e = 0; e < edges.size(); ++e) {
            uint16_t a = B::portalEdges_stub[e * 2], b = B::portalEdges_stub[e * 2 + 1];
            Vector3 d = B::portalVertices_stub[b] - B::portalVertices_stub[a];
            d /= vector3_length(d);
            int axis = 0;
            for (int k = 1; k < 3; ++k) if (std::abs(d[k]) > std::abs(d[axis])) axis = k;
            if (d[axis] < 0) d = -d;
            const Vector3 origin = B::portalVertices_stub[a] - d * vector3_dot(B::portalVertices_stub[a], d);
            Line key;
            for (int k = 0; k < 3; ++k) {
                key[k] = std::llround(d[k] * 1000000.0);
                key[k+3] = std::llround(origin[k] * 1024.0);
            }
            double lo = vector3_dot(B::portalVertices_stub[a], d), hi = vector3_dot(B::portalVertices_stub[b], d);
            bool reverse = lo > hi;
            if (reverse) { std::swap(lo, hi); std::swap(a, b); }
            lines[key].push_back({lo, hi, a, b, static_cast<uint16_t>(e), reverse});
        }
        std::vector<uint16_t> remap(edges.size());
        B::portalEdges_stub.clear();
        for (auto &[line, segments] : lines) {
            std::sort(segments.begin(), segments.end(), [](const Segment &a, const Segment &b) { return a.lo < b.lo; });
            for (std::size_t first = 0; first < segments.size();) {
                std::size_t end = first + 1;
                uint16_t a = segments[first].a, b = segments[first].b;
                double hi = segments[first].hi;
                while (end < segments.size() && segments[end].lo <= hi + 0.001) {
                    if (segments[end].hi > hi) { hi = segments[end].hi; b = segments[end].b; }
                    ++end;
                }
                const uint16_t id = B::portalEdges_stub.size() / 2;
                B::portalEdges_stub.push_back(a); B::portalEdges_stub.push_back(b);
                for (auto i = first; i < end; ++i) remap[segments[i].old] = (id << 1) | segments[i].reverse;
                first = end;
            }
        }
        for (auto &ref : B::portalEdgeReferences_stub) ref = remap[ref >> 1] ^ (ref & 1);
        incident.assign(B::portalVertices_stub.size(), {});
        const std::size_t edgeCount = B::portalEdges_stub.size() / 2;
        // Intersections include T-junctions, not just a polygon's two neighbors.
        // Search along the edge's longest axis, then test the full 3D segment.
        std::array<std::vector<uint16_t>, 3> ordered;
        for (int axis = 0; axis < 3; ++axis) {
            for (std::size_t i = 1; i < B::portalVertices_stub.size(); ++i) ordered[axis].push_back(i);
            std::sort(ordered[axis].begin(), ordered[axis].end(), [axis](uint16_t a, uint16_t b) {
                return B::portalVertices_stub[a][axis] < B::portalVertices_stub[b][axis];
            });
        }
        std::vector<std::vector<uint16_t>> onEdge(edgeCount);
        for (std::size_t e = 0; e < edgeCount; ++e) {
            const Vector3 a = B::portalVertices_stub[B::portalEdges_stub[e * 2]];
            const Vector3 b = B::portalVertices_stub[B::portalEdges_stub[e * 2 + 1]];
            const Vector3 d = b - a;
            const double length2 = vector3_dot(d, d);
            int axis = 0;
            for (int i = 1; i < 3; ++i) if (std::abs(d[i]) > std::abs(d[axis])) axis = i;
            const float lo = std::min(a[axis], b[axis]) - 0.01f;
            const float hi = std::max(a[axis], b[axis]) + 0.01f;
            auto it = std::lower_bound(ordered[axis].begin(), ordered[axis].end(), lo,
                                      [axis](uint16_t v, float x) { return B::portalVertices_stub[v][axis] < x; });
            for (; it != ordered[axis].end() && B::portalVertices_stub[*it][axis] <= hi; ++it) {
                const Vector3 p = B::portalVertices_stub[*it];
                const double t = vector3_dot(p - a, d) / length2;
                if (t < -1e-6 || t > 1.000001) continue;
                const Vector3 projection = a + d * t;
                if (vector3_length(p - projection) > 0.01) continue;
                onEdge[e].push_back(*it);
                auto &list = incident[*it];
                if (std::find(list.begin(), list.end(), e) == list.end()) list.push_back(e);
            }
        }
        for (const auto &list : incident) {
            if (list.size() > 8) Error("Portal vertex has more than eight incident edges");
            std::array<int16_t, 8> block;
            block.fill(-1);
            std::copy(list.begin(), list.end(), block.begin());
            B::portalVertexEdges_stub.push_back(IndexSet(block));
        }
        for (std::size_t e = 0; e < edgeCount; ++e) {
            std::set<std::pair<int16_t, int16_t>> intersections;
            for (const auto v : onEdge[e]) for (const auto other : incident[v])
                if (other != e) intersections.emplace(other, v);
            Titanfall::IntersectHeader_t header{};
            header.firstSet = B::portalIntersectEdges_stub.size();
            auto pair = intersections.begin();
            while (pair != intersections.end()) {
                std::array<int16_t, 8> es, vs;
                es.fill(-1); vs.fill(-1);
                for (int slot = 0; slot < 8 && pair != intersections.end(); ++slot, ++pair) {
                    es[slot] = pair->first;
                    vs[slot] = pair->second;
                }
                B::portalIntersectEdges_stub.push_back(IndexSet(es));
                B::portalIntersectVertices_stub.push_back(IndexSet(vs));
                ++header.setCount;
            }
            B::portalIntersectHeaders_stub.push_back(header);
        }
    }
};

void ClearPortals() {
    B::cellBSPNodes_stub.clear(); B::cells_stub.clear(); B::portals_stub.clear();
    B::portalVertices_stub.clear(); B::portalVertices_stub.emplace_back(Vector3(0));
    B::portalVertexReferences_stub.clear(); B::portalEdges_stub.clear(); B::portalEdgeReferences_stub.clear();
    B::portalVertexEdges_stub.clear(); B::portalIntersectHeaders_stub.clear();
    B::portalIntersectEdges_stub.clear(); B::portalIntersectVertices_stub.clear();
}

std::size_t RefCount(const Shared::visNode_t &node) {
    std::size_t total = node.refs.size();
    for (const auto &child : node.children) total += RefCount(child);
    return total;
}

void WriteAccessNode(const Shared::visNode_t &node, std::size_t index, const MinMax &bounds) {
    if (node.children.size() > 255 || node.refs.size() > 255 || RefCount(node) > 65535 ||
        B::objReferences.size() + node.refs.size() > 65535 ||
        B::cellAABBNodes.size() + node.children.size() > 65535)
        Error("Cell access tree exceeds native count/index fields");
    Titanfall::CellAABBNode_t out{};
    out.mins = bounds.mins; out.maxs = bounds.maxs;
    out.childCount = node.children.size(); out.objRefCount = node.refs.size();
    out.totalRefCount = RefCount(node);
    out.objRef = B::objReferences.size();
    for (const auto &ref : node.refs) {
        Titanfall::ObjReferenceBounds_t rb{};
        rb.mins = ref.minmax.mins; rb.maxs = ref.minmax.maxs;
        B::objReferenceBounds.push_back(rb); B::objReferences.push_back(ref.index);
    }
    out.firstChild = B::cellAABBNodes.size();
    if (node.children.empty()) out.firstChild = 0;
    const std::size_t first = B::cellAABBNodes.size();
    B::cellAABBNodes.resize(first + node.children.size());
    B::cellAABBNodes[index] = out;
    for (std::size_t i = 0; i < node.children.size(); ++i)
        WriteAccessNode(node.children[i], first + i, node.children[i].minmax);
}
} // namespace

void Titanfall2::EmitVisibility(const entity_t &world) {
    ClearPortals();
    PortalGeometry geometry;
    // Safe default: one actual cell, no fabricated portal quad. Sky apertures
    // come from authored sky brush faces. Selective brush cells are opt-in.
    if (!world.intForKey("_viewportals")) {
        B::cellBSPNodes_stub.push_back({-1, 0});
        Titanfall::Cell_t cell{0, 0, 1, -1};
        for (const brush_t &brush : world.brushes) for (const side_t &side : brush.sides) {
            if (side.bevel || side.winding.size() < 3 || !(side.compileFlags & C_SKY)) continue;
            auto portal = geometry.Polygon(side.winding, mapplanes[side.planenum].plane);
            portal.type = 1; portal.cell = 2;
            B::portals_stub.push_back(portal);
        }
        if (B::portals_stub.size() > 65535) Error("Sky portal count exceeds 16 bits");
        cell.portalCount = B::portals_stub.size();
        if (cell.portalCount) cell.flags |= 4;
        B::cells_stub.push_back(cell);
        Titanfall::EmitVisTree();
        geometry.Finish();
        return;
    }

    // Respawn's parser intentionally bypasses Q3 SetBrushContents. Classify a
    // local copy for the inherited BSP routines using Respawn shader contents.
    entity_t structural;
    for (const auto &source : world.brushes) {
        auto &brush = structural.brushes.emplace_back(source);
        int contents = 0, flags = 0;
        for (const auto &side : brush.sides) {
            contents |= side.shaderInfo->contentFlags;
            flags |= side.compileFlags;
        }
        brush.detail = (flags & C_DETAIL) || (contents & CONTENTS_DETAIL);
        brush.opaque = !(flags & C_TRANSLUCENT) && ((contents & CONTENTS_SOLID) || (flags & C_SKY));
        brush.compileFlags = flags;
    }
    facelist_t faces = MakeStructuralBSPFaceList(structural.brushes);
    if (faces.empty()) Error("_viewportals requires structural world brushes");
    tree_t tree = FaceBSP(faces);
    for (const auto &ref : Shared::visRefs) tree.minmax.extend(ref.minmax);
    MakeTreePortals(tree);
    FilterStructuralBrushesIntoTree(structural, tree);
    std::vector<node_t *> leaves;
    std::unordered_map<const node_t *, uint16_t> ids;
    std::function<void(node_t *)> collect = [&](node_t *node) {
        if (node->planenum == PLANENUM_LEAF) {
            if (leaves.size() >= 65534) Error("Portal cell count exceeds the sky-sentinel field");
            ids.emplace(node, leaves.size()); leaves.push_back(node);
        } else { collect(node->children[0]); collect(node->children[1]); }
    };
    collect(tree.headnode);
    B::cells_stub.resize(leaves.size());
    B::cellBSPNodes_stub.resize(1);
    std::function<void(const node_t *, std::size_t)> emitTree = [&](const node_t *node, std::size_t index) {
        if (node->planenum == PLANENUM_LEAF) B::cellBSPNodes_stub[index] = {-1, ids.at(node)};
        else {
            const uint32_t first = B::cellBSPNodes_stub.size();
            B::cellBSPNodes_stub.resize(first + 2);
            B::cellBSPNodes_stub[index] = {static_cast<int32_t>(PortalPlane(mapplanes[node->planenum].plane)), first};
            emitTree(node->children[0], first); emitTree(node->children[1], first + 1);
        }
    };
    emitTree(tree.headnode, 0);
    std::vector<std::vector<Titanfall::Portal_t>> outgoing(leaves.size());
    std::unordered_set<const portal_t *> visited;
    for (auto *leaf : leaves) for (const portal_t *p = leaf->portals; p;) {
        const int side = p->nodes[1] == leaf;
        const portal_t *next = p->next[side];
        if (p->onnode && p->winding.size() >= 3 && visited.insert(p).second) {
            const bool free0 = !p->nodes[0]->opaque, free1 = !p->nodes[1]->opaque;
            const bool sky = (p->compileFlags & C_SKY) != 0;
            if ((free0 && free1) || ((free0 || free1) && sky)) {
                auto portal = geometry.Polygon(p->winding, p->plane.plane);
                for (int from = 0; from < 2; ++from) if (!p->nodes[from]->opaque) {
                    portal.isReversed = from;
                    const bool destinationOpaque = p->nodes[1 - from]->opaque;
                    portal.type = destinationOpaque ? 1 : 0;
                    portal.cell = destinationOpaque ? leaves.size() + 1 : ids.at(p->nodes[1 - from]);
                    outgoing[ids.at(p->nodes[from])].push_back(portal);
                }
            }
        }
        p = next;
    }
    for (std::size_t i = 0; i < leaves.size(); ++i) {
        if (B::portals_stub.size() + outgoing[i].size() > 65535) Error("Portal record count exceeds 16 bits");
        Titanfall::Cell_t cell{};
        cell.firstPortal = B::portals_stub.size(); cell.portalCount = outgoing[i].size();
        cell.flags = 1; cell.leafWaterData = -1;
        for (const auto &p : outgoing[i]) { if (p.type == 1) cell.flags |= 4; B::portals_stub.push_back(p); }
        B::cells_stub[i] = cell;
    }
    geometry.Finish();
    // One access root per cell, followed by each root's geometric child tree.
    std::vector<std::vector<Shared::visRef_t>> references(leaves.size());
    std::function<void(const node_t *, const Shared::visRef_t &)> distribute = [&](const node_t *node, const Shared::visRef_t &ref) {
        if (node->planenum == PLANENUM_LEAF) { references[ids.at(node)].push_back(ref); return; }
        const auto &plane = mapplanes[node->planenum].plane;
        const Vector3 center = (ref.minmax.mins + ref.minmax.maxs) * 0.5f;
        const Vector3 extent = (ref.minmax.maxs - ref.minmax.mins) * 0.5f;
        const double d = vector3_dot(center, plane.normal()) - plane.dist();
        double radius = 0;
        for (int a = 0; a < 3; ++a) radius += std::abs(plane.normal()[a] * extent[a]);
        if (d + radius >= -0.01) distribute(node->children[0], ref);
        if (d - radius <= 0.01) distribute(node->children[1], ref);
    };
    for (const auto &ref : Shared::visRefs) distribute(tree.headnode, ref);
    B::cellAABBNodes.clear(); B::cellAABBNodes.resize(leaves.size());
    B::objReferences.clear(); B::objReferenceBounds.clear();
    for (std::size_t i = 0; i < leaves.size(); ++i) {
        const auto access = Shared::MakeVisTree(std::move(references[i]), 1e30f);
        WriteAccessNode(access, i, leaves[i]->minmax);
    }
    Sys_Printf("%9zu geometry-derived cells, %zu directed portals, %zu portal edges\n",
               leaves.size(), B::portals_stub.size(), B::portalEdges_stub.size() / 2);
    FreeTree(tree);
}
