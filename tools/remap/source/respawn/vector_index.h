// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include <cmath>
#include <cstdint>
#include <limits>
#include <vector>

namespace Respawn {
// Append-only epsilon lookup. The predicate must use the supplied per-axis
// epsilon. Keep the earliest matching index, including non-transitive matches.
// Clear before replacing or modifying existing elements of the source array.
class VectorIndex {
    static constexpr uint32_t missing = UINT32_MAX;
    const double cell;
    std::vector<uint32_t> heads;
    std::vector<uint32_t> next;
    uint32_t fallback = missing;

    static uint64_t key(int64_t x, int64_t y, int64_t z) {
        uint64_t h = static_cast<uint64_t>(x) * 0x9E3779B97F4A7C15ull;
        h ^= static_cast<uint64_t>(y) * 0xC2B2AE3D27D4EB4Full + (h << 6) + (h >> 2);
        h ^= static_cast<uint64_t>(z) * 0x165667B19E3779F9ull + (h << 6) + (h >> 2);
        return h;
    }
    template<class Point> bool coordinates(const Point &v, int64_t (&q)[3]) const {
        for (int a = 0; a < 3; ++a) {
            const double value = std::floor(static_cast<double>(v[a]) / cell);
            // Avoid undefined float-to-integer conversions and leave room for
            // neighbouring cells. Extreme or nonfinite vectors use a scan.
            if (!std::isfinite(value) || std::abs(value) >= 0x1p62) return false;
            q[a] = static_cast<int64_t>(value);
        }
        return true;
    }
public:
    explicit VectorIndex(double epsilon) : cell(2 * epsilon) {}
    void clear() {
        // Contiguous buckets and links avoid per-cell heap allocations and can
        // be released before the much larger lighting buffers are allocated.
        std::vector<uint32_t>().swap(heads);
        std::vector<uint32_t>().swap(next);
        fallback = missing;
    }
    template<class Point, class Equal>
    uint32_t find(const Point &v, const std::vector<Point> &data, Equal equal) {
        if (data.size() < next.size()) clear();
        if (heads.empty() || data.size() > heads.size() / 2) {
            std::size_t capacity = 64;
            while (data.size() > capacity / 2) capacity *= 2;
            heads.assign(capacity, missing);
            next.clear();
            fallback = missing;
        }
        for (std::size_t i = next.size(); i < data.size(); ++i) {
            int64_t q[3];
            next.push_back(missing);
            if (coordinates(data[i], q)) {
                auto &head = heads[key(q[0], q[1], q[2]) & (heads.size() - 1)];
                next[i] = head;
                head = static_cast<uint32_t>(i);
            } else {
                next[i] = fallback;
                fallback = static_cast<uint32_t>(i);
            }
        }
        uint32_t best = missing;
        auto scan = [&](uint32_t i) {
            for (; i != missing; i = next[i])
                if (i < best && equal(v, data[i])) best = i;
        };
        int64_t q[3];
        if (!coordinates(v, q)) {
            for (std::size_t i = 0; i < data.size(); ++i)
                if (equal(v, data[i])) return static_cast<uint32_t>(i);
            return missing;
        }
        scan(fallback);
        // A matching vector must lie in the query cell or an adjacent cell.
        for (int dx = -1; dx <= 1; ++dx)
            for (int dy = -1; dy <= 1; ++dy)
                for (int dz = -1; dz <= 1; ++dz) {
                    // Hash collisions may add candidates, never suppress a
                    // match: every candidate still passes the exact predicate.
                    scan(heads[key(q[0] + dx, q[1] + dy, q[2] + dz) & (heads.size() - 1)]);
                }
        return best;
    }
};
} // namespace Respawn
