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
    Titanfall 2 cubemaps: the CUBEMAPS lump (0x2A), per-mesh cubemap indices and
    the PAKFILE (0x28) holding materials/maps/<map>/cubemaps.hdr.vtf. Layouts follow
    retail Coliseum, Colony, Glitch, Homestead, Live Fire Stacks and the lobby; see
    docs/respawn/RESPAWN_TF2_LUMPS.md.
*/

#include "../remap.h"
#include "../bspfile_abstract.h"
#include "../respawn/bc6h.h"
#include <cstring>

using Respawn::Bake::V3;

namespace {

constexpr int FaceSize = 256;   // retail cubemap faces are 256 x 256 with 9 mips
constexpr int RenderSize = 64;  // rendered resolution, upsampled to FaceSize
constexpr double MenuDistance = 2048;

struct Pending { V3 origin; bool menu; };
std::vector<Pending> pendingCubemaps;

V3 Origin(const entity_t &e) {
    const Vector3 o = e.vectorForKey("origin");
    return {o.x(), o.y(), o.z()};
}

bool IsMenuAnchor(const entity_t &e) {
    return e.classname_is("info_target_clientside") && striEqualPrefix(e.valueForKey("script_name"), "menu_");
}

// Direction through texel (u, v) in [-1, 1] of a D3D cube face (+X, -X, +Y, -Y, +Z, -Z),
// sampled with Source world vectors: retail faces join seamlessly under this mapping.
V3 FaceDirection(int face, double u, double v) {
    switch (face) {
        case 0: return Respawn::Bake::normalize({1, -v, -u});
        case 1: return Respawn::Bake::normalize({-1, -v, u});
        case 2: return Respawn::Bake::normalize({u, 1, v});
        case 3: return Respawn::Bake::normalize({u, -1, -v});
        case 4: return Respawn::Bake::normalize({u, -v, 1});
        default: return Respawn::Bake::normalize({-u, -v, -1});
    }
}

using Face = std::vector<V3>;  // size x size, row-major

Face RenderFace(V3 origin, int face, const Respawn::Bake::Occluders *occluders, const Respawn::Bake::RadianceGrid *grid,
                V3 sky, const std::vector<Respawn::Bake::Light> &suns) {
    Face out(RenderSize * RenderSize);
    constexpr double far = 65536;
    for (int y = 0; y < RenderSize; ++y)
        for (int x = 0; x < RenderSize; ++x) {
            const V3 d = FaceDirection(face, (x + 0.5) / RenderSize * 2 - 1, (y + 0.5) / RenderSize * 2 - 1);
            V3 colour = sky;
            double fraction;
            V3 normal;
            if (occluders && occluders->firstHit(origin, origin + d * far, fraction, normal)) {
                const V3 hit = origin + d * (far * fraction);
                V3 radiance;
                // Direct light from the bake, plus a little sky light so shade is not black.
                colour = sky * 0.15;
                if (grid && grid->lookup(hit + normal * 1.0, normal, radiance)) colour = colour + radiance;
            } else {
                for (const Respawn::Bake::Light &sun : suns)
                    if (Respawn::Bake::dot(d, -sun.direction) > 0.9995)
                        colour = colour + sun.intensity * 4.0;
            }
            out[y * RenderSize + x] = colour;
        }
    return out;
}

// Bilinear upsample of a rendered face, then box-filtered mips down to 1 x 1.
std::vector<Face> MipChain(const Face &rendered) {
    std::vector<Face> mips;
    Face top(FaceSize * FaceSize);
    for (int y = 0; y < FaceSize; ++y)
        for (int x = 0; x < FaceSize; ++x) {
            const double fx = std::clamp((x + 0.5) * RenderSize / FaceSize - 0.5, 0.0, RenderSize - 1.0);
            const double fy = std::clamp((y + 0.5) * RenderSize / FaceSize - 0.5, 0.0, RenderSize - 1.0);
            const int x0 = int(fx), y0 = int(fy), x1 = std::min(x0 + 1, RenderSize - 1), y1 = std::min(y0 + 1, RenderSize - 1);
            const double tx = fx - x0, ty = fy - y0;
            auto at = [&](int px, int py) { return rendered[py * RenderSize + px]; };
            top[y * FaceSize + x] = (at(x0, y0) * (1 - tx) + at(x1, y0) * tx) * (1 - ty) + (at(x0, y1) * (1 - tx) + at(x1, y1) * tx) * ty;
        }
    mips.push_back(std::move(top));
    for (int size = FaceSize / 2; size >= 1; size /= 2) {
        const Face &previous = mips.back();
        Face next(size * size);
        for (int y = 0; y < size; ++y)
            for (int x = 0; x < size; ++x)
                next[y * size + x] = (previous[(2 * y) * size * 2 + 2 * x] + previous[(2 * y) * size * 2 + 2 * x + 1] +
                                      previous[(2 * y + 1) * size * 2 + 2 * x] + previous[(2 * y + 1) * size * 2 + 2 * x + 1]) * 0.25;
        mips.push_back(std::move(next));
    }
    return mips;
}

void AppendBlocks(std::vector<uint8_t> &out, const Face &face, int size) {
    for (int by = 0; by < (size + 3) / 4; ++by)
        for (int bx = 0; bx < (size + 3) / 4; ++bx) {
            float pixels[16][3];
            for (int i = 0; i < 16; ++i) {
                const V3 &c = face[std::min(by * 4 + i / 4, size - 1) * size + std::min(bx * 4 + i % 4, size - 1)];
                pixels[i][0] = float(c.x); pixels[i][1] = float(c.y); pixels[i][2] = float(c.z);
            }
            const auto block = Respawn::BC6H::encodeBlock(pixels);
            out.insert(out.end(), block.begin(), block.end());
        }
}

template<class T> void Put(std::vector<uint8_t> &out, T value) {
    const auto *bytes = reinterpret_cast<const uint8_t *>(&value);
    out.insert(out.end(), bytes, bytes + sizeof(T));
}

// VTF 7.5 cube array as retail writes it: BC6H (format 66), 9 mips smallest first,
// then frames (one per cubemap), then the six faces. CMA holds one float per cubemap;
// CRC is left zero, as the game does not check it.
std::vector<uint8_t> BuildVtf(const std::vector<std::vector<std::vector<Face>>> &cubemaps, const std::vector<float> &cma) {
    const uint32_t frames = uint32_t(cubemaps.size());
    const uint32_t cmaSize = frames > 1 ? 4 + 4 * frames : 0;
    const uint32_t imageOffset = 104 + cmaSize;
    std::vector<uint8_t> v;
    v.insert(v.end(), {'V', 'T', 'F', 0});
    Put<uint32_t>(v, 7); Put<uint32_t>(v, 5); Put<uint32_t>(v, 104);
    Put<uint16_t>(v, FaceSize); Put<uint16_t>(v, FaceSize); Put<uint32_t>(v, 0x420C);
    Put<uint16_t>(v, uint16_t(frames)); Put<uint16_t>(v, 0); Put<uint32_t>(v, 0);
    Put<float>(v, 0.2f); Put<float>(v, 0.2f); Put<float>(v, 0.2f); Put<uint32_t>(v, 0);
    Put<float>(v, 1.0f); Put<int32_t>(v, 66); Put<uint8_t>(v, 9); Put<int32_t>(v, -1);
    Put<uint8_t>(v, 0); Put<uint8_t>(v, 0); Put<uint16_t>(v, 1);
    v.insert(v.end(), 3, 0); Put<uint32_t>(v, 3); v.insert(v.end(), 8, 0);
    v.insert(v.end(), {'0', 0, 0, 0}); Put<uint32_t>(v, imageOffset);
    if (frames > 1) { v.insert(v.end(), {'C', 'M', 'A', 0}); Put<uint32_t>(v, 104); }
    else { v.insert(v.end(), {'C', 'M', 'A', 2}); Put<float>(v, cma.empty() ? 1.0f : cma[0]); }
    v.insert(v.end(), {'C', 'R', 'C', 2}); Put<uint32_t>(v, 0);
    if (frames > 1) {
        Put<uint32_t>(v, 4 * frames);
        for (float value : cma) Put<float>(v, value);
    }
    for (int mip = 8; mip >= 0; --mip)
        for (const auto &cubemap : cubemaps)
            for (int face = 0; face < 6; ++face)
                AppendBlocks(v, cubemap[face][mip], std::max(FaceSize >> mip, 1));
    return v;
}

uint32_t Crc32(const std::vector<uint8_t> &data) {
    uint32_t crc = 0xFFFFFFFF;
    for (uint8_t byte : data) {
        crc ^= byte;
        for (int k = 0; k < 8; ++k) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
    return ~crc;
}

// One stored (uncompressed) file in a ZIP with the "XZP1 0" comment retail uses.
std::vector<uint8_t> StoredZip(const std::string &name, const std::vector<uint8_t> &data) {
    const uint32_t crc = Crc32(data), size = uint32_t(data.size());
    std::vector<uint8_t> z;
    Put<uint32_t>(z, 0x04034B50); Put<uint16_t>(z, 10); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0);
    Put<uint32_t>(z, 0); Put<uint32_t>(z, crc); Put<uint32_t>(z, size); Put<uint32_t>(z, size);
    Put<uint16_t>(z, uint16_t(name.size())); Put<uint16_t>(z, 0);
    z.insert(z.end(), name.begin(), name.end());
    z.insert(z.end(), data.begin(), data.end());
    const uint32_t directory = uint32_t(z.size());
    Put<uint32_t>(z, 0x02014B50); Put<uint16_t>(z, 20); Put<uint16_t>(z, 10); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0);
    Put<uint32_t>(z, 0); Put<uint32_t>(z, crc); Put<uint32_t>(z, size); Put<uint32_t>(z, size);
    Put<uint16_t>(z, uint16_t(name.size())); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0);
    Put<uint16_t>(z, 0); Put<uint32_t>(z, 0); Put<uint32_t>(z, 0);
    z.insert(z.end(), name.begin(), name.end());
    const uint32_t directorySize = uint32_t(z.size()) - directory;
    Put<uint32_t>(z, 0x06054B50); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0); Put<uint16_t>(z, 1); Put<uint16_t>(z, 1);
    Put<uint32_t>(z, directorySize); Put<uint32_t>(z, directory); Put<uint16_t>(z, 32);
    const char comment[32] = "XZP1 0";
    z.insert(z.end(), comment, comment + 32);
    return z;
}

}  // namespace


/*
    CollectCubemap()
    Records an env_cubemap; the entity itself is not written, as in retail maps
*/
void Titanfall2::CollectCubemap(const entity_t &e) {
    pendingCubemaps.push_back({Origin(e), false});
}


/*
    EmitCubemaps()
    Places default cubemaps when none were authored, assigns the nearest cubemap
    to every lit mesh, renders each cubemap from the bake and writes the pakfile
*/
void Titanfall2::EmitCubemaps(const Respawn::Bake::Occluders *occluders, const Respawn::Bake::RadianceGrid *grid) {
    std::vector<V3> menuAnchors;
    for (const entity_t &e : entities)
        if (IsMenuAnchor(e)) menuAnchors.push_back(Origin(e));
    if (pendingCubemaps.empty()) {
        // Retail maps place one cubemap at the menu stage and the rest in play.
        if (!menuAnchors.empty())
            pendingCubemaps.push_back({menuAnchors.front() + V3{0, 0, 64}, true});
        V3 sum{};
        int count = 0;
        for (const entity_t &e : entities)
            if (e.classname_prefixed("info_spawnpoint_human")) { sum = sum + Origin(e); ++count; }
        V3 play{};
        if (count) {
            play = sum * (1.0 / count) + V3{0, 0, 64};
        } else if (!Titanfall::Bsp::models.empty()) {
            const auto &bounds = Titanfall::Bsp::models[0].minmax;
            play = V3{bounds.mins.x() + bounds.maxs.x(), bounds.mins.y() + bounds.maxs.y(), bounds.mins.z() + bounds.maxs.z()} * 0.5;
        }
        pendingCubemaps.push_back({play, false});
    }
    for (Pending &cubemap : pendingCubemaps)
        for (const V3 &anchor : menuAnchors)
            if (Respawn::Bake::length(cubemap.origin - anchor) < MenuDistance) cubemap.menu = true;
    if (pendingCubemaps.size() > 127)
        Error("%zu cubemaps exceed the per-mesh index range (127)", pendingCubemaps.size());

    for (const Pending &cubemap : pendingCubemaps)
        Titanfall2::Bsp::cubemaps.push_back({int32_t(std::lround(cubemap.origin.x)), int32_t(std::lround(cubemap.origin.y)),
                                             int32_t(std::lround(cubemap.origin.z)), 0});

    // Lit meshes take the nearest gameplay cubemap; unlit ones (sky, self-lit) none.
    std::vector<std::size_t> gameplay;
    for (std::size_t i = 0; i < pendingCubemaps.size(); ++i)
        if (!pendingCubemaps[i].menu) gameplay.push_back(i);
    if (gameplay.empty())
        for (std::size_t i = 0; i < pendingCubemaps.size(); ++i) gameplay.push_back(i);
    for (std::size_t m = 0; m < Titanfall::Bsp::meshes.size(); ++m) {
        Titanfall::Mesh_t &mesh = Titanfall::Bsp::meshes[m];
        if ((mesh.flags & 0x600) == S_VERTEX_UNLIT || (mesh.flags & S_SKY)) { mesh.cubemap = -1; continue; }
        const Vector3 &c = Titanfall::Bsp::meshBounds.at(m).origin;
        double best = 1e300;
        for (std::size_t i : gameplay) {
            const double d = Respawn::Bake::length(pendingCubemaps[i].origin - V3{c.x(), c.y(), c.z()});
            if (d < best) { best = d; mesh.cubemap = int8_t(i); }
        }
    }

    // Each cubemap sees the bake's lit surfaces and the first environment's sky.
    std::vector<Respawn::Bake::Light> suns;
    for (const Respawn::Bake::Light &light : Titanfall2::Bsp::bakeLights)
        if (light.type == Respawn::Bake::LightType::Sun && light.realtime) suns.push_back(light);
    const V3 sky = Titanfall2::Bsp::ambient.x + Titanfall2::Bsp::ambient.y + Titanfall2::Bsp::ambient.z > 0
        ? Titanfall2::Bsp::ambient : V3{0.4, 0.45, 0.5};
    std::vector<std::vector<std::vector<Face>>> rendered(pendingCubemaps.size());
    std::vector<float> cma;
    for (std::size_t i = 0; i < pendingCubemaps.size(); ++i) {
        for (int face = 0; face < 6; ++face)
            rendered[i].push_back(MipChain(RenderFace(pendingCubemaps[i].origin, face, occluders, grid, sky, suns)));
        // CMA meaning is unresolved; retail menu cubemaps store 5.0, gameplay ones 0.7-42.
        cma.push_back(pendingCubemaps[i].menu ? 5.0f : 1.0f);
    }
    const std::string name = std::string("materials/maps/") + mapName.c_str() + "/cubemaps.hdr.vtf";
    Titanfall2::Bsp::pakfile = StoredZip(name, BuildVtf(rendered, cma));
    Sys_Printf("%9zu cubemaps (%zu at the menu stage)\n", pendingCubemaps.size(), pendingCubemaps.size() - gameplay.size());
}
