/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Original Titanfall 2 lightmap baker. Plane encodings and light records were
 * measured from retail Coliseum/Glitch samples; see docs/RESPAWN_LIGHTING.md.
 *
 * Per page the engine reads:
 *   SKY  A  RGBM: rgb/255 * (a/255 * 3.984375 + 0.015625)
 *   SKY  B  direction: rgb/127 - 1, alpha 255
 *   RTL  A  four 6-bit slots into an RTL page (63 = unused), page in the top byte;
 *           texels without realtime lights hold 0xffffffff
 *   RTL  B  per-slot visibility (shadow mask), channel N for slot N
 *   RTL  C  half-resolution plane, embedded payloads only (written as zero)
 * RTL pages are 63 int16 hardware-light indices. Hardware indices count world
 * lights excluding ambient (type 5) records.
 */
#pragma once

#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <exception>
#include <functional>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace Respawn::Bake {

struct V3 {
    double x = 0, y = 0, z = 0;
};
inline V3 operator+(V3 a, V3 b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
inline V3 operator-(V3 a, V3 b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
inline V3 operator*(V3 a, double s) { return {a.x * s, a.y * s, a.z * s}; }
inline V3 operator-(V3 a) { return {-a.x, -a.y, -a.z}; }
inline double dot(V3 a, V3 b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
inline V3 cross(V3 a, V3 b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
inline double length(V3 a) { return std::sqrt(dot(a, a)); }
inline V3 normalize(V3 a) {
    const double l = length(a);
    return l > 0 ? a * (1.0 / l) : V3{0, 0, 1};
}
inline double luminance(V3 c) { return 0.2126 * c.x + 0.7152 * c.y + 0.0722 * c.z; }
inline V3 vmin(V3 a, V3 b) { return {std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z)}; }
inline V3 vmax(V3 a, V3 b) { return {std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z)}; }

/* ---------------------------------------------------------------------------
   Encodings
--------------------------------------------------------------------------- */
inline double rgbmMultiplier(std::uint8_t alpha) { return alpha / 255.0 * 3.984375 + 0.015625; }

inline std::array<std::uint8_t, 4> encodeRGBM(V3 colour) {
    const double r = std::max(0.0, colour.x), g = std::max(0.0, colour.y), b = std::max(0.0, colour.z);
    const double peak = std::max({r, g, b});
    if (!(peak > 0)) return {0, 0, 0, 0};
    // Smallest multiplier that holds the peak keeps the most RGB precision.
    const double wanted = std::ceil((peak - 0.015625) / 3.984375 * 255.0);
    const auto alpha = static_cast<std::uint8_t>(std::clamp(wanted, 0.0, 255.0));
    const double scale = 255.0 / rgbmMultiplier(alpha);
    auto channel = [&](double v) {
        return static_cast<std::uint8_t>(std::clamp(std::round(v * scale), 0.0, 255.0));
    };
    return {channel(r), channel(g), channel(b), alpha};
}

inline V3 decodeRGBM(const std::array<std::uint8_t, 4>& p) {
    const double m = rgbmMultiplier(p[3]) / 255.0;
    return {p[0] * m, p[1] * m, p[2] * m};
}

inline std::array<std::uint8_t, 4> encodeDirection(V3 d) {
    auto channel = [](double v) {
        return static_cast<std::uint8_t>(std::clamp(std::round((std::clamp(v, -1.0, 1.0) + 1.0) * 127.0), 0.0, 255.0));
    };
    return {channel(d.x), channel(d.y), channel(d.z), 255};
}

inline V3 decodeDirection(const std::array<std::uint8_t, 4>& p) {
    return {p[0] / 255.0 * 2.007874 - 1, p[1] / 255.0 * 2.007874 - 1, p[2] / 255.0 * 2.007874 - 1};
}

constexpr std::uint32_t RtlUnusedTexel = 0xffffffffu;
constexpr std::uint8_t RtlUnusedSlot = 63;
constexpr std::size_t RtlPageSize = 63;

inline std::uint32_t packRtlWord(const std::array<std::uint8_t, 4>& slots, std::uint8_t page) {
    std::uint32_t word = std::uint32_t(page) << 24;
    for (int i = 0; i < 4; ++i) {
        if (slots[i] > 63) throw std::invalid_argument("RTL slot exceeds 6 bits");
        word |= std::uint32_t(slots[i]) << (6 * i);
    }
    return word;
}

/* ---------------------------------------------------------------------------
   Lights
--------------------------------------------------------------------------- */
// Retail falloff is a quadratic through (0,1), (fifty,0.5) and (zero,0).
struct Attenuation { double constant = 1, linear = 0, quadratic = 0; };

inline Attenuation fitAttenuation(double zero, double fifty) {
    if (!(zero > 0) || !(fifty > 0) || !(fifty < zero) || !std::isfinite(zero))
        throw std::invalid_argument("Light falloff needs 0 < fifty-percent < zero-percent distance");
    const double det = zero * fifty * (fifty - zero);
    return {1.0, (0.5 * zero * zero - fifty * fifty) / det, (fifty - 0.5 * zero) / det};
}

enum class LightType : int { Point = 1, Spot = 2, Sun = 3, Ambient = 5 };

struct Light {
    LightType type = LightType::Point;
    V3 origin;
    V3 direction{0, 0, -1};  // direction light travels (spot and sun)
    V3 intensity;            // linear RGB
    double zeroDistance = 0;
    Attenuation attenuation;
    double cosInner = 1, cosOuter = 0;  // spot cone
    bool realtime = true;   // RTL slot with a baked shadow mask; otherwise baked into SKY A
    int hardwareIndex = -1; // index among non-ambient world lights
};

inline double falloff(const Light& light, double distance) {
    if (light.type == LightType::Sun) return 1.0;
    if (distance >= light.zeroDistance) return 0.0;
    const auto& a = light.attenuation;
    return std::clamp(a.constant + a.linear * distance + a.quadratic * distance * distance, 0.0, 1.0);
}

inline double spotFactor(const Light& light, V3 toSurface) {
    if (light.type != LightType::Spot) return 1.0;
    const double c = dot(light.direction, toSurface);
    if (c <= light.cosOuter) return 0.0;
    if (c >= light.cosInner || light.cosInner <= light.cosOuter) return 1.0;
    return (c - light.cosOuter) / (light.cosInner - light.cosOuter);
}

/* ---------------------------------------------------------------------------
   Occluders: convex brushes in a bounding-volume hierarchy
--------------------------------------------------------------------------- */
struct Brush {
    std::vector<std::array<double, 4>> planes;  // outward normal xyz, distance: inside when n.p <= d
    V3 mins, maxs;
};

class Occluders {
    struct Node { V3 mins, maxs; int left = -1, right = -1, first = 0, count = 0; };
    std::vector<Brush> m_brushes;
    std::vector<int> m_order;
    std::vector<Node> m_nodes;

    int build(int first, int count) {
        Node node;
        node.mins = {1e300, 1e300, 1e300};
        node.maxs = {-1e300, -1e300, -1e300};
        for (int i = first; i < first + count; ++i) {
            node.mins = vmin(node.mins, m_brushes[m_order[i]].mins);
            node.maxs = vmax(node.maxs, m_brushes[m_order[i]].maxs);
        }
        const int index = static_cast<int>(m_nodes.size());
        m_nodes.push_back(node);
        if (count <= 4) {
            m_nodes[index].first = first;
            m_nodes[index].count = count;
            return index;
        }
        const V3 size = node.maxs - node.mins;
        const int axis = size.x >= size.y && size.x >= size.z ? 0 : (size.y >= size.z ? 1 : 2);
        auto centre = [&](int b) {
            const V3 c = (m_brushes[b].mins + m_brushes[b].maxs) * 0.5;
            return axis == 0 ? c.x : (axis == 1 ? c.y : c.z);
        };
        const int middle = first + count / 2;
        std::nth_element(m_order.begin() + first, m_order.begin() + middle, m_order.begin() + first + count,
                         [&](int a, int b) { return centre(a) < centre(b); });
        const int left = build(first, middle - first);
        const int right = build(middle, first + count - middle);
        m_nodes[index].left = left;
        m_nodes[index].right = right;
        return index;
    }

    static bool segmentHitsBox(V3 a, V3 d, V3 mins, V3 maxs) {
        double t0 = 0, t1 = 1;
        const double o[3] = {a.x, a.y, a.z}, dir[3] = {d.x, d.y, d.z};
        const double lo[3] = {mins.x, mins.y, mins.z}, hi[3] = {maxs.x, maxs.y, maxs.z};
        for (int i = 0; i < 3; ++i) {
            if (std::abs(dir[i]) < 1e-12) {
                if (o[i] < lo[i] || o[i] > hi[i]) return false;
                continue;
            }
            double ta = (lo[i] - o[i]) / dir[i], tb = (hi[i] - o[i]) / dir[i];
            if (ta > tb) std::swap(ta, tb);
            t0 = std::max(t0, ta);
            t1 = std::min(t1, tb);
            if (t0 > t1) return false;
        }
        return true;
    }

    static bool segmentHitsBrush(V3 a, V3 b, const Brush& brush) {
        double enter = 0, exit = 1;
        for (const auto& p : brush.planes) {
            const V3 n{p[0], p[1], p[2]};
            const double da = dot(n, a) - p[3], db = dot(n, b) - p[3];
            // Points on a face count as outside, so rays along a face are open.
            constexpr double eps = 1e-6;
            if (da > -eps && db > -eps) return false;
            if (da <= -eps && db <= -eps) continue;
            const double t = da / (da - db);
            if (da > -eps) enter = std::max(enter, t);
            else exit = std::min(exit, t);
            if (enter >= exit) return false;
        }
        // Require a measurable overlap so rays grazing a face are not blocked.
        return (exit - enter) * length(b - a) > 1e-3;
    }

public:
    explicit Occluders(std::vector<Brush> brushes = {}) : m_brushes(std::move(brushes)) {
        m_order.resize(m_brushes.size());
        for (std::size_t i = 0; i < m_order.size(); ++i) m_order[i] = static_cast<int>(i);
        if (!m_brushes.empty()) build(0, static_cast<int>(m_brushes.size()));
    }

    std::size_t size() const { return m_brushes.size(); }
    bool empty() const { return m_brushes.empty(); }
    V3 mins() const { return m_nodes.empty() ? V3{} : m_nodes[0].mins; }
    V3 maxs() const { return m_nodes.empty() ? V3{} : m_nodes[0].maxs; }

    bool blocked(V3 a, V3 b) const {
        if (m_nodes.empty()) return false;
        const V3 d = b - a;
        int stack[128];
        int top = 0;
        stack[top++] = 0;
        while (top) {
            const Node& node = m_nodes[stack[--top]];
            if (!segmentHitsBox(a, d, node.mins, node.maxs)) continue;
            if (node.left < 0) {
                for (int i = node.first; i < node.first + node.count; ++i)
                    if (segmentHitsBrush(a, b, m_brushes[m_order[i]])) return true;
            } else if (top + 2 <= 128) {
                stack[top++] = node.left;
                stack[top++] = node.right;
            } else {
                throw std::runtime_error("Occluder hierarchy is too deep");
            }
        }
        return false;
    }
};

/* ---------------------------------------------------------------------------
   Charts and bake
--------------------------------------------------------------------------- */
struct Chart {
    std::uint32_t page = 0;
    std::vector<V3> positions, normals;
    std::vector<std::array<double, 2>> luxels;  // texel-space coordinates within the page
    std::vector<std::uint32_t> triangles;
};

struct PageSize { std::uint32_t width, height; };

struct Options {
    int ambientSamples = 16;       // cosine-weighted sky visibility rays per texel
    bool ambientOcclusion = true;  // false: treat the sky as fully visible
    double ambientScale = 0.05;    // SKY A = ambient * visibility * scale (needs engine calibration)
    double luxelSize = 16.0;       // world units per texel, for sub-texel shadow samples
    double rayOffset = 0.5;        // start rays off the surface along its normal
    unsigned threads = 0;          // 0: hardware concurrency
};

struct Result {
    std::vector<std::uint8_t> sky;   // per page: A then B
    std::vector<std::uint8_t> rtl;   // per page: A, B, then C
    std::vector<std::array<std::int16_t, RtlPageSize>> rtlPages;
    std::size_t chartedTexels = 0, realtimeTexels = 0;
};

namespace detail {
struct Sample {
    float px = 0, py = 0, pz = 0, nx = 0, ny = 0, nz = 0;
    float inside = -1e30f;
    std::int32_t chart = -1;
};


inline void parallelFor(std::size_t count, unsigned threads, const std::function<void(std::size_t)>& body) {
    if (!threads) threads = std::max(1u, std::thread::hardware_concurrency());
    threads = static_cast<unsigned>(std::min<std::size_t>(threads, std::max<std::size_t>(count, 1)));
    std::atomic<std::size_t> next{0};
    std::vector<std::thread> pool;
    std::exception_ptr failure;
    std::atomic<bool> failed{false};
    auto worker = [&] {
        try {
            for (std::size_t i; !failed && (i = next.fetch_add(1)) < count;) body(i);
        } catch (...) {
            if (!failed.exchange(true)) failure = std::current_exception();
        }
    };
    for (unsigned t = 1; t < threads; ++t) pool.emplace_back(worker);
    worker();
    for (auto& thread : pool) thread.join();
    if (failure) std::rethrow_exception(failure);
}

inline std::uint32_t hash(std::uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352d; x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16;
    return x;
}

inline void basis(V3 n, V3& t, V3& b) {
    t = normalize(std::abs(n.z) < 0.9 ? cross(n, {0, 0, 1}) : cross(n, {1, 0, 0}));
    b = cross(n, t);
}
}  // namespace detail

/*
    Rasterize charts into per-page texel samples. Texels up to one texel outside a
    triangle are kept (with clamped barycentrics) so bilinear filtering at chart
    edges reads lit values; the packer's gutter keeps charts apart.
*/
inline std::vector<std::vector<detail::Sample>> rasterize(const std::vector<Chart>& charts,
                                                          const std::vector<PageSize>& pages) {
    std::vector<std::vector<detail::Sample>> samples(pages.size());
    for (std::size_t p = 0; p < pages.size(); ++p) {
        if (!pages[p].width || !pages[p].height || pages[p].width % 2 || pages[p].height % 2)
            throw std::invalid_argument("Lightmap pages need nonzero even dimensions");
        samples[p].resize(std::size_t(pages[p].width) * pages[p].height);
    }
    for (std::size_t c = 0; c < charts.size(); ++c) {
        const Chart& chart = charts[c];
        if (chart.page >= pages.size()) throw std::out_of_range("Chart references a missing lightmap page");
        if (chart.positions.size() != chart.normals.size() || chart.positions.size() != chart.luxels.size() ||
            chart.triangles.size() % 3)
            throw std::invalid_argument("Malformed lightmap chart");
        const auto& page = pages[chart.page];
        auto& out = samples[chart.page];
        for (std::size_t t = 0; t < chart.triangles.size(); t += 3) {
            const std::uint32_t i0 = chart.triangles[t], i1 = chart.triangles[t + 1], i2 = chart.triangles[t + 2];
            if (std::max({i0, i1, i2}) >= chart.positions.size()) throw std::out_of_range("Chart index out of range");
            const auto &a = chart.luxels[i0], &b = chart.luxels[i1], &d = chart.luxels[i2];
            const double area2 = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0]);
            if (std::abs(area2) < 1e-9) continue;
            // Edge lengths opposite each vertex, to express barycentrics as texel distances.
            const double e0 = std::hypot(d[0] - b[0], d[1] - b[1]);
            const double e1 = std::hypot(d[0] - a[0], d[1] - a[1]);
            const double e2 = std::hypot(b[0] - a[0], b[1] - a[1]);
            const double h0 = std::abs(area2) / std::max(e0, 1e-9);
            const double h1 = std::abs(area2) / std::max(e1, 1e-9);
            const double h2 = std::abs(area2) / std::max(e2, 1e-9);
            const int x0 = std::max(0, int(std::floor(std::min({a[0], b[0], d[0]}) - 1.5)));
            const int y0 = std::max(0, int(std::floor(std::min({a[1], b[1], d[1]}) - 1.5)));
            const int x1 = std::min(int(page.width) - 1, int(std::ceil(std::max({a[0], b[0], d[0]}) + 1.5)));
            const int y1 = std::min(int(page.height) - 1, int(std::ceil(std::max({a[1], b[1], d[1]}) + 1.5)));
            for (int y = y0; y <= y1; ++y) {
                for (int x = x0; x <= x1; ++x) {
                    const double px = x + 0.5, py = y + 0.5;
                    double w1 = ((px - a[0]) * (d[1] - a[1]) - (py - a[1]) * (d[0] - a[0])) / area2;
                    double w2 = ((b[0] - a[0]) * (py - a[1]) - (b[1] - a[1]) * (px - a[0])) / area2;
                    double w0 = 1 - w1 - w2;
                    const double inside = std::min({w0 * h0, w1 * h1, w2 * h2});
                    if (inside < -1.0) continue;
                    auto& s = out[std::size_t(y) * page.width + x];
                    if (inside <= s.inside) continue;
                    w0 = std::max(0.0, w0); w1 = std::max(0.0, w1); w2 = std::max(0.0, w2);
                    const double sum = w0 + w1 + w2;
                    w0 /= sum; w1 /= sum; w2 /= sum;
                    const V3 pos = chart.positions[i0] * w0 + chart.positions[i1] * w1 + chart.positions[i2] * w2;
                    const V3 nrm = normalize(chart.normals[i0] * w0 + chart.normals[i1] * w1 + chart.normals[i2] * w2);
                    s = {float(pos.x), float(pos.y), float(pos.z), float(nrm.x), float(nrm.y), float(nrm.z),
                         float(inside), std::int32_t(c)};
                }
            }
        }
    }
    return samples;
}

/*
    Bake every page. `ambient` is the sky ambient colour (first light_environment);
    point/spot lights with realtime=false and the ambient go into SKY A; suns and
    realtime point/spot lights receive RTL slots and baked shadow masks.
*/
inline Result bake(const std::vector<Chart>& charts, const std::vector<PageSize>& pages,
                   const std::vector<Light>& lights, V3 ambient, const Occluders& occluders,
                   const Options& options = {}) {
    for (const auto& light : lights)
        if (light.realtime && light.type != LightType::Ambient && light.hardwareIndex < 0)
            throw std::invalid_argument("Realtime light without a hardware index");
    const auto samples = rasterize(charts, pages);

    // Scene extent for sky and sun rays.
    V3 lo = occluders.empty() ? V3{1e300, 1e300, 1e300} : occluders.mins();
    V3 hi = occluders.empty() ? V3{-1e300, -1e300, -1e300} : occluders.maxs();
    for (const auto& chart : charts)
        for (const auto& p : chart.positions) { lo = vmin(lo, p); hi = vmax(hi, p); }
    const double far = charts.empty() ? 1.0 : length(hi - lo) * 2 + 1024;

    // Shadow-mask visibility from four sub-texel samples, 0..255.
    auto visibility = [&](const detail::Sample& s, const Light& light) {
        const V3 n{s.nx, s.ny, s.nz};
        const V3 start = V3{s.px, s.py, s.pz} + n * options.rayOffset;
        V3 t, b;
        detail::basis(n, t, b);
        const double offsets[4][2] = {{-0.25, -0.25}, {0.25, -0.25}, {-0.25, 0.25}, {0.25, 0.25}};
        int open = 0;
        for (const auto& o : offsets) {
            const V3 from = start + t * (o[0] * options.luxelSize) + b * (o[1] * options.luxelSize);
            const V3 to = light.type == LightType::Sun ? from - light.direction * far : light.origin;
            if (!occluders.blocked(from, to)) ++open;
        }
        return static_cast<std::uint8_t>(open * 255 / 4);
    };

    // Pass 1: choose up to four realtime lights per texel by unshadowed
    // contribution times visibility, so lights behind walls don't take slots.
    struct Slots {
        std::array<std::int16_t, 4> light{-1, -1, -1, -1};
        std::array<float, 4> score{};
        std::array<std::uint8_t, 4> visible{};
    };
    std::vector<std::vector<Slots>> slots(pages.size());
    for (std::size_t p = 0; p < pages.size(); ++p) slots[p].resize(samples[p].size());
    for (std::size_t p = 0; p < pages.size(); ++p) {
        detail::parallelFor(pages[p].height, options.threads, [&](std::size_t y) {
            for (std::size_t x = 0; x < pages[p].width; ++x) {
                const std::size_t i = y * pages[p].width + x;
                const auto& s = samples[p][i];
                if (s.chart < 0) continue;
                const V3 pos{s.px, s.py, s.pz}, n{s.nx, s.ny, s.nz};
                Slots& out = slots[p][i];
                for (std::size_t l = 0; l < lights.size(); ++l) {
                    const Light& light = lights[l];
                    if (!light.realtime || light.type == LightType::Ambient) continue;
                    double score;
                    if (light.type == LightType::Sun) {
                        // Suns outrank local lights so their shadow mask is always kept.
                        score = dot(n, -light.direction) > 0 ? 1e9 + luminance(light.intensity) : 0;
                    } else {
                        const V3 toLight = light.origin - pos;
                        const double d = length(toLight);
                        if (d >= light.zeroDistance || d <= 0) continue;
                        const V3 l3 = toLight * (1.0 / d);
                        score = luminance(light.intensity) * falloff(light, d) * std::max(0.0, dot(n, l3)) *
                                spotFactor(light, -l3);
                    }
                    if (!(score > 0)) continue;
                    if (out.light[3] >= 0 && score <= out.score[3]) continue;  // cannot make the top four
                    const std::uint8_t visible = visibility(s, light);
                    // Retail keeps the sun slot where it is fully shadowed; local
                    // lights that cannot reach the texel give up their slot.
                    if (light.type != LightType::Sun) {
                        if (!visible) continue;
                        score *= visible / 255.0;
                    }
                    // Insert into the sorted top four.
                    for (int k = 0; k < 4; ++k) {
                        if (out.light[k] < 0 || score > out.score[k]) {
                            for (int m = 3; m > k; --m) {
                                out.light[m] = out.light[m - 1];
                                out.score[m] = out.score[m - 1];
                                out.visible[m] = out.visible[m - 1];
                            }
                            out.light[k] = static_cast<std::int16_t>(l);
                            out.score[k] = static_cast<float>(score);
                            out.visible[k] = visible;
                            break;
                        }
                    }
                }
            }
        });
    }

    // Assign one RTL page per chart; pages hold at most 63 hardware lights.
    std::vector<std::unordered_map<int, double>> chartLights(charts.size());
    for (std::size_t p = 0; p < pages.size(); ++p)
        for (std::size_t i = 0; i < samples[p].size(); ++i)
            if (samples[p][i].chart >= 0)
                for (int k = 0; k < 4; ++k)
                    if (slots[p][i].light[k] >= 0)
                        chartLights[samples[p][i].chart][slots[p][i].light[k]] += slots[p][i].score[k];

    Result result;
    std::vector<std::vector<int>> rtlPages;  // light indices per RTL page
    std::vector<int> chartPage(charts.size(), -1);
    std::vector<std::unordered_map<int, int>> chartSlot(charts.size());  // light -> slot within its page
    for (std::size_t c = 0; c < charts.size(); ++c) {
        if (chartLights[c].empty()) continue;
        std::vector<std::pair<int, double>> wanted(chartLights[c].begin(), chartLights[c].end());
        std::sort(wanted.begin(), wanted.end(), [](auto& a, auto& b) { return a.second > b.second; });
        if (wanted.size() > RtlPageSize) wanted.resize(RtlPageSize);
        int chosen = -1;
        for (std::size_t r = 0; r < rtlPages.size() && chosen < 0; ++r) {
            std::size_t missing = 0;
            for (auto& [light, score] : wanted)
                if (std::find(rtlPages[r].begin(), rtlPages[r].end(), light) == rtlPages[r].end()) ++missing;
            if (rtlPages[r].size() + missing <= RtlPageSize) chosen = static_cast<int>(r);
        }
        if (chosen < 0) {
            if (rtlPages.size() >= 255) throw std::runtime_error("More than 255 RTL pages are required");
            chosen = static_cast<int>(rtlPages.size());
            rtlPages.emplace_back();
        }
        auto& page = rtlPages[chosen];
        for (auto& [light, score] : wanted)
            if (std::find(page.begin(), page.end(), light) == page.end()) page.push_back(light);
        chartPage[c] = chosen;
        for (std::size_t s = 0; s < page.size(); ++s) chartSlot[c][page[s]] = static_cast<int>(s);
    }
    if (rtlPages.empty()) rtlPages.emplace_back();
    for (const auto& page : rtlPages) {
        std::array<std::int16_t, RtlPageSize> entries{};
        for (std::size_t s = 0; s < page.size(); ++s)
            entries[s] = static_cast<std::int16_t>(lights[page[s]].hardwareIndex);
        result.rtlPages.push_back(entries);
    }

    // Lay out the output buffers.
    std::size_t skyBytes = 0, rtlBytes = 0;
    std::vector<std::size_t> skyOffset, rtlOffset;
    for (const auto& page : pages) {
        const std::size_t texels = std::size_t(page.width) * page.height;
        skyOffset.push_back(skyBytes);
        rtlOffset.push_back(rtlBytes);
        skyBytes += texels * 8;
        rtlBytes += texels * 8 + texels;  // A, B, then C at half width and height
    }
    result.sky.assign(skyBytes, 0);
    result.rtl.assign(rtlBytes, 0);

    // Pass 2: rays and encoding.
    const int ambientSamples = std::max(1, options.ambientSamples);
    std::atomic<std::size_t> charted{0}, realtime{0};
    for (std::size_t p = 0; p < pages.size(); ++p) {
        const std::size_t texels = std::size_t(pages[p].width) * pages[p].height;
        std::uint8_t* skyA = result.sky.data() + skyOffset[p];
        std::uint8_t* skyB = skyA + texels * 4;
        std::uint8_t* rtlA = result.rtl.data() + rtlOffset[p];
        std::uint8_t* rtlB = rtlA + texels * 4;
        detail::parallelFor(pages[p].height, options.threads, [&](std::size_t y) {
            for (std::size_t x = 0; x < pages[p].width; ++x) {
                const std::size_t i = y * pages[p].width + x;
                std::uint32_t word = RtlUnusedTexel;
                std::array<std::uint8_t, 4> masks{};
                const auto& s = samples[p][i];
                if (s.chart >= 0) {
                    charted.fetch_add(1, std::memory_order_relaxed);
                    const V3 pos{s.px, s.py, s.pz}, n{s.nx, s.ny, s.nz};
                    const V3 start = pos + n * options.rayOffset;
                    V3 t, b;
                    detail::basis(n, t, b);
                    V3 baked{}, direction{};
                    double directionWeight = 0;

                    // Sky ambient: cosine-weighted visibility of the sky.
                    if (luminance(ambient) > 0) {
                        double visible = ambientSamples;
                        V3 openDirection = n * double(ambientSamples);
                        if (options.ambientOcclusion) {
                            visible = 0;
                            openDirection = {};
                            const std::uint32_t seed = detail::hash(std::uint32_t(i * 2654435761u + p));
                            const double rotate = (seed & 0xffff) / 65536.0;
                            for (int k = 0; k < ambientSamples; ++k) {
                                const double u = (k + 0.5) / ambientSamples;
                                const double phi = 2 * 3.14159265358979323846 * std::fmod(k * 0.6180339887498949 + rotate, 1.0);
                                const double r = std::sqrt(u);
                                const V3 dir = t * (r * std::cos(phi)) + b * (r * std::sin(phi)) + n * std::sqrt(1 - u);
                                if (!occluders.blocked(start, start + dir * far)) {
                                    visible += 1;
                                    openDirection = openDirection + dir;
                                }
                            }
                        }
                        const double fraction = visible / ambientSamples;
                        baked = baked + ambient * (fraction * options.ambientScale);
                        const double w = luminance(ambient) * fraction * options.ambientScale;
                        if (visible > 0) {
                            direction = direction + normalize(openDirection) * w;
                            directionWeight += w;
                        }
                    }

                    // Static (non-realtime) local lights.
                    for (const Light& light : lights) {
                        if (light.realtime || (light.type != LightType::Point && light.type != LightType::Spot)) continue;
                        const V3 toLight = light.origin - pos;
                        const double d = length(toLight);
                        if (d >= light.zeroDistance || d <= 0) continue;
                        const V3 l3 = toLight * (1.0 / d);
                        const double lambert = dot(n, l3);
                        if (lambert <= 0) continue;
                        const double scale = falloff(light, d) * lambert * spotFactor(light, -l3);
                        if (!(scale > 0) || occluders.blocked(start, light.origin)) continue;
                        baked = baked + light.intensity * scale;
                        const double w = luminance(light.intensity) * scale;
                        direction = direction + l3 * w;
                        directionWeight += w;
                    }

                    auto a = encodeRGBM(baked);
                    std::memcpy(skyA + i * 4, a.data(), 4);
                    const V3 dir = directionWeight > 0 ? direction * (1.0 / directionWeight) : n;
                    auto bd = encodeDirection(dir);
                    std::memcpy(skyB + i * 4, bd.data(), 4);

                    // Realtime slots and their shadow masks.
                    const int page = chartPage[s.chart];
                    if (page >= 0) {
                        std::array<std::uint8_t, 4> slotIds{RtlUnusedSlot, RtlUnusedSlot, RtlUnusedSlot, RtlUnusedSlot};
                        int used = 0;
                        for (int k = 0; k < 4; ++k) {
                            const int l = slots[p][i].light[k];
                            if (l < 0) continue;
                            const auto found = chartSlot[s.chart].find(l);
                            if (found == chartSlot[s.chart].end()) continue;  // dropped by the 63-light page cap
                            slotIds[used] = static_cast<std::uint8_t>(found->second);
                            masks[used] = slots[p][i].visible[k];
                            ++used;
                        }
                        if (used) {
                            word = packRtlWord(slotIds, static_cast<std::uint8_t>(page));
                            realtime.fetch_add(1, std::memory_order_relaxed);
                        }
                    }
                }
                for (int k = 0; k < 4; ++k) rtlA[i * 4 + k] = static_cast<std::uint8_t>(word >> (8 * k));
                std::memcpy(rtlB + i * 4, masks.data(), 4);
            }
        });
    }
    result.chartedTexels = charted;
    result.realtimeTexels = realtime;
    return result;
}

}  // namespace Respawn::Bake
