// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
// Original bounded shelf packer. Packing does not define engine texel encoding.
#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <vector>

namespace Respawn {
struct LightmapRect { double minX, minY, maxX, maxY; };
struct LightmapPlacement { std::uint32_t page; double offsetX, offsetY; };
struct LightmapPageExtent { std::uint32_t width, height; };

// Shelf packer that keeps its state between calls, so charts from separately
// compiled entities share pages without overlapping.
class LightmapAtlas {
    std::uint32_t m_width = 0, m_height = 0, m_gutter = 0;
    std::uint32_t m_x = 0, m_y = 0, m_rowHeight = 0;
    std::vector<LightmapPageExtent> m_used;

public:
    LightmapAtlas() = default;
    LightmapAtlas(std::uint32_t width, std::uint32_t height, std::uint32_t gutter) {
        reset(width, height, gutter);
    }

    void reset(std::uint32_t width, std::uint32_t height, std::uint32_t gutter) {
        if (!width || !height || width > 65536 || height > 65536 ||
            gutter >= width / 2 || gutter >= height / 2)
            throw std::invalid_argument("Invalid lightmap page dimensions/gutter");
        m_width = width; m_height = height; m_gutter = gutter;
        m_x = m_y = m_rowHeight = 0;
        m_used.clear();
    }

    std::uint32_t width() const { return m_width; }
    std::uint32_t height() const { return m_height; }
    std::size_t pageCount() const { return m_used.size(); }
    // Used area of each page, including gutters.
    const std::vector<LightmapPageExtent>& used() const { return m_used; }

    LightmapPlacement place(const LightmapRect& rect) {
        if (!m_width)
            throw std::logic_error("Lightmap atlas has not been configured");
        if (!std::isfinite(rect.minX) || !std::isfinite(rect.minY) ||
            !std::isfinite(rect.maxX) || !std::isfinite(rect.maxY) ||
            rect.maxX < rect.minX || rect.maxY < rect.minY)
            throw std::invalid_argument("Invalid lightmap rectangle");
        const double rw = std::ceil(rect.maxX - rect.minX) + 1 + 2 * m_gutter;
        const double rh = std::ceil(rect.maxY - rect.minY) + 1 + 2 * m_gutter;
        if (rw > m_width || rh > m_height)
            throw std::invalid_argument("Lightmap island exceeds page; splitting is required");
        const auto w = static_cast<std::uint32_t>(rw);
        const auto h = static_cast<std::uint32_t>(rh);
        if (m_used.empty()) m_used.push_back({0, 0});
        if (m_x + w > m_width) { m_x = 0; m_y += m_rowHeight; m_rowHeight = 0; }
        if (m_y + h > m_height) {
            m_x = m_y = m_rowHeight = 0;
            m_used.push_back({0, 0});
        }
        const auto page = static_cast<std::uint32_t>(m_used.size() - 1);
        if (page > 32767)
            throw std::invalid_argument("Lightmap page index exceeds signed 16-bit field");
        const LightmapPlacement result{page, m_x + m_gutter - rect.minX, m_y + m_gutter - rect.minY};
        m_x += w;
        if (h > m_rowHeight) m_rowHeight = h;
        auto& extent = m_used.back();
        extent.width = std::max(extent.width, m_x);
        extent.height = std::max(extent.height, m_y + h);
        return result;
    }
};

inline std::vector<LightmapPlacement> packLightmapRects(
    const std::vector<LightmapRect>& rects, std::uint32_t width,
    std::uint32_t height, std::uint32_t gutter) {
    LightmapAtlas atlas(width, height, gutter);
    std::vector<LightmapPlacement> result;
    result.reserve(rects.size());
    for (const auto& rect : rects)
        result.push_back(atlas.place(rect));
    return result;
}
}
