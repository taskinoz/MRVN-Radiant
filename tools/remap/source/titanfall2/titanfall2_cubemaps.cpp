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
#include <set>
#include "vfs.h"

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

// The level name, from the compiled map's path ("mp_name" for ".../mp_name.map").
std::string LevelName() {
    std::string name = source;
    const std::size_t slash = name.find_last_of("/\\");
    if (slash != std::string::npos) name.erase(0, slash + 1);
    const std::size_t dot = name.find_last_of('.');
    if (dot != std::string::npos) name.erase(dot);
    return name;
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
std::vector<Face> MipChain(const Face &rendered, int FaceSize = ::FaceSize) {
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

// Stored (uncompressed) files in a ZIP with the "XZP1 0" comment retail uses.
// Offsets are relative to the start of the lump.
std::vector<uint8_t> StoredZip(const std::vector<std::pair<std::string, std::vector<uint8_t>>> &files) {
    std::vector<uint8_t> z, directory;
    for (const auto &[name, data] : files) {
        const uint32_t crc = Crc32(data), size = uint32_t(data.size()), offset = uint32_t(z.size());
        Put<uint32_t>(z, 0x04034B50); Put<uint16_t>(z, 10); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0);
        Put<uint32_t>(z, 0); Put<uint32_t>(z, crc); Put<uint32_t>(z, size); Put<uint32_t>(z, size);
        Put<uint16_t>(z, uint16_t(name.size())); Put<uint16_t>(z, 0);
        z.insert(z.end(), name.begin(), name.end());
        z.insert(z.end(), data.begin(), data.end());
        Put<uint32_t>(directory, 0x02014B50); Put<uint16_t>(directory, 20); Put<uint16_t>(directory, 10);
        Put<uint16_t>(directory, 0); Put<uint16_t>(directory, 0);
        Put<uint32_t>(directory, 0); Put<uint32_t>(directory, crc); Put<uint32_t>(directory, size); Put<uint32_t>(directory, size);
        Put<uint16_t>(directory, uint16_t(name.size())); Put<uint16_t>(directory, 0); Put<uint16_t>(directory, 0);
        Put<uint16_t>(directory, 0); Put<uint16_t>(directory, 0); Put<uint32_t>(directory, 0); Put<uint32_t>(directory, offset);
        directory.insert(directory.end(), name.begin(), name.end());
    }
    const uint32_t start = uint32_t(z.size()), length = uint32_t(directory.size());
    z.insert(z.end(), directory.begin(), directory.end());
    Put<uint32_t>(z, 0x06054B50); Put<uint16_t>(z, 0); Put<uint16_t>(z, 0);
    Put<uint16_t>(z, uint16_t(files.size())); Put<uint16_t>(z, uint16_t(files.size()));
    Put<uint32_t>(z, length); Put<uint32_t>(z, start); Put<uint16_t>(z, 32);
    const char comment[32] = "XZP1 0";
    z.insert(z.end(), comment, comment + 32);
    return z;
}

// Titanfall 1 cubemap VTF, as Angel City's: version 7.5, one face set, mips
// smallest first, faces in D3D order. HDR is RGBA16161616F (format 24, as its
// cubemapdefault.hdr.vtf); LDR is RGBA8888 (format 0) in gamma space.
std::vector<uint8_t> SourceVtf(const std::vector<std::vector<Face>> &faces, bool hdr) {
    const int size = int(std::lround(std::sqrt(double(faces[0][0].size()))));
    const int mips = int(faces[0].size());
    V3 average{};
    for (const auto &face : faces) for (const V3 &c : face.back()) average = average + c;
    average = average * (1.0 / 6);
    std::vector<uint8_t> v;
    v.insert(v.end(), {'V', 'T', 'F', 0});
    Put<uint32_t>(v, 7); Put<uint32_t>(v, 5); Put<uint32_t>(v, 88);
    Put<uint16_t>(v, uint16_t(size)); Put<uint16_t>(v, uint16_t(size)); Put<uint32_t>(v, hdr ? 0x620C : 0x4000);
    Put<uint16_t>(v, 1); Put<uint16_t>(v, 0); Put<uint32_t>(v, 0);
    Put<float>(v, float(average.x)); Put<float>(v, float(average.y)); Put<float>(v, float(average.z)); Put<uint32_t>(v, 0);
    Put<float>(v, 1.0f); Put<int32_t>(v, hdr ? 24 : 0); Put<uint8_t>(v, uint8_t(mips)); Put<int32_t>(v, -1);
    Put<uint8_t>(v, 0); Put<uint8_t>(v, 0); Put<uint16_t>(v, 1);
    v.insert(v.end(), 3, 0); Put<uint32_t>(v, 1); v.insert(v.end(), 8, 0);
    v.insert(v.end(), {'0', 0, 0, 0}); Put<uint32_t>(v, 88);
    for (int mip = mips - 1; mip >= 0; --mip)
        for (const auto &face : faces)
            for (const V3 &c : face[mip]) {
                if (hdr) {
                    for (double channel : {c.x, c.y, c.z}) Put<uint16_t>(v, Respawn::BC6H::halfBits(float(channel)));
                    Put<uint16_t>(v, 0x3C00);  // alpha 1.0
                } else {
                    for (double channel : {c.x, c.y, c.z})
                        Put<uint8_t>(v, uint8_t(std::lround(std::pow(std::clamp(channel, 0.0, 1.0), 1 / 2.2) * 255)));
                    Put<uint8_t>(v, 255);
                }
            }
    return v;
}

// The "$envmap"/"$envmap2" keys of a TF1 material's VMT that have a value.
// Materials whose VMT cannot be found get no cubemap.
bool UsesEnvmap(const std::string &texture, std::vector<std::string> &keys) {
    std::string path = "materials/" + texture + ".vmt";
    std::replace(path.begin(), path.end(), '\\', '/');
    keys.clear();
    const MemBuffer file = vfsLoadFile(path.c_str());
    if (!file) return false;
    const std::string text(file.data(), file.size());
    std::vector<std::string> tokens;
    std::size_t at = 0;
    while ((at = text.find('"', at)) != std::string::npos) {
        const std::size_t end = text.find('"', at + 1);
        if (end == std::string::npos) break;
        tokens.push_back(text.substr(at + 1, end - at - 1));
        at = end + 1;
    }
    for (std::size_t i = 0; i + 1 < tokens.size(); ++i) {
        std::string key = tokens[i];
        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return char(std::tolower(c)); });
        if ((key == "$envmap" || key == "$envmap2") && !tokens[i + 1].empty())
            keys.push_back(tokens[i]);
    }
    return !keys.empty();
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
static std::vector<std::size_t> PlaceCubemaps() {
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

    std::vector<std::size_t> gameplay;
    for (std::size_t i = 0; i < pendingCubemaps.size(); ++i)
        if (!pendingCubemaps[i].menu) gameplay.push_back(i);
    if (gameplay.empty())
        for (std::size_t i = 0; i < pendingCubemaps.size(); ++i) gameplay.push_back(i);
    return gameplay;
}

// Renders a cubemap's six faces; `faces` receives each face's mip chain at `size`.
static std::vector<Face> RenderCubemap(V3 origin, int size, const Respawn::Bake::Occluders *occluders,
                                       const Respawn::Bake::RadianceGrid *grid, std::vector<std::vector<Face>> &faces) {
    std::vector<Respawn::Bake::Light> suns;
    for (const Respawn::Bake::Light &light : Titanfall2::Bsp::bakeLights)
        if (light.type == Respawn::Bake::LightType::Sun && light.realtime) suns.push_back(light);
    const V3 sky = Titanfall2::Bsp::ambient.x + Titanfall2::Bsp::ambient.y + Titanfall2::Bsp::ambient.z > 0
        ? Titanfall2::Bsp::ambient : V3{0.4, 0.45, 0.5};
    std::vector<Face> rendered;
    faces.clear();
    for (int face = 0; face < 6; ++face) {
        rendered.push_back(RenderFace(origin, face, occluders, grid, sky, suns));
        faces.push_back(MipChain(rendered.back(), size));
    }
    return rendered;
}

void Titanfall2::EmitCubemaps(const Respawn::Bake::Occluders *occluders, const Respawn::Bake::RadianceGrid *grid) {
    const std::vector<std::size_t> gameplay = PlaceCubemaps();

    // Lit meshes take the nearest gameplay cubemap; unlit ones (sky, self-lit) none.
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
    const std::string name = "materials/maps/" + LevelName() + "/cubemaps.hdr.vtf";
    Titanfall2::Bsp::pakfile = StoredZip({{name, BuildVtf(rendered, cma)}});
    Sys_Printf("%9zu cubemaps (%zu at the menu stage)\n", pendingCubemaps.size(), pendingCubemaps.size() - gameplay.size());
}


/*
    EmitCubemapsTF1()
    Titanfall 1 cubemaps, as Source 1 and retail Angel City do them: one
    c<x>_<y>_<z>.vtf/.hdr.vtf pair per cubemap plus cubemapdefault, and a patch
    VMT for each envmapped material pointing $envmap at its cubemap. Material
    sorts of envmapped materials take the cubemap nearest their meshes; others -1.
*/
void Titanfall2::EmitCubemapsTF1(const Respawn::Bake::Occluders *occluders, const Respawn::Bake::RadianceGrid *grid) {
    const std::vector<std::size_t> gameplay = PlaceCubemaps();
    const std::string folder = "maps/" + LevelName() + "/";
    auto suffix = [](const int32_t (&o)[3]) {
        return std::to_string(o[0]) + "_" + std::to_string(o[1]) + "_" + std::to_string(o[2]);
    };
    std::vector<std::string> stems;
    std::vector<std::pair<std::string, std::vector<uint8_t>>> files;
    for (std::size_t i = 0; i < pendingCubemaps.size(); ++i) {
        stems.push_back(folder + "c" + suffix(Titanfall2::Bsp::cubemaps[i].origin));
        std::vector<std::vector<Face>> hdr, ldr;
        const std::vector<Face> rendered = RenderCubemap(pendingCubemaps[i].origin, 64, occluders, grid, hdr);
        for (const Face &face : rendered) ldr.push_back(MipChain(face, 32));
        files.push_back({"materials/" + stems.back() + ".hdr.vtf", SourceVtf(hdr, true)});
        files.push_back({"materials/" + stems.back() + ".vtf", SourceVtf(ldr, false)});
        if (i == gameplay.front()) {  // the default is the first gameplay cubemap
            files.push_back({"materials/" + folder + "cubemapdefault.hdr.vtf", files[files.size() - 2].second});
            files.push_back({"materials/" + folder + "cubemapdefault.vtf", files[files.size() - 2].second});
        }
    }

    // Mesh centres per material sort decide each sort's cubemap.
    std::vector<V3> centre(Titanfall::Bsp::materialSorts.size());
    std::vector<int> count(Titanfall::Bsp::materialSorts.size(), 0);
    for (std::size_t m = 0; m < Titanfall::Bsp::meshes.size(); ++m) {
        const Vector3 &c = Titanfall::Bsp::meshBounds.at(m).origin;
        const uint16_t s = Titanfall::Bsp::meshes[m].materialOffset;
        centre[s] = centre[s] + V3{c.x(), c.y(), c.z()};
        count[s]++;
    }
    auto textureName = [](int16_t index) -> std::string {
        const auto &texture = Titanfall::Bsp::textureData.at(index);
        return &Titanfall::Bsp::textureDataData.at(Titanfall::Bsp::textureDataTable.at(texture.name_index));
    };
    std::set<std::pair<int16_t, int16_t>> patches;
    std::size_t envmapped = 0;
    std::vector<std::string> keys;
    for (std::size_t s = 0; s < Titanfall::Bsp::materialSorts.size(); ++s) {
        Titanfall::MaterialSort_t &sort = Titanfall::Bsp::materialSorts[s];
        sort.cubemap = -1;
        if (!count[s] || !UsesEnvmap(textureName(sort.textureData), keys)) continue;
        const V3 c = centre[s] * (1.0 / count[s]);
        double best = 1e300;
        for (std::size_t i : gameplay) {
            const double d = Respawn::Bake::length(pendingCubemaps[i].origin - c);
            if (d < best) { best = d; sort.cubemap = int16_t(i); }
        }
        patches.insert({sort.textureData, sort.cubemap});
        ++envmapped;
    }
    for (const auto &[textureIndex, cubemap] : patches) {
        const std::string name = textureName(textureIndex);
        UsesEnvmap(name, keys);
        std::string patched = name;
        std::replace(patched.begin(), patched.end(), '\\', '/');
        std::transform(patched.begin(), patched.end(), patched.begin(), [](unsigned char ch) { return char(std::tolower(ch)); });
        patched = "materials/" + folder + patched + "_" + suffix(Titanfall2::Bsp::cubemaps[cubemap].origin) + ".vmt";
        std::string text = "\"patch\"\n{\n\t\"include\"\t\t\"materials/" + name + ".vmt\"\n\t\"replace\"\n\t{\n";
        for (const std::string &key : keys) text += "\t\t\"" + key + "\"\t\t\"" + stems[cubemap] + "\"\n";
        text += "\t}\n}\n";
        files.push_back({patched, std::vector<uint8_t>(text.begin(), text.end())});
    }
    Titanfall2::Bsp::pakfile = StoredZip(files);
    Sys_Printf("%9zu cubemaps, %zu envmapped material sorts\n", pendingCubemaps.size(), envmapped);
}
