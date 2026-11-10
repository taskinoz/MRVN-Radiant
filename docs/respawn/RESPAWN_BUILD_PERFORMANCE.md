# Compiler and lighting performance (8 November 2026)

The TF1/TFO and TF2 compiler paths now use an epsilon spatial index for vertex
and normal deduplication instead of scanning all previous vectors. Queries
still use the original comparison and return the earliest matching index.
This preserves insertion order and handles vectors appended directly by the
collision writer. Buckets and links use contiguous arrays, with temporary
indices reset before compilation and freed after geometry emission, before
lighting. Out-of-range and nonfinite coordinates use a scan rather than an
undefined floating-point-to-integer conversion.

The convex shadow BVH precomputes each ray's reciprocal direction, visits the
nearer child first, and checks individual brush bounds before testing planes.
The per-brush plane test, shadow samples, ray offsets, lighting equations and
encodings are unchanged. Bounce still uses the original first-hit traversal.

Direct irradiance scratch now covers one lightmap page rather than all pages.
After that page's workers join, its texels enter the radiance grid in the same
page/texel order as before, then its scratch and realtime-slot arrays are
released. Baked colour arrays are allocated as their pages are processed.
The complete grid is ready before bounce, cubemap or character-probe gathers.

The baker was already multithreaded, but ignored remap's `-threads` setting.
It now honours that setting for both TF1 and TF2. For example:

```powershell
remap.exe -threads 4 -game titanfall2 -fs_basepath MAP_ROOT -bsp MAP_FILE
```

Reducing the worker budget preserves baked output. Geometry emission remains
ordered because vertex IDs and first-match deduplication affect binary output.
Stage timings now identify geometry, collision, visibility, lightmap passes,
probes, shadows and cubemaps in the compile log.

## Before and after

The measured workload is `mp_minecraft_survival_games`: a 122,668,451-byte
source map producing a 314,909,060-byte BSP, compiled with the same assets,
command and source directory. The Windows machine exposes 16 logical CPUs.
Baseline binary was preserved before optimization; the optimized binary is
also saved with a SHA-256 digest in its report.

| Measurement | Before | After | Reduction |
| --- | --- | --- | --- |
| Full compile | 287.5 s | 89.9 s | 68.7% |
| CPU work (sampled) | 1765.4 CPU s | 1189.9 CPU s | 32.6% |
| Peak working set | 2.25 GiB | 1.72 GiB | 23.2% |
| Peak committed memory | 2.38 GiB | 1.85 GiB | 22.1% |

The measured full compile is 3.20 times faster. These are one
measured full compile per final version, not statistical averages. CPU time
is sampled every 100 ms; memory uses Windows process lifetime peak working-set
and commit counters. A small background compiler build overlapped part of the
baseline run; the final optimized measurement had no other build jobs. Earlier
runs measured 292 seconds for the original build and 92?93 seconds for the
intermediate optimization, consistent with the improvement. Results depend on
the map, CPU, cache state and other work on the machine.

## Output verification

- All 128 Survival Games lump payloads, versions, lengths and FourCC values
  match, as do its BSP header and directory and all 3 compared sidecars.
- The baseline and final compiler each pass all 55 regression fixtures.
  All 128 lump payloads and metadata match in each of 57 generated BSPs,
  including TF1, TF2 and the shared Apex smoke fixture; nine entity sidecars
  are byte-identical.
- The complete BSP files match after excluding the embedded build-time comment
  and two bytes at the ends of the baseline's version/time comment blocks.
  Investigation found those two bytes uninitialized by `strncpy(..., 63)` into
  a 64-byte buffer. TF1/TF2 now zero-initialize both buffers. These comments sit
  outside every lump and do not change geometry, physics or lighting.
- Separate TF1 and TF2 lit-map CLI builds match their baseline across all 128
  lump payloads with `-threads 1` and `-threads 4`.
- Six repository C++ tests pass, plus a local differential check of 308,000
  ray results against the frozen original BVH and a two-page bake with bounced
  probes against the original baker. Vertex-index tests cover epsilon
  boundaries, first-match ordering, direct appends, cache resets and extreme
  coordinates. Lighting tests compare lightmaps and probes at one, two and
  four workers.
- All 218 Python tests pass; MSVC Release build and `git diff --check` pass.

The measured speedup is not a completeness claim for either compiler. No native
game session was needed for this optimization pass: the verified game-data
bytes are unchanged. Existing unresolved format and runtime-parity work stays
tracked in the TF1/TF2 and triangle-collision notes.

Local evidence is saved in `.local/respawn/perf/`: `comparison.json`,
`before-measured.json`, `after-memory.json`, the preserved baseline binary and
BSP, `regression-byte-comparison.json`, `lighting-cli-comparison.json`,
`tests-memory.log`, `python-tests.log`, and the compile logs. The measurement
and comparison scripts, frozen reference header and differential check source
are saved alongside them. Large map assets and binaries are not checked in.
