/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Original bounded adapter for the project's existing native TF2 baker.
 * RBL1 input is produced by repair_tf1_port.py, never a game format.
 */
#include "../remap/source/respawn/lightbake.h"
#include <filesystem>
#include <fstream>
#include <iostream>

namespace B = Respawn::Bake;
std::ifstream input;
template<class T> T read() {
    T value{};
    if (!input.read(reinterpret_cast<char *>(&value), sizeof(value))) throw std::runtime_error("Truncated bake input");
    return value;
}
double number() {
    const double v = read<double>();
    if (!std::isfinite(v)) throw std::runtime_error("Nonfinite bake input");
    return v;
}
B::V3 vector() { return {number(), number(), number()}; }
std::uint32_t count(std::uint32_t limit) {
    const auto n = read<std::uint32_t>();
    if (n > limit) throw std::runtime_error("Bake input count exceeds limit");
    return n;
}
template<class T> void write(const std::string &path, const std::vector<T> &data) {
    if (std::filesystem::exists(path)) throw std::runtime_error("Refusing to overwrite bake output");
    std::ofstream out(path, std::ios::binary);
    if (!out.write(reinterpret_cast<const char *>(data.data()), data.size() * sizeof(T))) throw std::runtime_error("Bake output write failed");
}
int main(int argc, char **argv) {
    try {
        if (argc != 3) throw std::runtime_error("Usage: relight_bridge INPUT OUTPUT_PREFIX");
        input.open(argv[1], std::ios::binary);
        if (read<std::uint32_t>() != 0x314c4252) throw std::runtime_error("Expected RBL1 input");
        const auto np = count(256), nc = count(65536), nl = count(4096), nb = count(65536), nr = count(65535);
        B::V3 ambient = vector();
        std::vector<B::PageSize> pages;
        std::uint64_t texels = 0;
        for (unsigned i = 0; i < np; ++i) {
            const auto w = count(8192), h = count(8192);
            texels += std::uint64_t(w) * h;
            if (!w || !h || w % 2 || h % 2 || texels > 16777216) throw std::runtime_error("Invalid bake page dimensions/budget");
            pages.push_back({w, h});
        }
        std::vector<B::Light> lights;
        for (unsigned i = 0; i < nl; ++i) {
            B::Light l;
            const int type = read<std::int32_t>();
            if (type != 1 && type != 2 && type != 3 && type != 5) throw std::runtime_error("Unsupported light type");
            l.type = static_cast<B::LightType>(type); l.hardwareIndex = read<std::int32_t>();
            l.realtime = read<std::uint32_t>() != 0; l.shadowMask = read<std::uint32_t>() != 0;
            l.origin = vector(); l.direction = vector(); l.intensity = vector(); l.zeroDistance = number();
            l.attenuation = {number(), number(), number()}; l.cosInner = number(); l.cosOuter = number();
            lights.push_back(l);
        }
        std::vector<B::Chart> charts;
        for (unsigned i = 0; i < nc; ++i) {
            B::Chart c; c.page = count(255);
            const auto nv = count(65536), ni = count(3000000);
            for (unsigned v = 0; v < nv; ++v) {
                c.positions.push_back(vector()); c.normals.push_back(vector()); c.luxels.push_back({number(), number()});
            }
            for (unsigned v = 0; v < ni; ++v) c.triangles.push_back(count(nv ? nv - 1 : 0));
            charts.push_back(std::move(c));
        }
        std::vector<B::Brush> brushes;
        for (unsigned i = 0; i < nb; ++i) {
            B::Brush b; const auto n = count(256); b.mins = vector(); b.maxs = vector();
            if (!n || b.mins.x > b.maxs.x || b.mins.y > b.maxs.y || b.mins.z > b.maxs.z) throw std::runtime_error("Invalid occluder bounds");
            for (unsigned p = 0; p < n; ++p) b.planes.push_back({number(), number(), number(), number()});
            brushes.push_back(std::move(b));
        }
        std::vector<B::V3> points;
        for (unsigned i = 0; i < nr; ++i) points.push_back(vector());
        if (input.peek() != EOF) throw std::runtime_error("Unexpected bake input tail");
        const B::Occluders occluders(std::move(brushes));
        B::Options options; options.threads = 8;
        const auto result = B::bake(charts, pages, lights, ambient, occluders, options);
        const auto probes = B::bakeProbes(points, lights, ambient, occluders, options, &result.bounce);
        const auto tree = B::buildProbeTree(points);
        const std::string prefix = argv[2];
        write(prefix + ".sky", result.sky); write(prefix + ".rtl", result.rtl); write(prefix + ".pages", result.rtlPages);
        write(prefix + ".probes", probes); write(prefix + ".tree", tree.nodes); write(prefix + ".refs", tree.references);
        std::cout << "{\"charted_texels\":" << result.chartedTexels << ",\"realtime_texels\":" << result.realtimeTexels
                  << ",\"rtl_pages\":" << result.rtlPages.size() << ",\"probes\":" << probes.size()
                  << ",\"probe_references\":" << tree.references.size() << ",\"probe_nodes\":" << tree.nodes.size() << "}\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
