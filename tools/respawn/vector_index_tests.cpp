// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/vector_index.h"
#include <array>
#include <iostream>
#include <random>
#include <stdexcept>
using Point = std::array<float, 3>;
static constexpr float epsilon = .001f;
static bool equal(const Point &a, const Point &b) {
    return std::abs(a[0]-b[0]) < epsilon && std::abs(a[1]-b[1]) < epsilon && std::abs(a[2]-b[2]) < epsilon;
}
int main() {
    try {
        Respawn::VectorIndex index(epsilon);
        std::vector<Point> points;
        auto check = [&](Point p) {
            uint32_t expected = UINT32_MAX;
            for (uint32_t i = 0; i < points.size(); ++i)
                if (equal(p, points[i])) { expected = i; break; }
            if (index.find(p, points, equal) != expected)
                throw std::runtime_error("Spatial lookup differs from first-match scan");
        };
        // Epsilon equality is not transitive; insertion order must win even
        // when a later matching vector occupies the query's own cell.
        points = {{{-.0008f, 0, 0}}, {{.0008f, 0, 0}}};
        check({0, 0, 0});
        for (float boundary : {-.004f, -.002f, 0.f, .002f, .004f}) {
            points.push_back({boundary, boundary, boundary});
            for (float delta : {-epsilon, -epsilon*.999f, 0.f, epsilon*.999f, epsilon})
                check({boundary+delta, boundary-delta, boundary});
        }
        std::mt19937 random(617);
        std::uniform_real_distribution<float> coordinate(-5.f, 5.f);
        for (int n = 0; n < 5000; ++n) {
            Point p{coordinate(random), coordinate(random), coordinate(random)};
            check(p);
            // Simulate collision code appending directly, outside EmitVertex.
            points.push_back(p);
            check(p);
            p[0] += epsilon*.9f;
            check(p);
        }
        const float huge = std::numeric_limits<float>::max();
        points.push_back({huge, -huge, huge});
        check(points.back());
        const float nan = std::numeric_limits<float>::quiet_NaN();
        points.push_back({nan, 0, 0});
        check(points.back());
        const float inf = std::numeric_limits<float>::infinity();
        points.push_back({inf, 0, 0});
        check(points.back());
        // Shrink detection, followed by explicit reset for same-size replacement.
        points.clear(); check({0, 0, 0});
        points.push_back({1, 2, 3}); check({1, 2, 3});
        index.clear(); points[0] = {4, 5, 6}; check({4, 5, 6}); check({1, 2, 3});
        std::cout << "Vector lookup agrees with first-match scan\n";
    } catch (const std::exception &e) { std::cerr << e.what() << '\n'; return 1; }
}
