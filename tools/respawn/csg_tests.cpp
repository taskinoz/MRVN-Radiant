// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/csg.h"
#include <iostream>
#include <stdexcept>

using namespace Respawn::Csg;

static void require(bool value, const char* why) {
    if (!value) throw std::runtime_error(why);
}

static Solid box(Point lo, Point hi, int order) {
    return {{{{1, 0, 0}, hi[0]}, {{-1, 0, 0}, -lo[0]}, {{0, 1, 0}, hi[1]},
             {{0, -1, 0}, -lo[1]}, {{0, 0, 1}, hi[2]}, {{0, 0, -1}, -lo[2]}},
            lo, hi, order};
}

static double total(const std::vector<Polygon>& fragments) {
    double sum = 0;
    for (const auto& f : fragments) sum += area(f);
    return sum;
}

int main() {
    try {
        // Top face of a 256x256 floor at z=0 (owner 0).
        const Polygon floorTop{{-128, -128, 0}, {128, -128, 0}, {128, 128, 0}, {-128, 128, 0}};
        const Plane up{{0, 0, 1}, 0};

        // A crate resting on the floor only partly covers it: the face is kept whole
        // (depth hides the covered part) rather than fragmented.
        auto resting = visibleFragments(floorTop, up, 0, {box({-32, -32, 0}, {32, 32, 64}, 1)});
        require(resting.size() == 1 && std::abs(total(resting) - 256.0 * 256) < 1, "Partly covered face stays whole");

        // A crate's bottom face resting on the floor is fully hidden.
        const Polygon crateBottom{{-32, -32, 0}, {-32, 32, 0}, {32, 32, 0}, {32, -32, 0}};
        auto bottom = visibleFragments(crateBottom, {{0, 0, -1}, 0}, 1, {box({-128, -128, -16}, {128, 128, 0}, 0)});
        require(bottom.empty(), "Face flush against a solid, facing into it, is removed");

        // A floating crate hides nothing.
        auto floating = visibleFragments(floorTop, up, 0, {box({-32, -32, 10}, {32, 32, 64}, 1)});
        require(floating.size() == 1 && std::abs(total(floating) - 256.0 * 256) < 1, "Floating crate hides nothing");

        // A face buried inside another brush disappears.
        auto buried = visibleFragments(floorTop, up, 0, {box({-200, -200, -50}, {200, 200, 50}, 1)});
        require(buried.empty(), "Buried face is removed");

        // Coplanar top faces of overlapping brushes: only the later brush keeps the overlap.
        const Solid later = box({0, -128, -16}, {256, 128, 0}, 1);
        auto earlierFace = visibleFragments(floorTop, up, 0, {later});
        require(std::abs(total(earlierFace) - 128.0 * 256) < 1, "Earlier brush loses the shared region");
        const Polygon laterTop{{0, -128, 0}, {256, -128, 0}, {256, 128, 0}, {0, 128, 0}};
        auto laterFace = visibleFragments(laterTop, up, 1, {box({-128, -128, -16}, {128, 128, 0}, 0)});
        require(std::abs(total(laterFace) - 256.0 * 256) < 1, "Later brush keeps its whole face");

        std::cout << "CSG face tests passed\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
