/* -------------------------------------------------------------------------------

   Copyright (C) 2022-2025 MRVN-Radiant and contributors.
   For a list of contributors, see the accompanying CONTRIBUTORS file.

   This file is part of MRVN-Radiant.

   MRVN-Radiant is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.

   MRVN-Radiant is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.

   You should have received a copy of the GNU General Public License
   along with GtkRadiant; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

   ------------------------------------------------------------------------------- */

/*
    HIPRT Ray Tracing Implementation

    Uses AMD HIP RT + Orochi for GPU-accelerated BVH ray tracing.
    Orochi provides GPU abstraction over HIP/CUDA, so this works on
    both AMD and NVIDIA GPUs without requiring a HIP SDK installation.

    BVH is built on GPU via HIPRT host API.
    Ray traversal is done on the GPU via a kernel compiled at runtime
    using hiprtBuildTraceKernels (HIPRT links its BVH traversal routines
    into the user's kernel at JIT time).

    Falls back to disabled state if no GPU is available at runtime.
*/

#include "hiprt_trace.h"
#include "remap.h"
#include "bspfile_shared.h"

#ifdef USE_HIPRT
#include <Orochi/Orochi.h>
#include <hiprt/hiprt_libpath.h>
#define _ENABLE_HIPRTEW
#include <hiprt/hiprtew.h>
#include <chrono>
#include <cstring>
#include <string>
#include <algorithm>
#endif

namespace HIPRTTrace {

// =============================================================================
// Internal State
// =============================================================================

#ifdef USE_HIPRT

static oroDevice   g_oroDevice = 0;
static oroCtx      g_oroCtx = nullptr;
static hiprtContext g_context = nullptr;
static bool        g_sceneReady = false;
static SceneStats  g_stats = {};

// GPU geometry
static hiprtGeometry g_geom = nullptr;

// GPU device memory for geometry (must persist while geometry is alive)
static oroDeviceptr g_d_vertices = 0;
static oroDeviceptr g_d_indices = 0;

// GPU kernel functions
static oroFunction g_closestHitFunc = nullptr;
static oroFunction g_anyHitFunc = nullptr;

// GPU buffers for single-ray dispatch
static oroDeviceptr g_d_ray = 0;
static oroDeviceptr g_d_hit = 0;

// Batch kernel functions
static oroFunction g_closestHitBatchFunc = nullptr;
static oroFunction g_anyHitBatchFunc = nullptr;

// Batch GPU buffers (grow as needed)
static oroDeviceptr g_d_batchRays = 0;
static oroDeviceptr g_d_batchAnyResults = 0;
static oroDeviceptr g_d_batchHitResults = 0;
static size_t g_batchCapacity = 0;
static size_t g_batchHitCapacity = 0;

// Per-triangle metadata on host (maps global primID -> mesh index + local prim ID)
struct TriangleMeta {
    int meshIndex;
    int localPrimID;
};
static std::vector<TriangleMeta> g_triangleMeta;

// =============================================================================
// GPU Kernel Source
// =============================================================================
// This kernel source is compiled at runtime by hiprtBuildTraceKernels.
// HIPRT patches in its BVH traversal routines during compilation.

static const char* g_kernelSource = R"(
#include <hiprt/hiprt_device.h>

struct RayInput {
    float ox, oy, oz;
    float dx, dy, dz;
    float minT, maxT;
};

struct HitOutput {
    float t;
    float u, v;
    float nx, ny, nz;
    unsigned int primID;
};

extern "C" __global__ void ClosestHitKernel(
    hiprtGeometry geom,
    const RayInput* __restrict__ rayIn,
    HitOutput* __restrict__ hitOut)
{
    hiprtRay ray;
    ray.origin    = make_float3(rayIn->ox, rayIn->oy, rayIn->oz);
    ray.direction = make_float3(rayIn->dx, rayIn->dy, rayIn->dz);
    ray.minT      = rayIn->minT;
    ray.maxT      = rayIn->maxT;

    hiprtGeomTraversalClosest tr(geom, ray);
    hiprtHit hit = tr.getNextHit();

    if (hit.hasHit()) {
        hitOut->t      = hit.t;
        hitOut->u      = hit.uv.x;
        hitOut->v      = hit.uv.y;
        hitOut->nx     = hit.normal.x;
        hitOut->ny     = hit.normal.y;
        hitOut->nz     = hit.normal.z;
        hitOut->primID = hit.primID;
    } else {
        hitOut->primID = 0xFFFFFFFF;
        hitOut->t      = -1.0f;
    }
}

extern "C" __global__ void AnyHitKernel(
    hiprtGeometry geom,
    const RayInput* __restrict__ rayIn,
    HitOutput* __restrict__ hitOut)
{
    hiprtRay ray;
    ray.origin    = make_float3(rayIn->ox, rayIn->oy, rayIn->oz);
    ray.direction = make_float3(rayIn->dx, rayIn->dy, rayIn->dz);
    ray.minT      = rayIn->minT;
    ray.maxT      = rayIn->maxT;

    hiprtGeomTraversalAnyHit tr(geom, ray);
    hiprtHit hit = tr.getNextHit();

    if (hit.hasHit()) {
        hitOut->primID = hit.primID;
        hitOut->t      = hit.t;
    } else {
        hitOut->primID = 0xFFFFFFFF;
        hitOut->t      = -1.0f;
    }
}

extern "C" __global__ void ClosestHitKernelBatch(
    hiprtGeometry geom,
    const RayInput* __restrict__ raysIn,
    HitOutput* __restrict__ hitsOut,
    int numRays)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= numRays) return;

    hiprtRay ray;
    ray.origin    = make_float3(raysIn[idx].ox, raysIn[idx].oy, raysIn[idx].oz);
    ray.direction = make_float3(raysIn[idx].dx, raysIn[idx].dy, raysIn[idx].dz);
    ray.minT      = raysIn[idx].minT;
    ray.maxT      = raysIn[idx].maxT;

    hiprtGeomTraversalClosest tr(geom, ray);
    hiprtHit hit = tr.getNextHit();

    if (hit.hasHit()) {
        hitsOut[idx].t      = hit.t;
        hitsOut[idx].u      = hit.uv.x;
        hitsOut[idx].v      = hit.uv.y;
        hitsOut[idx].nx     = hit.normal.x;
        hitsOut[idx].ny     = hit.normal.y;
        hitsOut[idx].nz     = hit.normal.z;
        hitsOut[idx].primID = hit.primID;
    } else {
        hitsOut[idx].primID = 0xFFFFFFFF;
        hitsOut[idx].t      = -1.0f;
    }
}

extern "C" __global__ void AnyHitKernelBatch(
    hiprtGeometry geom,
    const RayInput* __restrict__ raysIn,
    unsigned int* __restrict__ hitsOut,
    int numRays)
{
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= numRays) return;

    hiprtRay ray;
    ray.origin    = make_float3(raysIn[idx].ox, raysIn[idx].oy, raysIn[idx].oz);
    ray.direction = make_float3(raysIn[idx].dx, raysIn[idx].dy, raysIn[idx].dz);
    ray.minT      = raysIn[idx].minT;
    ray.maxT      = raysIn[idx].maxT;

    hiprtGeomTraversalAnyHit tr(geom, ray);
    hiprtHit hit = tr.getNextHit();

    hitsOut[idx] = hit.hasHit() ? 1u : 0u;
}
)";

// Structures matching the kernel (must match layout exactly)
struct RayInput {
    float ox, oy, oz;
    float dx, dy, dz;
    float minT, maxT;
};

struct HitOutput {
    float t;
    float u, v;
    float nx, ny, nz;
    uint32_t primID;
};

// =============================================================================
// Internal Helpers
// =============================================================================

static bool CompileKernelFunction(const char* funcName, oroFunction &funcOut) {
    // Two-step compilation following HIPRT tutorial pattern:
    // 1. Compile source to bitcode with Orochi RTC
    // 2. Link HIPRT traversal routines via hiprtBuildTraceKernelsFromBitcode
    const bool isAmd = (oroGetCurAPI(0) == ORO_API_HIP);

    std::vector<const char*> options;
    if (isAmd) {
        options.push_back("-fgpu-rdc");
        options.push_back("-Xclang");
        options.push_back("-disable-llvm-passes");
        options.push_back("-Xclang");
        options.push_back("-mno-constructor-aliases");
    } else {
        options.push_back("--device-c");
        options.push_back("-arch=compute_60");
    }
    options.push_back("-std=c++17");

    // Add include path so the runtime compiler can find <hiprt/hiprt_device.h>
    static std::string includeOpt = std::string("-I") + HIPRT_SDK_INCLUDE_DIR;
    options.push_back(includeOpt.c_str());

    // Step 1: Compile kernel source to bitcode using Orochi RTC
    orortcProgram prog;
    orortcResult rtcErr = orortcCreateProgram(&prog, g_kernelSource, "hiprt_trace_kernels", 0, nullptr, nullptr);
    if (rtcErr != ORORTC_SUCCESS) {
        Sys_Warning("orortcCreateProgram failed (%s)\n", orortcGetErrorString(rtcErr));
        return false;
    }

    orortcAddNameExpression(prog, funcName);

    rtcErr = orortcCompileProgram(prog, static_cast<int>(options.size()), options.data());
    if (rtcErr != ORORTC_SUCCESS) {
        size_t logSize = 0;
        orortcGetProgramLogSize(prog, &logSize);
        if (logSize > 1) {
            std::string log(logSize, '\0');
            orortcGetProgramLog(prog, &log[0]);
            Sys_Warning("Kernel compile error:\n%s\n", log.c_str());
        }
        orortcDestroyProgram(&prog);
        return false;
    }

    // Extract bitcode (AMD) or PTX (NVIDIA)
    size_t codeSize = 0;
    if (isAmd)
        orortcGetBitcodeSize(prog, &codeSize);
    else
        orortcGetCodeSize(prog, &codeSize);

    if (codeSize == 0) {
        Sys_Warning("Kernel compilation produced empty output\n");
        orortcDestroyProgram(&prog);
        return false;
    }

    std::string bitcode(codeSize, '\0');
    if (isAmd)
        orortcGetBitcode(prog, &bitcode[0]);
    else
        orortcGetCode(prog, &bitcode[0]);

    orortcDestroyProgram(&prog);

    // Step 2: Link HIPRT traversal routines into the compiled bitcode
    hiprtApiFunction function = nullptr;
    hiprtError err = hiprtBuildTraceKernelsFromBitcode(
        g_context,
        1,                          // numFunctions
        &funcName,
        "hiprt_trace_kernels",      // moduleName
        bitcode.data(),
        codeSize,
        0,                          // numGeomTypes
        1,                          // numRayTypes
        nullptr,                    // funcNameSets
        &function,
        false);                     // cache

    if (err != hiprtSuccess) {
        Sys_Warning("hiprtBuildTraceKernelsFromBitcode failed for %s (error %d)\n", funcName, err);
        return false;
    }

    funcOut = reinterpret_cast<oroFunction>(function);
    return true;
}

static bool CompileKernels() {
    Sys_Printf("  Compiling GPU trace kernels...\n");

    if (!CompileKernelFunction("ClosestHitKernel", g_closestHitFunc)) {
        Sys_Warning("Failed to compile ClosestHitKernel\n");
        return false;
    }

    if (!CompileKernelFunction("AnyHitKernel", g_anyHitFunc)) {
        Sys_Warning("Failed to compile AnyHitKernel\n");
        return false;
    }

    if (!CompileKernelFunction("AnyHitKernelBatch", g_anyHitBatchFunc)) {
        Sys_Warning("Failed to compile AnyHitKernelBatch\n");
        return false;
    }

    if (!CompileKernelFunction("ClosestHitKernelBatch", g_closestHitBatchFunc)) {
        Sys_Warning("Failed to compile ClosestHitKernelBatch\n");
        return false;
    }

    Sys_Printf("  HIPRT trace kernels compiled successfully\n");
    return true;
}

static void AllocGpuRayBuffers() {
    if (g_d_ray == 0) {
        oroMalloc(&g_d_ray, sizeof(RayInput));
    }
    if (g_d_hit == 0) {
        oroMalloc(&g_d_hit, sizeof(HitOutput));
    }
}

static void FreeGpuRayBuffers() {
    if (g_d_ray != 0) { oroFree(g_d_ray); g_d_ray = 0; }
    if (g_d_hit != 0) { oroFree(g_d_hit); g_d_hit = 0; }
}

static void EnsureBatchBuffers(size_t numRays) {
    if (numRays <= g_batchCapacity) return;

    if (g_d_batchRays) oroFree(g_d_batchRays);
    if (g_d_batchAnyResults) oroFree(g_d_batchAnyResults);

    // Round up to next power of 2 for growth
    size_t cap = 1024;
    while (cap < numRays) cap *= 2;

    oroMalloc(&g_d_batchRays, cap * sizeof(RayInput));
    oroMalloc(&g_d_batchAnyResults, cap * sizeof(uint32_t));
    g_batchCapacity = cap;
}

static void EnsureBatchHitBuffers(size_t numRays) {
    if (numRays <= g_batchHitCapacity) return;

    if (g_d_batchHitResults) oroFree(g_d_batchHitResults);

    size_t cap = 1024;
    while (cap < numRays) cap *= 2;

    oroMalloc(&g_d_batchHitResults, cap * sizeof(HitOutput));
    g_batchHitCapacity = cap;
}

static void FreeBatchBuffers() {
    if (g_d_batchRays) { oroFree(g_d_batchRays); g_d_batchRays = 0; }
    if (g_d_batchAnyResults) { oroFree(g_d_batchAnyResults); g_d_batchAnyResults = 0; }
    if (g_d_batchHitResults) { oroFree(g_d_batchHitResults); g_d_batchHitResults = 0; }
    g_batchCapacity = 0;
    g_batchHitCapacity = 0;
}

// Fire a single closest-hit ray on the GPU and read the result back
static bool TraceClosest(const RayInput &ray, HitOutput &hit) {
    oroMemcpyHtoD(g_d_ray, const_cast<RayInput*>(&ray), sizeof(RayInput));

    hiprtGeometry geomArg = g_geom;
    oroDeviceptr  rayArg  = g_d_ray;
    oroDeviceptr  hitArg  = g_d_hit;
    void* args[] = { &geomArg, &rayArg, &hitArg };
    oroError oroErr = oroModuleLaunchKernel(g_closestHitFunc, 1, 1, 1, 1, 1, 1, 0, 0, args, 0);
    if (oroErr != oroSuccess) return false;

    oroMemcpyDtoH(&hit, g_d_hit, sizeof(HitOutput));
    return (hit.primID != 0xFFFFFFFF);
}

// Fire a single any-hit ray on the GPU
static bool TraceAny(const RayInput &ray) {
    oroMemcpyHtoD(g_d_ray, const_cast<RayInput*>(&ray), sizeof(RayInput));

    hiprtGeometry geomArg = g_geom;
    oroDeviceptr  rayArg  = g_d_ray;
    oroDeviceptr  hitArg  = g_d_hit;
    void* args[] = { &geomArg, &rayArg, &hitArg };
    oroError oroErr = oroModuleLaunchKernel(g_anyHitFunc, 1, 1, 1, 1, 1, 1, 0, 0, args, 0);
    if (oroErr != oroSuccess) return false;

    HitOutput hit;
    oroMemcpyDtoH(&hit, g_d_hit, sizeof(HitOutput));
    return (hit.primID != 0xFFFFFFFF);
}

#endif // USE_HIPRT


// =============================================================================
// Public API Implementation
// =============================================================================

bool Init() {
#ifdef USE_HIPRT
    if (g_context != nullptr) {
        return true;
    }

    Sys_Printf("Initializing HIPRT ray tracing...\n");

    // Initialize Orochi (GPU abstraction over HIP/CUDA)
    oroApi api = (oroApi)(ORO_API_HIP | ORO_API_CUDA);
    if (oroInitialize(api, 0, g_hip_paths, g_hiprtc_paths) != ORO_SUCCESS) {
        Sys_Warning("Failed to initialize Orochi (no GPU runtime found)\n");
        return false;
    }

    if (oroInit(0) != oroSuccess) {
        Sys_Warning("Failed to initialize GPU runtime\n");
        return false;
    }

    if (oroDeviceGet(&g_oroDevice, 0) != oroSuccess) {
        Sys_Warning("No GPU device found\n");
        return false;
    }

    {
        oroDeviceProp props;
        oroGetDeviceProperties(&props, g_oroDevice);
        Sys_Printf("  GPU device: %s\n", props.name);
    }

    if (oroCtxCreate(&g_oroCtx, 0, g_oroDevice) != oroSuccess) {
        Sys_Warning("Failed to create GPU context\n");
        return false;
    }

    // Initialize HIPRT extension wrangler (dynamic DLL loading)
    int hiprtewResult = 0;
    hiprtewInit(&hiprtewResult);
    if (hiprtewResult != HIPRTEW_SUCCESS) {
        Sys_Warning("Failed to load HIPRT library (error %d)\n", hiprtewResult);
        oroCtxDestroy(g_oroCtx);
        g_oroCtx = nullptr;
        return false;
    }

    // Create HIPRT context
    hiprtContextCreationInput ctxtInput;
    ctxtInput.ctxt   = oroGetRawCtx(g_oroCtx);
    ctxtInput.device = oroGetRawDevice(g_oroDevice);

    {
        oroDeviceProp props;
        oroGetDeviceProperties(&props, g_oroDevice);
        if (std::string(props.name).find("NVIDIA") != std::string::npos)
            ctxtInput.deviceType = hiprtDeviceNVIDIA;
        else
            ctxtInput.deviceType = hiprtDeviceAMD;
    }

    hiprtError rtErr = hiprtCreateContext(HIPRT_API_VERSION, ctxtInput, g_context);
    if (rtErr != hiprtSuccess) {
        Sys_Warning("Failed to create HIPRT context (error %d)\n", rtErr);
        oroCtxDestroy(g_oroCtx);
        g_oroCtx = nullptr;
        return false;
    }

    Sys_Printf("  HIPRT context created successfully\n");

    // Compile GPU trace kernels
    if (!CompileKernels()) {
        Sys_Warning("Failed to compile trace kernels, GPU tracing disabled\n");
        hiprtDestroyContext(g_context);
        g_context = nullptr;
        oroCtxDestroy(g_oroCtx);
        g_oroCtx = nullptr;
        return false;
    }

    // Allocate persistent GPU buffers for single-ray dispatch
    AllocGpuRayBuffers();

    return true;

#else
    return false;
#endif
}


void Shutdown() {
#ifdef USE_HIPRT
    ClearScene();
    FreeGpuRayBuffers();
    FreeBatchBuffers();

    g_closestHitFunc = nullptr;
    g_anyHitFunc = nullptr;
    g_closestHitBatchFunc = nullptr;
    g_anyHitBatchFunc = nullptr;

    if (g_context != nullptr) {
        hiprtDestroyContext(g_context);
        g_context = nullptr;
        Sys_Printf("HIPRT context released\n");
    }

    if (g_oroCtx != nullptr) {
        oroCtxDestroy(g_oroCtx);
        g_oroCtx = nullptr;
    }
#endif
}


void ClearScene() {
#ifdef USE_HIPRT
    if (g_geom != nullptr && g_context != nullptr) {
        hiprtDestroyGeometry(g_context, g_geom);
        g_geom = nullptr;
    }
    if (g_d_vertices != 0) { oroFree(g_d_vertices); g_d_vertices = 0; }
    if (g_d_indices != 0)  { oroFree(g_d_indices);  g_d_indices = 0; }
    g_triangleMeta.clear();
    g_sceneReady = false;
    g_stats = {};
#endif
}


void BuildScene(bool skipSkyMeshes) {
#ifdef USE_HIPRT
    if (g_context == nullptr) {
        Sys_Warning("HIPRT context not initialized, cannot build scene\n");
        return;
    }

    ClearScene();

    auto startTime = std::chrono::high_resolution_clock::now();

    Sys_Printf("Building HIPRT BVH scene...\n");

    g_stats.numMeshes = 0;
    g_stats.numTriangles = 0;
    g_stats.numVertices = 0;

    // Flatten all mesh geometry into a single vertex+index buffer for HIPRT
    std::vector<float> allVertices;   // x,y,z per vertex
    std::vector<uint32_t> allIndices; // 3 per triangle

    for (size_t meshIdx = 0; meshIdx < Shared::meshes.size(); meshIdx++) {
        const Shared::Mesh_t &mesh = Shared::meshes[meshIdx];

        if (skipSkyMeshes && mesh.shaderInfo &&
            (mesh.shaderInfo->compileFlags & C_SKY)) {
            continue;
        }

        if (mesh.triangles.size() < 3 || mesh.vertices.empty()) {
            continue;
        }

        size_t numTris  = mesh.triangles.size() / 3;
        size_t numVerts = mesh.vertices.size();
        uint32_t vertexOffset = static_cast<uint32_t>(allVertices.size() / 3);

        // Append vertices
        for (size_t v = 0; v < numVerts; v++) {
            allVertices.push_back(mesh.vertices[v].xyz.x());
            allVertices.push_back(mesh.vertices[v].xyz.y());
            allVertices.push_back(mesh.vertices[v].xyz.z());
        }

        // Append triangles (re-indexed with vertex offset)
        for (size_t t = 0; t < numTris; t++) {
            uint16_t i0 = mesh.triangles[t * 3 + 0];
            uint16_t i1 = mesh.triangles[t * 3 + 1];
            uint16_t i2 = mesh.triangles[t * 3 + 2];

            if (i0 >= numVerts || i1 >= numVerts || i2 >= numVerts)
                continue;

            allIndices.push_back(vertexOffset + i0);
            allIndices.push_back(vertexOffset + i1);
            allIndices.push_back(vertexOffset + i2);

            TriangleMeta meta;
            meta.meshIndex  = static_cast<int>(meshIdx);
            meta.localPrimID = static_cast<int>(t);
            g_triangleMeta.push_back(meta);
        }

        g_stats.numMeshes++;
        g_stats.numTriangles += numTris;
        g_stats.numVertices  += numVerts;
    }

    if (allIndices.empty()) {
        Sys_Warning("No triangles to build BVH from\n");
        return;
    }

    uint32_t totalVerts = static_cast<uint32_t>(allVertices.size() / 3);
    uint32_t totalTris  = static_cast<uint32_t>(allIndices.size() / 3);

    // Upload vertices to GPU
    oroMalloc(&g_d_vertices, allVertices.size() * sizeof(float));
    oroMemcpyHtoD(g_d_vertices, allVertices.data(), allVertices.size() * sizeof(float));

    // Upload indices to GPU
    oroMalloc(&g_d_indices, allIndices.size() * sizeof(uint32_t));
    oroMemcpyHtoD(g_d_indices, allIndices.data(), allIndices.size() * sizeof(uint32_t));

    // Setup HIPRT triangle mesh
    hiprtTriangleMeshPrimitive mesh;
    mesh.vertices       = reinterpret_cast<hiprtDevicePtr>(g_d_vertices);
    mesh.vertexCount    = totalVerts;
    mesh.vertexStride   = sizeof(float) * 3;
    mesh.triangleIndices = reinterpret_cast<hiprtDevicePtr>(g_d_indices);
    mesh.triangleCount   = totalTris;
    mesh.triangleStride  = sizeof(uint32_t) * 3;

    hiprtGeometryBuildInput geomInput;
    geomInput.type                   = hiprtPrimitiveTypeTriangleMesh;
    geomInput.primitive.triangleMesh = mesh;
    geomInput.geomType               = 0;

    hiprtBuildOptions options;
    options.buildFlags = hiprtBuildFlagBitPreferFastBuild;

    // Get temp buffer size and allocate
    size_t tempSize = 0;
    hiprtError err = hiprtGetGeometryBuildTemporaryBufferSize(g_context, geomInput, options, tempSize);
    if (err != hiprtSuccess) {
        Sys_Warning("hiprtGetGeometryBuildTemporaryBufferSize failed (error %d)\n", err);
        oroFree(g_d_vertices); g_d_vertices = 0;
        oroFree(g_d_indices);  g_d_indices = 0;
        return;
    }

    hiprtDevicePtr d_temp = nullptr;
    if (tempSize > 0) {
        oroMalloc(reinterpret_cast<oroDeviceptr*>(&d_temp), tempSize);
    }

    // Create geometry
    err = hiprtCreateGeometry(g_context, geomInput, options, g_geom);
    if (err != hiprtSuccess) {
        Sys_Warning("hiprtCreateGeometry failed (error %d)\n", err);
        if (d_temp) oroFree(reinterpret_cast<oroDeviceptr>(d_temp));
        oroFree(g_d_vertices); g_d_vertices = 0;
        oroFree(g_d_indices);  g_d_indices = 0;
        return;
    }

    // Build BVH on GPU
    err = hiprtBuildGeometry(g_context, hiprtBuildOperationBuild, geomInput, options, d_temp, 0, g_geom);
    if (err != hiprtSuccess) {
        Sys_Warning("hiprtBuildGeometry failed (error %d)\n", err);
        hiprtDestroyGeometry(g_context, g_geom);
        g_geom = nullptr;
        if (d_temp) oroFree(reinterpret_cast<oroDeviceptr>(d_temp));
        oroFree(g_d_vertices); g_d_vertices = 0;
        oroFree(g_d_indices);  g_d_indices = 0;
        return;
    }

    // Synchronize to ensure build is complete
    oroDeviceSynchronize();

    // Free temp buffer only (geometry buffers must persist while geometry is alive)
    if (d_temp) oroFree(reinterpret_cast<oroDeviceptr>(d_temp));

    auto endTime = std::chrono::high_resolution_clock::now();
    g_stats.buildTimeMs = std::chrono::duration<double, std::milli>(endTime - startTime).count();

    g_sceneReady = true;

    Sys_Printf("  %zu meshes, %zu triangles, %zu vertices\n",
               g_stats.numMeshes, g_stats.numTriangles, g_stats.numVertices);
    Sys_Printf("  GPU BVH built in %.2f ms\n", g_stats.buildTimeMs);

#else
    Sys_Warning("HIPRT not available, using fallback ray tracing\n");
#endif
}


bool TestVisibility(const Vector3 &origin, const Vector3 &dir, float maxDist) {
#ifdef USE_HIPRT
    if (!g_sceneReady)
        return false;

    RayInput ray;
    ray.ox = origin.x(); ray.oy = origin.y(); ray.oz = origin.z();
    ray.dx = dir.x();    ray.dy = dir.y();    ray.dz = dir.z();
    ray.minT = 0.1f;
    ray.maxT = maxDist;

    return TraceAny(ray);
#else
    return false;
#endif
}


bool TraceRay(const Vector3 &origin, const Vector3 &dir, float maxDist,
              float &outHitDist, Vector3 &outHitNormal, int &outMeshIndex) {
#ifdef USE_HIPRT
    if (!g_sceneReady)
        return false;

    RayInput ray;
    ray.ox = origin.x(); ray.oy = origin.y(); ray.oz = origin.z();
    ray.dx = dir.x();    ray.dy = dir.y();    ray.dz = dir.z();
    ray.minT = 0.1f;
    ray.maxT = maxDist;

    HitOutput hit;
    if (!TraceClosest(ray, hit))
        return false;

    outHitDist = hit.t;
    outHitNormal = Vector3(hit.nx, hit.ny, hit.nz);
    float len = vector3_length(outHitNormal);
    if (len > 1e-6f)
        outHitNormal = outHitNormal * (1.0f / len);

    // Map global primID to mesh index
    if (hit.primID < g_triangleMeta.size()) {
        outMeshIndex = g_triangleMeta[hit.primID].meshIndex;
    } else {
        outMeshIndex = -1;
    }

    return true;
#else
    return false;
#endif
}


bool TraceRayExtended(const Vector3 &origin, const Vector3 &dir, float maxDist,
                      float &outHitDist, Vector3 &outHitNormal, int &outMeshIndex,
                      Vector2 &outHitUV, int &outPrimID) {
#ifdef USE_HIPRT
    if (!g_sceneReady)
        return false;

    RayInput ray;
    ray.ox = origin.x(); ray.oy = origin.y(); ray.oz = origin.z();
    ray.dx = dir.x();    ray.dy = dir.y();    ray.dz = dir.z();
    ray.minT = 0.1f;
    ray.maxT = maxDist;

    HitOutput hit;
    if (!TraceClosest(ray, hit))
        return false;

    outHitDist = hit.t;
    outHitNormal = Vector3(hit.nx, hit.ny, hit.nz);
    float len = vector3_length(outHitNormal);
    if (len > 1e-6f)
        outHitNormal = outHitNormal * (1.0f / len);

    // Map global primID to mesh index and local prim ID
    int localPrimID = 0;
    if (hit.primID < g_triangleMeta.size()) {
        outMeshIndex = g_triangleMeta[hit.primID].meshIndex;
        localPrimID  = g_triangleMeta[hit.primID].localPrimID;
    } else {
        outMeshIndex = -1;
    }
    outPrimID = localPrimID;

    // Interpolate UV coordinates from barycentric coordinates
    float u = hit.u;
    float v = hit.v;
    float w = 1.0f - u - v;

    if (outMeshIndex >= 0 && outMeshIndex < static_cast<int>(Shared::meshes.size())) {
        const Shared::Mesh_t &mesh = Shared::meshes[outMeshIndex];
        size_t triIdx = localPrimID * 3;

        if (triIdx + 2 < mesh.triangles.size()) {
            uint16_t i0 = mesh.triangles[triIdx + 0];
            uint16_t i1 = mesh.triangles[triIdx + 1];
            uint16_t i2 = mesh.triangles[triIdx + 2];

            if (i0 < mesh.vertices.size() && i1 < mesh.vertices.size() && i2 < mesh.vertices.size()) {
                const Vector2 &uv0 = mesh.vertices[i0].textureUV;
                const Vector2 &uv1 = mesh.vertices[i1].textureUV;
                const Vector2 &uv2 = mesh.vertices[i2].textureUV;

                outHitUV[0] = w * uv0[0] + u * uv1[0] + v * uv2[0];
                outHitUV[1] = w * uv0[1] + u * uv1[1] + v * uv2[1];
            } else {
                outHitUV = Vector2(0, 0);
            }
        } else {
            outHitUV = Vector2(0, 0);
        }
    } else {
        outHitUV = Vector2(0, 0);
    }

    return true;
#else
    return false;
#endif
}


bool IsSceneReady() {
#ifdef USE_HIPRT
    return g_sceneReady;
#else
    return false;
#endif
}


SceneStats GetSceneStats() {
#ifdef USE_HIPRT
    return g_stats;
#else
    return SceneStats{};
#endif
}


void BatchTestVisibility(int count, const Vector3* origins, const Vector3* dirs,
                         const float* maxDists, uint8_t* results) {
#ifdef USE_HIPRT
    if (!g_sceneReady || count <= 0 || g_anyHitBatchFunc == nullptr) {
        for (int i = 0; i < count; i++) results[i] = 0;
        return;
    }

    // Pack into RayInput array
    std::vector<RayInput> rays(count);
    for (int i = 0; i < count; i++) {
        rays[i].ox = origins[i].x(); rays[i].oy = origins[i].y(); rays[i].oz = origins[i].z();
        rays[i].dx = dirs[i].x();    rays[i].dy = dirs[i].y();    rays[i].dz = dirs[i].z();
        rays[i].minT = 0.1f;
        rays[i].maxT = maxDists[i];
    }

    EnsureBatchBuffers(count);

    // Upload rays to GPU
    oroMemcpyHtoD(g_d_batchRays, rays.data(), count * sizeof(RayInput));

    // Launch batch kernel
    int threadsPerBlock = 256;
    int numBlocks = (count + threadsPerBlock - 1) / threadsPerBlock;

    hiprtGeometry geomArg = g_geom;
    oroDeviceptr raysArg = g_d_batchRays;
    oroDeviceptr resultsArg = g_d_batchAnyResults;
    int countArg = count;
    void* args[] = { &geomArg, &raysArg, &resultsArg, &countArg };

    oroError oroErr = oroModuleLaunchKernel(g_anyHitBatchFunc, numBlocks, 1, 1, threadsPerBlock, 1, 1, 0, 0, args, 0);
    if (oroErr != oroSuccess) {
        Sys_Warning("Batch any-hit kernel launch failed (error %d)\n", oroErr);
        for (int i = 0; i < count; i++) results[i] = 0;
        return;
    }

    // Download results
    std::vector<uint32_t> gpuResults(count);
    oroMemcpyDtoH(gpuResults.data(), g_d_batchAnyResults, count * sizeof(uint32_t));

    for (int i = 0; i < count; i++) {
        results[i] = (gpuResults[i] != 0) ? 1 : 0;
    }
#else
    for (int i = 0; i < count; i++) results[i] = 0;
#endif
}


void BatchTraceRay(int count, const Vector3* origins, const Vector3* dirs,
                   const float* maxDists, float* outHitDists,
                   float* outHitNormalXs, float* outHitNormalYs,
                   float* outHitNormalZs, int* outMeshIndices) {
#ifdef USE_HIPRT
    if (!g_sceneReady || count <= 0 || g_closestHitBatchFunc == nullptr) {
        for (int i = 0; i < count; i++) {
            outHitDists[i] = -1.0f;
            if (outMeshIndices) outMeshIndices[i] = -1;
        }
        return;
    }

    // Pack into RayInput array
    std::vector<RayInput> rays(count);
    for (int i = 0; i < count; i++) {
        rays[i].ox = origins[i].x(); rays[i].oy = origins[i].y(); rays[i].oz = origins[i].z();
        rays[i].dx = dirs[i].x();    rays[i].dy = dirs[i].y();    rays[i].dz = dirs[i].z();
        rays[i].minT = 0.1f;
        rays[i].maxT = maxDists[i];
    }

    EnsureBatchBuffers(count);
    EnsureBatchHitBuffers(count);

    // Upload rays to GPU
    oroMemcpyHtoD(g_d_batchRays, rays.data(), count * sizeof(RayInput));

    // Launch batch closest-hit kernel
    int threadsPerBlock = 256;
    int numBlocks = (count + threadsPerBlock - 1) / threadsPerBlock;

    hiprtGeometry geomArg = g_geom;
    oroDeviceptr raysArg = g_d_batchRays;
    oroDeviceptr hitsArg = g_d_batchHitResults;
    int countArg = count;
    void* args[] = { &geomArg, &raysArg, &hitsArg, &countArg };

    oroError oroErr = oroModuleLaunchKernel(g_closestHitBatchFunc, numBlocks, 1, 1, threadsPerBlock, 1, 1, 0, 0, args, 0);
    if (oroErr != oroSuccess) {
        Sys_Warning("Batch closest-hit kernel launch failed (error %d)\n", oroErr);
        for (int i = 0; i < count; i++) {
            outHitDists[i] = -1.0f;
            if (outMeshIndices) outMeshIndices[i] = -1;
        }
        return;
    }

    // Download results
    std::vector<HitOutput> gpuHits(count);
    oroMemcpyDtoH(gpuHits.data(), g_d_batchHitResults, count * sizeof(HitOutput));

    for (int i = 0; i < count; i++) {
        if (gpuHits[i].primID != 0xFFFFFFFF && gpuHits[i].t >= 0) {
            outHitDists[i] = gpuHits[i].t;
            if (outHitNormalXs) outHitNormalXs[i] = gpuHits[i].nx;
            if (outHitNormalYs) outHitNormalYs[i] = gpuHits[i].ny;
            if (outHitNormalZs) outHitNormalZs[i] = gpuHits[i].nz;
            if (outMeshIndices && gpuHits[i].primID < g_triangleMeta.size()) {
                outMeshIndices[i] = g_triangleMeta[gpuHits[i].primID].meshIndex;
            } else if (outMeshIndices) {
                outMeshIndices[i] = -1;
            }
        } else {
            outHitDists[i] = -1.0f;
            if (outHitNormalXs) outHitNormalXs[i] = 0;
            if (outHitNormalYs) outHitNormalYs[i] = 0;
            if (outHitNormalZs) outHitNormalZs[i] = 0;
            if (outMeshIndices) outMeshIndices[i] = -1;
        }
    }
#else
    for (int i = 0; i < count; i++) {
        outHitDists[i] = -1.0f;
        if (outMeshIndices) outMeshIndices[i] = -1;
    }
#endif
}

} // namespace HIPRTTrace
