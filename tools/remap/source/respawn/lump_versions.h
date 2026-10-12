/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Versions observed in the local corpus and cross-checked against bsp_tool's
 * Titanfall/Titanfall 2 schemas. See docs/RESPAWN_SAMPLES.md and RESPAWN_SOURCES.md.
 */
#pragma once
#include <cstddef>
#include <cstdint>

namespace Respawn {
// For the currently generated R1/R2 layouts. R5 uses distinct v0 records.
constexpr std::uint32_t generatedLumpVersion(std::uint32_t bspVersion, std::size_t index) {
    if (bspVersion != 29 && bspVersion != 37) return 0;
    switch (index) {
    case 0x01: // planes
    case 0x02: // texture data
    case 0x24: // leaf water data
    case 0x44: // triangle collision nodes
    case 0x45: // triangle collision headers
    case 0x48: // lit flat vertices
    case 0x49: // lit bump vertices
    case 0x53: // lightmap headers
        return 1;
    case 0x42: // packed triangle collision indices
        return 2;
    case 0x36: // R2 world-light stub uses the v3 record layout
        return bspVersion == 37 ? 3 : 1;
    default:
        return 0;
    }
}
} // namespace Respawn
