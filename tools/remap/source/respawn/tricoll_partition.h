// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#pragma once
#include "tricoll_bevels.h"
#include <limits>

namespace Respawn {
struct TricollBevelChunk {
    std::size_t batch;
    std::uint32_t firstTriangle;
    std::uint16_t triangleCount;
    TricollBevelEncoding bevels;
    std::uint32_t droppedReferences = 0;  // unencodable chain targets, see below
};

// Batches preserve material/contents ownership; references use entity-wide
// triangle IDs so an edge may cross a material or header boundary. Splitting
// changes only storage, never the geometry or the selected plane multiset.
inline std::vector<TricollBevelChunk> partitionTricollBevels(
        unsigned width, const std::vector<std::uint16_t>& precedingTriangleCounts,
        const std::vector<std::uint32_t>& batchSizes,
        const std::vector<std::vector<std::uint32_t>>& references,
        unsigned maxTriangles = 300) {
    if ((width != 10 && width != 11) || !maxTriangles || maxTriangles > (1u << width))
        throw std::runtime_error("Invalid tricoll partition width or triangle limit");
    std::uint64_t total = 0;
    for (const auto size : batchSizes) total += size;
    if (total != references.size() || total > std::numeric_limits<std::uint32_t>::max())
        throw std::runtime_error("Tricoll partition batches do not match the triangle references");
    for (const auto& list : references) {
        if (list.size() > 65535)
            throw std::runtime_error("A triangle's bevel list exceeds the native 16-bit stream capacity");
        for (const auto target : list)
            if (target >= total) throw std::runtime_error("Tricoll partition target is outside the entity");
    }
    std::vector<TricollBevelChunk> chunks;
    std::uint32_t first = 0;
    for (std::size_t batch = 0; batch < batchSizes.size(); ++batch) {
        for (std::uint32_t offset = 0; offset < batchSizes[batch];) {
            const auto amount = std::min<std::uint32_t>(maxTriangles, batchSizes[batch] - offset);
            chunks.push_back({batch, first + offset, static_cast<std::uint16_t>(amount), {}});
            offset += amount;
        }
        first += batchSizes[batch];
    }
    std::vector<std::uint32_t> owner(references.size());
    for (;;) {
        if (precedingTriangleCounts.size() > 65536 || chunks.size() > 65536 - precedingTriangleCounts.size())
            throw std::runtime_error("Tricoll partition exceeds the native 16-bit primitive header field");
        for (std::size_t h = 0; h < chunks.size(); ++h)
            for (std::uint32_t i = 0; i < chunks[h].triangleCount; ++i)
                owner[chunks[h].firstTriangle + i] = static_cast<std::uint32_t>(h);
        std::vector<bool> split(chunks.size(), false);
        bool anySplit = false;
        for (std::size_t h = 0; h < chunks.size(); ++h) {
            std::size_t values = 0;
            for (std::uint32_t i = 0; i < chunks[h].triangleCount; ++i) {
                const auto& list = references[chunks[h].firstTriangle + i];
                std::map<std::uint32_t, std::size_t> groups;
                for (const auto target : list) ++groups[owner[target]];
                const auto own = groups.find(static_cast<std::uint32_t>(h));
                if (list.size() < 15 && (groups.empty() || (groups.size() == 1 && own != groups.end()))) {
                    values += list.size();
                } else {
                    values += list.size();
                    if (own == groups.end()) values += 2; // current-header zero-count sentinel
                    for (const auto& group : groups) {
                        if (group.first == h && group.second > 127) split[h] = true;
                        values += 2 * ((group.second + 126) / 127);
                    }
                }
                if (values > 65535) split[h] = true;
            }
            if (split[h]) {
                if (chunks[h].triangleCount == 1)
                    throw std::runtime_error("One triangle's bevel chain cannot fit the native header limits");
                anySplit = true;
            }
        }
        if (!anySplit) break;
        std::vector<TricollBevelChunk> refined;
        for (std::size_t h = 0; h < chunks.size(); ++h) {
            const auto& chunk = chunks[h];
            if (!split[h]) { refined.push_back(chunk); continue; }
            const auto left = static_cast<std::uint16_t>(chunk.triangleCount / 2);
            refined.push_back({chunk.batch, chunk.firstTriangle, left, {}});
            refined.push_back({chunk.batch, chunk.firstTriangle + left,
                               static_cast<std::uint16_t>(chunk.triangleCount - left), {}});
        }
        chunks.swap(refined);
        // A split changes foreign segment counts as well as local counts, so
        // re-check every header until all streams fit the final partition.
    }
    auto counts = precedingTriangleCounts;
    for (const auto& chunk : chunks) counts.push_back(chunk.triangleCount);
    for (std::size_t h = 0; h < chunks.size(); ++h) {
        auto& chunk = chunks[h];
        // Chain segments store their header in 2 * width - 7 bits (8192 TF1
        // headers, 32768 TF2), and every chain ends on a segment naming its own
        // header. Beyond that, keep what a plain list can hold: up to 14 targets
        // in the triangle's own header. Bevels only trim early hull contacts, so
        // dropping one leaves collision conservative.
        const std::uint32_t headerLimit = 1u << (2 * width - 7);
        const auto current = static_cast<std::uint32_t>(precedingTriangleCounts.size() + h);
        std::vector<std::vector<TricollBevelReference>> local(chunk.triangleCount);
        for (std::uint32_t i = 0; i < chunk.triangleCount; ++i) {
            const auto& list = references[chunk.firstTriangle + i];
            for (const auto target : list) {
                const auto targetChunk = owner[target];
                const auto header = static_cast<std::uint32_t>(precedingTriangleCounts.size() + targetChunk);
                if (header != current && header >= headerLimit) { ++chunk.droppedReferences; continue; }
                local[i].push_back({header, target - chunks[targetChunk].firstTriangle});
            }
            const bool chain = local[i].size() >= 15 ||
                std::any_of(local[i].begin(), local[i].end(), [&](const auto& ref) { return ref.header != current; });
            if (chain && current >= headerLimit) {
                std::vector<TricollBevelReference> own;
                for (const auto& ref : local[i])
                    if (ref.header == current && own.size() < 14) own.push_back(ref);
                chunk.droppedReferences += static_cast<std::uint32_t>(local[i].size() - own.size());
                local[i].swap(own);
            }
        }
        chunk.bevels = encodeTricollBevels(width,
            static_cast<std::uint32_t>(precedingTriangleCounts.size() + h), counts, local);
    }
    return chunks;
}
} // namespace Respawn
