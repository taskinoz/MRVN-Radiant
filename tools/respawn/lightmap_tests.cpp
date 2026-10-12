// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/lightmap.h"
#include <iostream>
#include <limits>

static void require(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}

int main() {
    try {
        std::vector<Respawn::LightmapRect> rects;
        for (int i = 0; i < 200; ++i)
            rects.push_back({-30.25, -10.5, 7.75 + i % 3, 20.5});
        const auto placements = Respawn::packLightmapRects(rects, 128, 128, 2);
        require(placements.size() == rects.size(), "All islands must be placed");
        for (std::size_t i = 0; i < rects.size(); ++i) {
            const auto& p = placements[i]; const auto& a = rects[i];
            const double x0 = a.minX + p.offsetX - 2, y0 = a.minY + p.offsetY - 2;
            const double x1 = a.maxX + p.offsetX + 2, y1 = a.maxY + p.offsetY + 2;
            require(x0 >= 0 && y0 >= 0 && x1 < 128 && y1 < 128, "Island/gutter must fit page");
            const double u = (a.minX + p.offsetX) * (1.0 / 128);
            require(u > 0 && u < 1, "Normalized UV scale must not be zero");
            for (std::size_t j = 0; j < i; ++j) {
                const auto& q = placements[j]; const auto& b = rects[j];
                if (p.page == q.page)
                    require(x1 < b.minX + q.offsetX - 2 || x0 > b.maxX + q.offsetX + 2 ||
                            y1 < b.minY + q.offsetY - 2 || y0 > b.maxY + q.offsetY + 2,
                            "Packed islands including gutters must not overlap");
            }
        }
        require(placements.back().page > 0, "Fixture must exercise page rollover");
        for (const auto& bad : std::vector<Respawn::LightmapRect>{
                 {0, 0, 1024, 1}, {1, 0, 0, 1}, {0, 0, std::numeric_limits<double>::infinity(), 1}}) {
            bool rejected = false;
            try { Respawn::packLightmapRects({bad}, 128, 128, 2); }
            catch (const std::invalid_argument&) { rejected = true; }
            require(rejected, "Oversized/nonfinite/inverted rectangle must be rejected");
        }
        std::cout << "Lightmap packing tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n'; return 1;
    }
}
