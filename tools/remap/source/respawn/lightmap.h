// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
// Original bounded shelf packer. Packing does not define engine texel encoding.
#pragma once
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace Respawn {
struct LightmapRect { double minX, minY, maxX, maxY; };
struct LightmapPlacement { std::uint32_t page; double offsetX, offsetY; };

inline std::vector<LightmapPlacement> packLightmapRects(
    const std::vector<LightmapRect>& rects, std::uint32_t width,
    std::uint32_t height, std::uint32_t gutter) {
    if (!width || !height || width > 65536 || height > 65536 ||
        gutter >= width / 2 || gutter >= height / 2)
        throw std::invalid_argument("Invalid lightmap page dimensions/gutter");
    std::vector<LightmapPlacement> result;
    std::uint32_t x = 0, y = 0, rowHeight = 0, page = 0;
    for (const auto& rect : rects) {
        if (!std::isfinite(rect.minX) || !std::isfinite(rect.minY) ||
            !std::isfinite(rect.maxX) || !std::isfinite(rect.maxY) ||
            rect.maxX < rect.minX || rect.maxY < rect.minY)
            throw std::invalid_argument("Invalid lightmap rectangle");
        const double rw = std::ceil(rect.maxX - rect.minX) + 1 + 2 * gutter;
        const double rh = std::ceil(rect.maxY - rect.minY) + 1 + 2 * gutter;
        if (rw > width || rh > height)
            throw std::invalid_argument("Lightmap island exceeds page; splitting is required");
        const auto w = static_cast<std::uint32_t>(rw);
        const auto h = static_cast<std::uint32_t>(rh);
        if (x + w > width) { x = 0; y += rowHeight; rowHeight = 0; }
        if (y + h > height) { x = y = rowHeight = 0; ++page; }
        if (page > 32767)
            throw std::invalid_argument("Lightmap page index exceeds signed 16-bit field");
        result.push_back({page, x + gutter - rect.minX, y + gutter - rect.minY});
        x += w;
        if (h > rowHeight) rowHeight = h;
    }
    return result;
}
}
