#pragma once

#include <algorithm>
#include <array>
#include <utility>
#include <vector>

namespace Respawn {

struct CoverageBox {
    std::array<double, 3> mins, maxs;
};

inline bool coversBoxFraction(const CoverageBox &cell, const std::vector<CoverageBox> &input, double fraction) {
    double required = fraction;
    for (int axis = 0; axis < 3; ++axis) {
        if (!(cell.maxs[axis] > cell.mins[axis])) return false;
        required *= cell.maxs[axis] - cell.mins[axis];
    }
    std::vector<CoverageBox> boxes;
    std::vector<double> xs;
    for (const auto &candidate : input) {
        CoverageBox box;
        for (int axis = 0; axis < 3; ++axis) {
            box.mins[axis] = std::max(cell.mins[axis], candidate.mins[axis]);
            box.maxs[axis] = std::min(cell.maxs[axis], candidate.maxs[axis]);
        }
        if (box.mins[0] >= box.maxs[0] || box.mins[1] >= box.maxs[1] || box.mins[2] >= box.maxs[2]) continue;
        double volume = 1;
        for (int axis = 0; axis < 3; ++axis) volume *= box.maxs[axis] - box.mins[axis];
        if (volume >= required) return true;
        boxes.push_back(box);
        xs.push_back(box.mins[0]);
        xs.push_back(box.maxs[0]);
    }
    std::sort(xs.begin(), xs.end());
    xs.erase(std::unique(xs.begin(), xs.end()), xs.end());
    double covered = 0;
    for (std::size_t x = 1; x < xs.size(); ++x) {
        std::vector<const CoverageBox *> active;
        std::vector<double> ys;
        for (const auto &box : boxes) if (box.mins[0] <= xs[x - 1] && box.maxs[0] >= xs[x]) {
            active.push_back(&box);
            ys.push_back(box.mins[1]);
            ys.push_back(box.maxs[1]);
        }
        std::sort(ys.begin(), ys.end());
        ys.erase(std::unique(ys.begin(), ys.end()), ys.end());
        for (std::size_t y = 1; y < ys.size(); ++y) {
            std::vector<std::pair<double, double>> intervals;
            for (const auto *box : active) if (box->mins[1] <= ys[y - 1] && box->maxs[1] >= ys[y])
                intervals.emplace_back(box->mins[2], box->maxs[2]);
            std::sort(intervals.begin(), intervals.end());
            double length = 0, low = 0, high = 0;
            bool haveInterval = false;
            for (const auto &interval : intervals) {
                if (!haveInterval) { low = interval.first; high = interval.second; haveInterval = true; }
                else if (interval.first <= high) high = std::max(high, interval.second);
                else { length += high - low; low = interval.first; high = interval.second; }
            }
            if (haveInterval) length += high - low;
            covered += (xs[x] - xs[x - 1]) * (ys[y] - ys[y - 1]) * length;
            if (covered >= required) return true;
        }
    }
    return false;
}

} // namespace Respawn
