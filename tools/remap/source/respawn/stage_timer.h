#pragma once

// Wall-clock time of one compile stage, printed to the log when it ends:
//      12.3 s  EmitCollisionGrid
// For finding where compile time goes (docs/respawn/RESPAWN_BUILD_PERFORMANCE.md).

#include <chrono>

#include "inout.h"

namespace Respawn {
struct StageTimer {
    const char *name;
    std::chrono::steady_clock::time_point start = std::chrono::steady_clock::now();
    explicit StageTimer(const char *stage) : name(stage) {}
    ~StageTimer() {
        const double seconds = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        Sys_Printf("%9.1f s  %s\n", seconds, name);
    }
    StageTimer(const StageTimer &) = delete;
    StageTimer &operator=(const StageTimer &) = delete;
};
}

#define REMAP_STAGE_CONCAT2(a, b) a##b
#define REMAP_STAGE_CONCAT(a, b) REMAP_STAGE_CONCAT2(a, b)
// Times the rest of the enclosing scope.
#define REMAP_STAGE(name) ::Respawn::StageTimer REMAP_STAGE_CONCAT(remapStage_, __LINE__)(name)
