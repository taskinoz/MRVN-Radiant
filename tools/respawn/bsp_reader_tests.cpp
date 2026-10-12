// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/bsp_reader.h"
#include "../remap/source/respawn/lump_versions.h"
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}

template<class F> static void rejects(F function) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    require(rejected, "Expected malformed input to be rejected");
}

static void put(std::vector<unsigned char>& bytes, std::size_t offset, std::uint32_t value, bool big = false) {
    for (int i = 0; i < 4; ++i) bytes[offset + i] = static_cast<unsigned char>(value >> ((big ? 3 - i : i) * 8));
}

static std::vector<unsigned char> fixture(std::uint32_t version = 29, bool big = false) {
    std::vector<unsigned char> data(Respawn::HeaderSize + 4);
    const std::string magic = big ? "PSBr" : "rBSP";
    std::copy(magic.begin(), magic.end(), data.begin());
    put(data, 4, version, big); put(data, 8, 5, big); put(data, 12, 127, big);
    put(data, 16, Respawn::HeaderSize, big); put(data, 20, 4, big);
    const std::string payload = "base";
    std::copy(payload.begin(), payload.end(), data.begin() + Respawn::HeaderSize);
    return data;
}

static void write(const fs::path& path, const std::vector<unsigned char>& data) {
    std::ofstream output(path, std::ios::binary);
    output.write(reinterpret_cast<const char*>(data.data()), data.size());
    require(bool(output), "Cannot write test fixture");
}

static void selfTest(const fs::path& root) {
    const auto folder = root / std::to_string(std::chrono::high_resolution_clock::now().time_since_epoch().count());
    fs::create_directories(folder);
    require(Respawn::generatedLumpVersion(29, 0x36) == 1, "R1 world-light version");
    require(Respawn::generatedLumpVersion(37, 0x36) == 3, "R2 world-light version");
    require(Respawn::generatedLumpVersion(47, 0x36) == 0, "Apex world-light version");
    require(Respawn::generatedLumpVersion(29, 0x49) == 1, "R1 lit vertex version");
    require(Respawn::generatedLumpVersion(37, 0x53) == 1, "R2 lightmap header version");
    for (const auto version : {29u, 37u, 47u}) {
        auto bytes = fixture(version);
        const auto h = Respawn::parseHeader(bytes.data(), bytes.size());
        require(h.version == version && h.revision == 5 && h.lumps[0].length == 4, "Header fields");
    }
    auto bytes = fixture(37, true);
    require(Respawn::parseHeader(bytes.data(), bytes.size()).bigEndian, "Big endian header");
    require(Respawn::parseHeader(bytes.data(), bytes.size()).lumps[0].offset == Respawn::HeaderSize, "Big endian offset");
    rejects([&] { Respawn::parseHeader(bytes.data(), 10); });
    bytes[0] = '!'; rejects([&] { Respawn::parseHeader(bytes.data(), bytes.size()); });
    bytes = fixture(); put(bytes, 12, 128);
    rejects([&] { Respawn::parseHeader(bytes.data(), bytes.size()); });
    bytes = fixture(49 | (2u << 16));
    rejects([&] { Respawn::parseHeader(bytes.data(), bytes.size()); });
    const auto path = folder / "base.bsp";
    write(path, fixture());
    Respawn::BspReader reader(path.string());
    require(reader.readLump(0) == std::vector<char>({'b','a','s','e'}), "Embedded payload");
    require(reader.readLump(1).empty(), "Empty lump");
    rejects([&] { reader.readLump(128); });
    rejects([&] { reader.readLump(0, 3); });
    const auto overridePath = folder / "override.bsp";
    write(overridePath, fixture());
    write(Respawn::sidecarPath(overridePath.string(), 0), {'e','x','t'});
    write(Respawn::sidecarPath(overridePath.string(), 0, true), {'c','l','i'});
    Respawn::BspReader overridden(overridePath.string());
    require(overridden.readLump(0) == std::vector<char>({'e','x','t'}), "Default override");
    require(overridden.readLump(0, 10, true) == std::vector<char>({'c','l','i'}), "Client override");
    const auto upperPath = folder / "upper.bsp";
    write(upperPath, fixture());
    write(Respawn::sidecarPath(upperPath.string(), 42, false, true), {'u'});
    Respawn::BspReader upper(upperPath.string());
    require(upper.readLump(42) == std::vector<char>({'u'}), "Uppercase sidecar");
    const auto emptyPath = folder / "empty.bsp";
    write(emptyPath, fixture()); write(Respawn::sidecarPath(emptyPath.string(), 0), {});
    Respawn::BspReader empty(emptyPath.string());
    rejects([&] { empty.readLump(0); });
    const auto badPath = folder / "bad.bsp";
    bytes = fixture(); put(bytes, 16, 0xfffffffe);
    write(badPath, bytes);
    Respawn::BspReader bad(badPath.string()); rejects([&] { bad.readLump(0); });
    bytes = fixture(); put(bytes, 16, 10); write(folder / "header-range.bsp", bytes);
    Respawn::BspReader headerRange((folder / "header-range.bsp").string());
    rejects([&] { headerRange.readLump(0); });
    const auto streamedPath = folder / "streamed.bsp";
    bytes = fixture(49 | (1u << 16)); put(bytes, 16, 0x1000000);
    write(streamedPath, bytes);
    Respawn::BspReader streamed(streamedPath.string());
    rejects([&] { streamed.readLump(0); });
    write(Respawn::sidecarPath(streamedPath.string(), 0), {'s','t','r'});
    require(streamed.readLump(0) == std::vector<char>({'s','t','r'}), "Streamed virtual offset");
    for (const std::string header : {"ENTITIES01\n", "ENTITIES02 num_models=24\r\n"}) {
        std::vector<char> entities = {'{','}', '\0'};
        const std::string payload = header + "{\"classname\" \"info_player_start\"}\n";
        Respawn::appendEntityFile(entities, payload.data(), payload.size());
        require(entities.back() == '\0', "Entity terminator");
        require(std::count(entities.begin(), entities.end(), '\0') == 1, "No intermediate NUL");
        require(std::string(entities.data()).find("info_player_start") != std::string::npos, "Entity partition visible");
        require(std::string(entities.data()).find("num_models") == std::string::npos, "Header removed");
    }
    rejects([] { Respawn::entityPayloadOffset("bad\n", 4); });
    rejects([] { Respawn::entityPayloadOffset("ENTITIES01", 10); });
    rejects([] { const std::string longLine(4097, 'x'); Respawn::entityPayloadOffset(longLine.data(), longLine.size()); });
    std::cout << "Native BSP reader and entity tests passed\n";
}

int main(int argc, char** argv) {
    try {
        if (argc == 3 && std::string(argv[1]) == "--self-test") {
            selfTest(argv[2]);
            return 0;
        }
        if (argc < 2) throw std::runtime_error("Supply --self-test <folder> or BSP paths");
        for (int arg = 1; arg < argc; ++arg) {
            Respawn::BspReader reader(argv[arg]);
            std::uint64_t bytes = 0;
            std::size_t populated = 0;
            for (std::size_t i = 0; i < Respawn::LumpCount; ++i) {
                const auto data = reader.readLump(i);
                bytes += data.size();
                populated += !data.empty();
            }
            std::cout << argv[arg] << ": version " << reader.header().version
                      << ", " << populated << " populated lumps, " << bytes << " payload bytes\n";
        }
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
