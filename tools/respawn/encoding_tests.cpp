// Copyright (C) 2026 MRVN-Radiant contributors. GPL-2.0-or-later.
#include "../remap/source/respawn/encoding.h"
#include <iostream>
#include <limits>

static void require(bool value, const char* message) {
    if (!value) throw std::runtime_error(message);
}
template<class F> static void rejects(F function) {
    bool rejected = false;
    try { function(); } catch (const std::exception&) { rejected = true; }
    require(rejected, "Expected invalid encoding input to be rejected");
}

int main() {
    try {
        const std::string names("compat\\bump_extra\0compat\\bump\0", 30);
        const std::vector<char> pool(names.begin(), names.end());
        require(!Respawn::textureNameEquals(pool, 0, "compat\\bump"), "Prefix alias rejected");
        require(Respawn::textureNameEquals(pool, 18, "compat\\bump"), "Later exact match found");
        require(!Respawn::textureNameEquals(pool, std::numeric_limits<std::size_t>::max(), "x"), "Offset bounded");
        require(!Respawn::textureNameEquals({'a'}, 0, "a"), "Terminator required");
        require(Respawn::textureName("textures/compat/bump") == "compat\\bump", "Texture prefix normalization");
        require(Respawn::textureName("noshader") == "noshader", "Unprefixed short name preserved");
        rejects([] { Respawn::textureName("textures/"); });
        rejects([] { Respawn::textureName(std::string("x\0y", 3)); });
        const auto integer = Respawn::quantizeBoundsAxis(-64, 64);
        require(integer.origin == 0 && integer.extent == 66, "Existing integer collision margin preserved");
        for (int a = -64; a < 64; ++a) {
            for (int width = 0; width < 32; ++width) {
                const double minimum = a * 0.125;
                const double maximum = minimum + width * 0.125;
                const auto encoded = Respawn::quantizeBoundsAxis(minimum, maximum);
                require(encoded.origin - encoded.extent <= minimum - 2 &&
                        encoded.origin + encoded.extent >= maximum + 2,
                        "Fractional bounds contain both sides and their margin");
            }
        }
        rejects([] { Respawn::quantizeBoundsAxis(32767.5, 32768.5); });
        rejects([] { Respawn::quantizeBoundsAxis(-32768, 32767); });
        rejects([] { Respawn::quantizeBoundsAxis(1, -1); });
        rejects([] { Respawn::quantizeBoundsAxis(std::numeric_limits<double>::quiet_NaN(), 1); });
        rejects([] { Respawn::quantizeBoundsAxis(0, std::numeric_limits<double>::infinity()); });
        std::cout << "Texture identity and conservative collision encoding tests passed\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
