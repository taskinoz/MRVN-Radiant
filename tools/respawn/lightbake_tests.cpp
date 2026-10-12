// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/lightbake.h"
#include <iostream>

using namespace Respawn::Bake;

static void require(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}

static bool near(double a, double b, double tolerance) { return std::abs(a - b) <= tolerance; }

static Brush box(V3 mins, V3 maxs) {
    return {{{1, 0, 0, maxs.x}, {-1, 0, 0, -mins.x}, {0, 1, 0, maxs.y},
             {0, -1, 0, -mins.y}, {0, 0, 1, maxs.z}, {0, 0, -1, -mins.z}},
            mins, maxs};
}

// A 128x128 floor at z=0 facing up, mapped at 16 units per texel with a 2-texel border.
static Chart floorChart() {
    Chart chart;
    const double corners[4][2] = {{-64, -64}, {64, -64}, {64, 64}, {-64, 64}};
    for (const auto& c : corners) {
        chart.positions.push_back({c[0], c[1], 0});
        chart.normals.push_back({0, 0, 1});
        chart.luxels.push_back({(c[0] + 64) / 16 + 2, (c[1] + 64) / 16 + 2});
    }
    chart.triangles = {0, 1, 2, 0, 2, 3};
    return chart;
}

static std::uint32_t rtlWord(const Result& r, std::size_t texel) {
    std::uint32_t w = 0;
    for (int k = 0; k < 4; ++k) w |= std::uint32_t(r.rtl[texel * 4 + k]) << (8 * k);
    return w;
}

int main() {
    try {
        // Encodings measured from retail maps.
        for (double v : {0.004, 0.02, 0.2, 1.0, 3.5}) {
            const V3 d = decodeRGBM(encodeRGBM({v, v * 0.5, v * 0.25}));
            require(near(d.x, v, v * 0.02 + 0.0002) && near(d.z, v * 0.25, v * 0.02 + 0.0002), "RGBM round trip");
        }
        require(encodeRGBM({0, 0, 0}) == std::array<std::uint8_t, 4>{0, 0, 0, 0}, "Black encodes as zero");
        const V3 up = decodeDirection(encodeDirection({0, 0, 1}));
        require(near(up.x, 0, 0.01) && near(up.z, 1, 0.01), "Direction round trip");
        require(packRtlWord({0, 63, 63, 63}, 0) == 0x00ffffc0u, "Retail one-light RTL word");
        require(packRtlWord({1, 63, 63, 63}, 0) == 0x00ffffc1u, "Retail second-slot RTL word");

        // Coliseum light records: (zero, fifty) -> attenuation.
        const auto a = fitAttenuation(300, 90);
        require(near(a.linear, -0.006508, 1e-6) && near(a.quadratic, 1.0582e-5, 1e-8), "Coliseum point falloff");
        const auto b = fitAttenuation(350, 105);
        require(near(b.linear, -0.005578, 1e-6) && near(b.quadratic, 7.77e-6, 1e-8), "Coliseum spot falloff");
        Light probe; probe.zeroDistance = 300; probe.attenuation = a;
        require(near(falloff(probe, 90), 0.5, 1e-9) && falloff(probe, 300) == 0, "Falloff endpoints");

        // Occlusion.
        Occluders cube({box({-10, -10, -10}, {10, 10, 10})});
        require(cube.blocked({-20, 0, 0}, {20, 0, 0}), "Segment through brush is blocked");
        require(!cube.blocked({-20, 20, 0}, {20, 20, 0}), "Segment beside brush is open");
        require(!cube.blocked({-20, 10, 0}, {20, 10, 0}), "Grazing segment is open");
        require(!cube.blocked({0, 0, 11}, {0, 0, 50}), "Segment above brush is open");

        // A roof over the x<0 half of the floor shadows the sun there.
        std::vector<Brush> brushes{box({-200, -200, 100}, {0, 200, 116})};
        Occluders scene(brushes);
        Light sun;
        sun.type = LightType::Sun;
        sun.direction = {0, 0, -1};
        sun.intensity = {3, 3, 3};
        sun.hardwareIndex = 0;
        Light point;
        point.type = LightType::Point;
        point.origin = {0, 0, 1000};  // far beyond its zero distance
        point.intensity = {1, 1, 1};
        point.zeroDistance = 200;
        point.attenuation = fitAttenuation(200, 60);
        point.hardwareIndex = 1;
        Options options;
        options.threads = 2;
        const std::vector<PageSize> pages{{16, 16}};
        const Result r = bake({floorChart()}, pages, {sun, point}, {0.8, 0.8, 0.8}, scene, options);

        require(r.sky.size() == 16 * 16 * 8 && r.rtl.size() == 16 * 16 * 9, "Plane sizes match retail layout");
        require(r.rtlPages.size() == 1 && r.rtlPages[0][0] == 0, "Sun occupies the first RTL page entry");
        // Floor texels 2..9 cover world -64..64; texel 3 is under the roof, texel 8 is not.
        auto texel = [](int x, int y) { return std::size_t(y) * 16 + x; };
        const std::size_t shaded = texel(3, 8), lit = texel(8, 8), empty = texel(0, 15);
        require(rtlWord(r, shaded) == 0x00ffffc0u && rtlWord(r, lit) == 0x00ffffc0u, "Floor texels reference the sun");
        require(rtlWord(r, empty) == RtlUnusedTexel, "Unused texels are 0xffffffff");
        const std::uint8_t* rtlB = r.rtl.data() + 16 * 16 * 4;
        require(rtlB[shaded * 4] == 0, "Roofed texel is shadowed");
        require(rtlB[lit * 4] == 255, "Open texel sees the sun");
        const std::uint8_t* skyA = r.sky.data();
        const std::array<std::uint8_t, 4> shadedSky{skyA[shaded * 4], skyA[shaded * 4 + 1], skyA[shaded * 4 + 2], skyA[shaded * 4 + 3]};
        const std::array<std::uint8_t, 4> litSky{skyA[lit * 4], skyA[lit * 4 + 1], skyA[lit * 4 + 2], skyA[lit * 4 + 3]};
        require(decodeRGBM(litSky).x > decodeRGBM(shadedSky).x, "Roof reduces sky ambient");
        // Fill is ambient * scale * (0.4 + 0.6 * visibility); some hemisphere rays
        // from the open texel still reach the roof.
        const double open = decodeRGBM(litSky).x / (0.8 * options.ambientScale);
        require(open > 0.76 && open < 1.01, "Open sky fill uses ambient * scale * (0.4 + 0.6 * visibility)");
        require(decodeRGBM(shadedSky).x >= 0.8 * options.ambientScale * 0.39, "Fill keeps its 40% floor");
        // SKY B: bent sky direction scaled by cbrt(visibility).
        const std::uint8_t* skyB = r.sky.data() + 16 * 16 * 4;
        auto skyVector = [&](std::size_t i) {
            return decodeDirection({skyB[i * 4], skyB[i * 4 + 1], skyB[i * 4 + 2], skyB[i * 4 + 3]});
        };
        require(length(skyVector(lit)) > length(skyVector(shaded)) + 0.1, "Roof shortens the sky vector");
        require(skyVector(lit).z > 0.5 && length(skyVector(lit)) <= 1.01, "Open sky vector points up");
        require(skyVector(shaded).x > 0, "Roofed sky vector bends towards the open side");
        require(r.chartedTexels >= 64, "Floor covers its texels");

        // An unscaled static light lands in SKY A instead of RTL.
        Light lamp = point;
        lamp.origin = {0, 0, 50};
        lamp.realtime = false;
        const Result s = bake({floorChart()}, pages, {lamp}, {0, 0, 0}, Occluders(), options);
        const std::array<std::uint8_t, 4> centre{s.sky[texel(6, 6) * 4], s.sky[texel(6, 6) * 4 + 1],
                                                 s.sky[texel(6, 6) * 4 + 2], s.sky[texel(6, 6) * 4 + 3]};
        require(decodeRGBM(centre).x > 0.3, "Static light is baked into SKY A");
        require(rtlWord(s, texel(6, 6)) == RtlUnusedTexel, "Static light takes no RTL slot");

        // Probes: one under the roof, one in the open next to a realtime point light.
        require(cube.inside({0, 0, 0}) && !cube.inside({0, 0, 20}), "Point-in-brush test");
        Light lamp2 = point;
        lamp2.origin = {200, 0, 80};
        const std::vector<V3> probePoints{{-100, 0, 50}, {150, 0, 50}};
        const auto probes = bakeProbes(probePoints, {sun, lamp2}, {0.8, 0.8, 0.8}, scene, options);
        require(probes[0].values[15] == 0 && probes[1].values[15] == 8192, "Probe sun visibility");
        require(probes[1].values[14] > probes[0].values[14], "Open probe sky vector is longer upwards");
        require(probes[1].lights[0] == 1 && probes[1].weights[0] == 255 && probes[1].lights[1] == -1, "Probe local light link");
        require(probes[0].lights[0] == -1, "Out-of-range light is not linked");
        require(probes[1].values[3] > 0 && probes[1].values[3] < 8192, "Ambient W term in fixed point");

        // KD tree: every probe referenced once, leaves of at most eight, cuts separate children.
        std::vector<V3> cloud;
        for (int i = 0; i < 300; ++i)
            cloud.push_back({double((i * 37) % 101), double((i * 59) % 89), double((i * 13) % 17)});
        const ProbeTree tree = buildProbeTree(cloud);
        std::vector<int> seen(cloud.size(), 0);
        for (const auto& ref : tree.references) seen.at(ref.probe)++;
        require(std::all_of(seen.begin(), seen.end(), [](int n) { return n == 1; }), "Each probe referenced once");
        std::function<void(std::uint32_t, std::vector<std::uint32_t>&)> collect = [&](std::uint32_t node, std::vector<std::uint32_t>& out) {
            const auto& n = tree.nodes.at(node);
            if ((n[0] & 3) == 3) {
                require(n[1] >= 1 && n[1] <= 8, "Leaf size");
                for (std::uint32_t i = 0; i < n[1]; ++i) out.push_back((n[0] >> 2) + i);
                return;
            }
            std::vector<std::uint32_t> left, right;
            collect(n[0] >> 2, left);
            collect((n[0] >> 2) + 1, right);
            float cut;
            std::memcpy(&cut, &n[1], 4);
            auto axisOf = [&](std::uint32_t r) {
                const auto& ref = tree.references[r];
                return (n[0] & 3) == 0 ? ref.x : (n[0] & 3) == 1 ? ref.y : ref.z;
            };
            for (auto r : left) require(axisOf(r) <= cut, "Left subtree lies below the cut");
            for (auto r : right) require(axisOf(r) >= cut, "Right subtree lies above the cut");
            out.insert(out.end(), left.begin(), left.end());
            out.insert(out.end(), right.begin(), right.end());
        };
        std::vector<std::uint32_t> all;
        collect(0, all);
        require(all.size() == cloud.size(), "Tree covers every reference");

        std::cout << "Lightmap bake tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
