// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace Respawn {
inline std::string textureName(std::string name) {
    if (name.compare(0, 9, "textures/") == 0 || name.compare(0, 9, "textures\\") == 0)
        name.erase(0, 9);
    std::replace(name.begin(), name.end(), '/', '\\');
    if (name.empty() || name.find('\0') != std::string::npos)
        throw std::runtime_error("Invalid empty or NUL-containing texture name");
    return name;
}

// Match the complete NUL-terminated name at a record's offset.
inline bool textureNameEquals(const std::vector<char>& pool, std::size_t offset,
                              const std::string& name) {
    return offset < pool.size() && name.size() < pool.size() - offset &&
           pool[offset + name.size()] == '\0' &&
           std::equal(name.begin(), name.end(), pool.begin() + offset);
}

// Upper triangle nibble: lowest-Z vertex and which of the other two is
// highest. The observed TF1/TF2 rule breaks minimum ties toward the first
// vertex and maximum ties toward the last: a horizontal triangle is 4.
// Rare retail exceptions are recorded in RESPAWN_TRICOLL_PORTALS.md.
inline std::uint32_t triangleZOrder(const std::array<float, 3>& z) {
    int low = 0, high = 0;
    for (int k = 1; k < 3; ++k) {
        if (z[k] < z[low]) low = k;
        if (z[k] >= z[high]) high = k;
    }
    const int firstOther = 1 & ~low;
    return static_cast<std::uint32_t>(low | ((firstOther != high) << 2));
}

struct BoundsAxis { std::int16_t origin; std::int16_t extent; };

inline BoundsAxis quantizeBoundsAxis(double minimum, double maximum) {
    if (!std::isfinite(minimum) || !std::isfinite(maximum) || minimum > maximum)
        throw std::runtime_error("Collision bounds must be finite and ordered");
    const double center = std::round(minimum * 0.5 + maximum * 0.5);
    // Preserve the existing two-unit collision margin and compensate for the
    // rounded center so neither side of a fractional brush is lost.
    const double extent = std::ceil(std::max(center - minimum, maximum - center) + 2.0);
    if (center < -32768 || center > 32767 || extent < 0 || extent > 32767)
        throw std::runtime_error("Collision bounds exceed the signed 16-bit representation");
    return {static_cast<std::int16_t>(center), static_cast<std::int16_t>(extent)};
}
} // namespace Respawn
