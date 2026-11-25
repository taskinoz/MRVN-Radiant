/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Minimal BC6H_UF16 encoder: every block uses mode 11 (one region, 10-bit
 * endpoints, 4-bit indices), from the D3D11 block compression specification.
 * Enough for blurry environment maps such as Titanfall 2 cubemaps.
 */
#pragma once

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>

namespace Respawn::BC6H {

// Non-negative float to IEEE half bits, clamped to the largest finite half.
inline std::uint16_t halfBits(float value) {
    if (!(value > 0)) return 0;
    if (value >= 65504.0f) return 0x7BFF;
    std::uint32_t f;
    std::memcpy(&f, &value, 4);
    const int exponent = int((f >> 23) & 0xFF) - 127 + 15;
    const std::uint32_t mantissa = f & 0x7FFFFF;
    if (exponent <= 0) {
        if (exponent < -10) return 0;
        const std::uint32_t m = (mantissa | 0x800000) >> (1 - exponent);
        return std::uint16_t((m + 0x1000) >> 13);
    }
    const std::uint32_t h = (std::uint32_t(exponent) << 10) | (mantissa >> 13);
    const std::uint32_t round = (mantissa >> 12) & 1;
    return std::uint16_t(std::min<std::uint32_t>(h + round, 0x7BFF));
}

namespace detail {
constexpr int weights[16] = {0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64};

// 10-bit endpoint to the 16-bit interpolation domain, as the decoder does.
inline int unquantize(int q) {
    if (q == 0) return 0;
    if (q == 1023) return 0xFFFF;
    return ((q << 16) + 0x8000) >> 10;
}
// Half bits h decode from interpolated value u as (u * 31) >> 6.
inline int quantize(int half) {
    const int u = (half * 64 + 30) / 31;
    if (u <= 0) return 0;
    if (u >= 0xFFFF - 16) return 1023;
    return std::clamp((u - 32 + 32) / 64, 1, 1022);
}

struct Bits {
    std::array<std::uint8_t, 16> data{};
    int position = 0;
    void put(std::uint32_t value, int count) {
        for (int i = 0; i < count; ++i, ++position)
            if ((value >> i) & 1) data[position >> 3] |= std::uint8_t(1u << (position & 7));
    }
};
}  // namespace detail

// Encodes 16 linear RGB pixels (row-major 4x4) as one 16-byte block.
inline std::array<std::uint8_t, 16> encodeBlock(const float (&pixels)[16][3]) {
    using namespace detail;
    int h[16][3], lo[3] = {0x7FFF, 0x7FFF, 0x7FFF}, hi[3] = {0, 0, 0};
    for (int p = 0; p < 16; ++p)
        for (int c = 0; c < 3; ++c) {
            h[p][c] = halfBits(pixels[p][c]);
            lo[c] = std::min(lo[c], h[p][c]);
            hi[c] = std::max(hi[c], h[p][c]);
        }
    // Try each diagonal of the channel bounding box; keep the one with least error.
    long long bestError = -1;
    int bestQ[2][3] = {}, bestIndex[16] = {};
    for (int diagonal = 0; diagonal < 4; ++diagonal) {
        int q[2][3], e[2][3];
        for (int c = 0; c < 3; ++c) {
            const bool flip = (c == 1 && (diagonal & 1)) || (c == 2 && (diagonal & 2));
            q[0][c] = quantize(flip ? hi[c] : lo[c]);
            q[1][c] = quantize(flip ? lo[c] : hi[c]);
            e[0][c] = unquantize(q[0][c]);
            e[1][c] = unquantize(q[1][c]);
        }
        long long error = 0;
        int index[16];
        for (int p = 0; p < 16; ++p) {
            long long best = -1;
            for (int i = 0; i < 16; ++i) {
                long long d = 0;
                for (int c = 0; c < 3; ++c) {
                    const int value = ((((64 - weights[i]) * e[0][c] + weights[i] * e[1][c] + 32) >> 6) * 31) >> 6;
                    d += (long long)(value - h[p][c]) * (value - h[p][c]);
                }
                if (best < 0 || d < best) { best = d; index[p] = i; }
            }
            error += best;
        }
        if (bestError < 0 || error < bestError) {
            bestError = error;
            std::memcpy(bestQ, q, sizeof(q));
            std::memcpy(bestIndex, index, sizeof(index));
        }
    }
    // The first pixel's index is stored without its top bit, so it must be below 8.
    if (bestIndex[0] >= 8) {
        for (int c = 0; c < 3; ++c) std::swap(bestQ[0][c], bestQ[1][c]);
        for (int &i : bestIndex) i = 15 - i;
    }
    Bits bits;
    bits.put(0x03, 5);  // mode 11
    for (int e = 0; e < 2; ++e)
        for (int c = 0; c < 3; ++c) bits.put(std::uint32_t(bestQ[e][c]), 10);
    bits.put(std::uint32_t(bestIndex[0]), 3);
    for (int p = 1; p < 16; ++p) bits.put(std::uint32_t(bestIndex[p]), 4);
    return bits.data;
}

}  // namespace Respawn::BC6H
