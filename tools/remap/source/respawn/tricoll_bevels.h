// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include <algorithm>
#include <cstdint>
#include <map>
#include <stdexcept>
#include <vector>

namespace Respawn {
struct TricollBevelReference {
    std::uint32_t header;
    std::uint32_t triangle;
};

struct TricollBevelEncoding {
    std::vector<std::uint32_t> words;
    std::vector<std::uint16_t> starts;
    std::vector<std::uint8_t> counts;
    std::uint16_t indexCount = 0;
};

// Serialize an already selected list of clipping-plane triangle references.
// This deliberately does not select bevel geometry. TF1 uses 10-bit values,
// TF2 11-bit values. See RESPAWN_TRICOLL_PORTALS.md for the retail chain layout.
inline TricollBevelEncoding encodeTricollBevels(
        unsigned width, std::uint32_t current,
        const std::vector<std::uint16_t>& triangleCounts,
        const std::vector<std::vector<TricollBevelReference>>& references) {
    if (width != 10 && width != 11)
        throw std::runtime_error("Tricoll bevel values must use 10 or 11 bits");
    if (triangleCounts.size() > 65536 || current >= triangleCounts.size() ||
        !triangleCounts[current] || references.size() != triangleCounts[current])
        throw std::runtime_error("Tricoll bevel source header/triangle count is invalid");
    const std::uint32_t valueLimit = 1u << width;
    const std::uint32_t headerLimit = 1u << (2 * width - 7);
    std::vector<std::uint32_t> values;
    TricollBevelEncoding result;
    const auto append = [&](std::uint32_t value) {
        if (values.size() == 65535)
            throw std::runtime_error("Tricoll bevel index count exceeds 16 bits; repartition the header");
        values.push_back(value);
    };
    const auto descriptor = [&](std::uint32_t target, std::uint32_t count) {
        if (target >= headerLimit)
            throw std::runtime_error("Tricoll bevel chain header index exceeds its packed field");
        const std::uint32_t entry = (target << 7) | count;
        append(entry & (valueLimit - 1));
        append(entry >> width);
    };
    for (const auto& list : references) {
        std::map<std::uint32_t, std::vector<std::uint32_t>> groups;
        for (const auto& ref : list) {
            if (ref.header >= triangleCounts.size() ||
                ref.triangle >= triangleCounts[ref.header] || ref.triangle >= valueLimit)
                throw std::runtime_error("Tricoll bevel reference exceeds its target triangle range");
            groups[ref.header].push_back(ref.triangle);
        }
        // Empty triangles use zero even after a full 65535-value header.
        result.starts.push_back(list.empty() ? 0 : static_cast<std::uint16_t>(values.size()));
        if (list.size() < 15 && (groups.empty() || (groups.size() == 1 && groups.begin()->first == current))) {
            result.counts.push_back(static_cast<std::uint8_t>(list.size()));
            for (const auto& ref : list) append(ref.triangle);
            continue;
        }
        result.counts.push_back(15);
        const auto own = groups.find(current);
        // A segment naming its own header terminates the chain immediately;
        // it must be last and cannot be split into two 7-bit-count segments.
        if (own != groups.end() && own->second.size() > 127)
            throw std::runtime_error("Tricoll bevel list has more than 127 local targets; repartition the header");
        for (const auto& group : groups) {
            if (group.first == current) continue;
            for (std::size_t first = 0; first < group.second.size(); first += 127) {
                const auto amount = std::min<std::size_t>(127, group.second.size() - first);
                descriptor(group.first, static_cast<std::uint32_t>(amount));
                for (std::size_t k = first; k < first + amount; ++k) append(group.second[k]);
            }
        }
        if (own == groups.end()) {
            // Native traversal stops only when the segment names its own
            // header. Zero count on a foreign header does not terminate it.
            descriptor(current, 0);
        } else {
            descriptor(current, static_cast<std::uint32_t>(own->second.size()));
            for (const auto target : own->second) append(target);
        }
    }
    result.indexCount = static_cast<std::uint16_t>(values.size());
    result.words.resize((values.size() * width + 31) / 32, 0);
    for (std::size_t i = 0; i < values.size(); ++i) {
        const std::size_t bit = i * width, word = bit / 32;
        const unsigned shift = static_cast<unsigned>(bit % 32);
        result.words[word] |= values[i] << shift;
        if (shift + width > 32) result.words[word + 1] |= values[i] >> (32 - shift);
    }
    return result;
}
} // namespace Respawn
