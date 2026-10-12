/* Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
 * Original bounded rBSP reader. Research attribution: docs/RESPAWN_SOURCES.md.
 * Payloads are opaque; this reader does not establish game schema compatibility.
 */
#pragma once

#include <array>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace Respawn {
constexpr std::size_t LumpCount = 128;
constexpr std::size_t HeaderSize = 16 + LumpCount * 16;

struct Lump {
    std::uint32_t offset, length, version, fourCC;
};

struct Header {
    std::uint32_t version, revision;
    bool bigEndian;
    std::array<Lump, LumpCount> lumps;

    bool streamed() const { return (version & 0xffff) >= 49 && (version >> 16) == 1; }
};

inline std::uint32_t readU32(const unsigned char* p, bool bigEndian) {
    std::uint32_t value = 0;
    for (int i = 0; i < 4; ++i)
        value |= std::uint32_t(p[i]) << ((bigEndian ? 3 - i : i) * 8);
    return value;
}

inline Header parseHeader(const unsigned char* bytes, std::size_t size) {
    if (size < HeaderSize)
        throw std::runtime_error("Truncated rBSP header");
    const std::string magic(reinterpret_cast<const char*>(bytes), 4);
    if (magic != "rBSP" && magic != "PSBr")
        throw std::runtime_error("Invalid rBSP magic");
    Header header{};
    header.bigEndian = magic == "PSBr";
    header.version = readU32(bytes + 4, header.bigEndian);
    header.revision = readU32(bytes + 8, header.bigEndian);
    if (readU32(bytes + 12, header.bigEndian) != 127)
        throw std::runtime_error("Unsupported rBSP maximum lump index");
    if ((header.version >> 16) != 0 && !header.streamed())
        throw std::runtime_error("Unsupported rBSP version flags");
    for (std::size_t i = 0; i < LumpCount; ++i) {
        auto p = bytes + 16 + i * 16;
        header.lumps[i] = {readU32(p, header.bigEndian), readU32(p + 4, header.bigEndian),
                          readU32(p + 8, header.bigEndian), readU32(p + 12, header.bigEndian)};
    }
    return header;
}

inline std::uint64_t fileSize(std::ifstream& stream) {
    stream.seekg(0, std::ios::end);
    const auto size = stream.tellg();
    if (size < 0)
        throw std::runtime_error("Cannot determine BSP file size");
    stream.seekg(0);
    return static_cast<std::uint64_t>(size);
}

inline std::string sidecarPath(const std::string& path, std::size_t index,
                               bool client = false, bool uppercase = false) {
    if (index >= LumpCount)
        throw std::out_of_range("Invalid lump index");
    std::ostringstream name;
    name << path << '.';
    if (uppercase) name << std::uppercase;
    name << std::hex << std::setfill('0') << std::setw(4) << index << ".bsp_lump";
    if (client) name << ".client";
    return name.str();
}

class BspReader {
    std::string m_path;
    std::ifstream m_stream;
    std::uint64_t m_size;
    Header m_header;

    static std::vector<char> readBytes(std::ifstream& stream, std::uint64_t offset,
                                      std::uint64_t length, std::size_t limit) {
        if (length > limit || length > std::uint64_t(std::numeric_limits<std::streamsize>::max()))
            throw std::runtime_error("Lump exceeds read limit");
        std::vector<char> data(static_cast<std::size_t>(length));
        if (length) {
            stream.clear();
            stream.seekg(static_cast<std::streamoff>(offset));
            if (!stream.read(data.data(), static_cast<std::streamsize>(length)))
                throw std::runtime_error("Truncated lump payload");
        }
        return data;
    }

public:
    explicit BspReader(const std::string& path) : m_path(path), m_stream(path, std::ios::binary) {
        if (!m_stream) throw std::runtime_error("Cannot open BSP: " + path);
        m_size = fileSize(m_stream);
        std::array<unsigned char, HeaderSize> bytes{};
        if (!m_stream.read(reinterpret_cast<char*>(bytes.data()), bytes.size()))
            throw std::runtime_error("Truncated rBSP header");
        m_header = parseHeader(bytes.data(), bytes.size());
    }

    const Header& header() const { return m_header; }
    std::uint64_t size() const { return m_size; }

    // Default sidecars override embedded lumps. Client callers explicitly opt in
    // to .client overrides; numeric directory offsets do not address sidecars.
    std::vector<char> readLump(std::size_t index, std::size_t limit = 256 * 1024 * 1024,
                               bool client = false) {
        if (index >= LumpCount) throw std::out_of_range("Invalid lump index");
        for (bool variant : {true, false}) {
            if (variant && !client) continue;
            for (bool uppercase : {false, true}) {
                std::ifstream extra(sidecarPath(m_path, index, variant, uppercase), std::ios::binary);
                if (extra) {
                    const auto length = fileSize(extra);
                    if (!length) throw std::runtime_error("Empty external lump");
                    return readBytes(extra, 0, length, limit);
                }
            }
        }
        const auto& lump = m_header.lumps[index];
        if (!lump.length) return {};
        if (m_header.streamed()) throw std::runtime_error("Missing streamed lump");
        if (lump.offset < HeaderSize || std::uint64_t(lump.offset) + lump.length > m_size)
            throw std::runtime_error("Lump range outside BSP payload");
        return readBytes(m_stream, lump.offset, lump.length, limit);
    }
};

inline std::size_t entityPayloadOffset(const char* data, std::size_t size) {
    std::size_t end = 0;
    while (end < size && end < 4096 && data[end] != '\n') ++end;
    if (end == size || end == 4096)
        throw std::runtime_error("Missing or oversized entity file header");
    std::string header(data, end);
    if (!header.empty() && header.back() == '\r') header.pop_back();
    if (header != "ENTITIES01" && header != "ENTITIES02" && header.compare(0, 11, "ENTITIES02 ") != 0)
        throw std::runtime_error("Unsupported entity file header");
    return end + 1;
}

inline void appendEntityFile(std::vector<char>& entities, const char* data, std::size_t size) {
    const auto offset = entityPayloadOffset(data, size);
    // Embedded and sidecar entity streams each carry terminators. Keeping an
    // intermediate NUL would hide every partition after the first from parsers.
    while (!entities.empty() && entities.back() == '\0') entities.pop_back();
    while (size > offset && data[size - 1] == '\0') --size;
    if (!entities.empty() && entities.back() != '\n') entities.push_back('\n');
    entities.insert(entities.end(), data + offset, data + size);
    entities.push_back('\0');
}
} // namespace Respawn
