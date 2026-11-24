# Scope of work: Apex Legends / R5Reloaded

Date: 24 November 2026. Companion index:
[SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md). Do not transfer an
item to Apex by matching TF2 v37 lump numbers. Pin the game build, season corpus
and R5Reloaded SDK before starting any item.

## Pinned targets and current boundary

| Source / runtime | Build or revision | Boundary |
| --- | --- | --- |
| Installed S3 game | `R5pc_r5launch_N1094_CL456479` (30 October 2019), under `F:/Games/Apex Detours/R5Reloaded` | S3-native references: World's Edge `mp_rr_desertlands_64k_x_64k` and Firing Range `mp_rr_canyonlands_staging`; Kings Canyon `mu1`/`mu1_night` also shipped. Aqueduct in this install is a later Arenas backport, not an S3 reference. |
| R5Reloaded | SDK v2.3 for the native harness; Flowstate scripts 4.1 in the recorded branch tests | Later SDK/season builds are untested. |
| `apex-s3-compiler` branch | HEAD `709e770`; backend ported from r5valkyrie `feat_lightmap_tweaks` `2c5564d`, based on fork `main` `5f7caa5` | This is the only branch with substantial Apex compiler support. It is **not** on `main` or `tf1-tfo-compatibility`. |
| Checked-out integration branch | `tf1-tfo-compatibility` at `d58cc3e` | Has the older stub Apex path plus the experimental TF2→Apex converter; it lacks the branch-local S3 backend. |
| Earlier Apex fork review | r5valkyrie/MRVN-Radiant `main` `5f7caa5` | Selective source integration only; not a merge or compatibility certificate. |

Baseline evidence:
[RESPAWN_APEX_FORK_REVIEW.md](RESPAWN_APEX_FORK_REVIEW.md),
[RESPAWN_APEX_S3.md](RESPAWN_APEX_S3.md) on `apex-s3-compiler`,
[RESPAWN_TF2_TO_APEX.md](RESPAWN_TF2_TO_APEX.md),
[RESPAWN_R5_HARNESS.md](RESPAWN_R5_HARNESS.md),
[RESPAWN_COMPATIBILITY.md](RESPAWN_COMPATIBILITY.md) and
[RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md).

**Headline:** Apex is no longer only a geometry-conversion experiment. The
`apex-s3-compiler` backend was merged into a one-hash integration worktree with
the TF1 acceptance and TF2 lighting changes; the resulting compiler passes the
full 69-report suite. A dev-textured fixture room and a recovered TF2 `mp_box`
load in the S3 rendered client, with 14/14 native trace checks and visible
per-face lightmaps/prop contact shadows. That native evidence predates the
one-hash compiler and has not been replayed under it, so this remains a bounded
proof of concept, not full season or asset compatibility.

## Map support

### APEX-BRANCH-01 — integrate the S3 compiler branch — Partial (`S`/`B`/`N`)

`apex-s3-compiler` has 11 commits beyond the shared base
(`57ede40`). They add the r5valkyrie Apex backend and its S3 corrections:
real collision, prop editor copies, per-face lightmap charts, trimmed pages,
light/shadow/visibility encoding, a native regression and 22-bit tree indices.
The backend was merged into `.local/respawn/integration-one-hash` (branch
`integration-one-hash`) on top of `tf1-r1-acceptance`, with the two Surf Beginner
packaging commits cherry-picked from `tf1-tfo-compatibility`. Three Apex defects
found while validating the merge were fixed in that worktree before the final
build: exact texture-name lookup, vertex-type selection for flags `0x600`, and a
non-degenerate prop fixture. The final compiler SHA-256 is
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110`; the first
integrated build `2a8b09d9…` is superseded.

The one-hash build passes `compiler_regression.py` with 69 reports and zero
issues: 37 `titanfallonline`, 29 `titanfall2` and 3 `apexlegends`. It also passes
316 Python unit tests and six C++ tests. The older 33/26/Apex counts are no
longer the acceptance totals.

**Missing:** replay the 14/14 native Apex fixture under this exact compiler
hash, from a clean checkout. The retained rendered-client result belongs to the
earlier `apex-s3-compiler` build and must not be claimed for the one-hash binary.

**Acceptance:** one build from the chosen base contains the S3 backend, passes
the full compiler suite (met), and reproduces the branch's 14/14 native fixture
from a clean checkout (open).

### APEX-MAP-01 — season-pinned v47 profile and corpus — Partial (`S`/`B`)

S0–S3 shipped maps all use rBSP 47, header revision 30 and version 0 for every
lump; static props are 64-byte records with the same parented-prop tail. The
branch therefore has evidence for a common S0–S3 layout, but only S3 was run
natively. S0–S2 have no harness here. Read-only `inspect_bsp.py` checks on six
local samples (S0/S1/S2 Canyonlands or Kings Canyon, S3 World's Edge and Firing
Range, plus the Aqueduct backport) reported zero structural issues. The compiled
`regress-5` fixture is also structurally clean and has nonzero world-light,
lightmap, CSM, probe, RTL, visibility and shadow-mesh lumps; its PAKFILE is empty,
consistent with the missing baked cubemap VTF.

`LoadR5BSPFile()` is explicitly unimplemented in `apex_legends_bsp.cpp:49-50`;
`EmitStubs()` is declared but has no Apex definition. These are not proven
blockers for the normal fixture path, but they are not full-format implementations.

Earlier conclusions based on the backported Aqueduct were corrected: its
`0x61` BC7 lightmap copy and lightmap header flag `0x08` are later-season
features, not S3 features. S3 maps carry `cubemaps.hdr.vtf` in PAKFILE and 6.5
bytes per texel of realtime light data; the compiler writes neither the later
`0x61` nor the flag.

**Missing:** a runtime gate for each advertised season, or an explicit statement
that S0–S2 share the layout but are untested; bounded validators for lump
versions and field semantics; unsupported-version failure path.

**Acceptance:** compiled map validates and loads for every advertised season;
profiles record engine hash, corpus hashes, lump versions and sample sizes.

### APEX-MAP-02 — models, props, entities and triggers — Partial (`B`/`N`)

The branch adds `cast_to_obj.py` to create editor copies from RSX Cast exports,
so `mdl/x.rmdl` finds `models/mdl/x.obj` for bounds and collision-leaf
placement while the game lump keeps the `.rmdl` name. A `trigger_multiple`
spawned with its brush bounds, was non-solid, and `IsTouching` reported the
player only inside. Three barrel props rendered in the fixture room, and the
recovered `mp_box` (274 entities) compiled in under four seconds to a 35 MB BSP
and loaded on the client.

**Missing:** moving brush entities (`func_brush`, doors, platforms, rotating
brushes), a general brush-submodel collision emitter (the trigger `*coll` path is
a special case), other trigger classes, arbitrary model/material dependency
closure, navmesh files and multiplayer gameplay. The older TF2→Apex converter's
requirement for entity lump 24 to start with `01* env fx script snd spawn` plus
NUL is not a general writer gate.

**Acceptance:** authored map with arbitrary props and movers loads in dedicated
and rendered clients; all entity partitions and visibility IDs validate against
a season-matched retail sample; no missing-material checkerboard.

### APEX-MAP-03 — packaging and dependency closure — Partial (`N`)

`stage_r5_map.py` builds client and `server_` VPKs, all five `.ent` partitions,
level `.rson`/`.kv` and a bounds script, and installs only `mp_mrvn_*` levels.
The older port also required `englishserver_MAP.bsp.pak000_dir.vpk` plus its
chunk for dedicated R5. Map materials must already be in a loaded pak;
`world/dev/dev_gray_512` is always available.

**Missing:** clean cold-load closure for custom textures/models/RPak assets,
texture streaming and STARPaks, RPak version coverage, GUID collision checks,
and all game modes/playlists beyond the tested Flowstate setup.

**Acceptance:** fresh deployment with authored assets; no GUID collisions;
repeatable compile→stage→load→uninstall cycle; full mode discovery recorded.

## Collision

### APEX-COL-01 — native fixture and retail-shaped emitters — Partial (`B`/`N`)

The branch replaced the previous stub path, whose custom maps had no collision
and let the player fall through the floor. In S3, `apex_native_regression.py`
passed 14/14 checks: floor, ceiling, walls, block top/side, ramp at two heights,
hulls against ceiling/block/wall, barrel side/top, trigger non-solidity and
trigger bounds. Traces stop about 1/32 unit short, within tolerance. A burned
barrel cast a sun shadow after the CSM reference fix.

Retail visibility trees have one root per cell (265 on World's Edge), internal
nodes before leaves in 0x77–0x79, subtree totals in 0x25, and 22-bit indices.
The branch lifted the old 65,535-object limit to 4,194,303 and fixed the fork's
loss of objects past 255; 320 barrels now all draw. The current source still
emits exactly one cell (`EmitCells`) and only sky portals (`EmitPortals`), so the
retail-shaped tree encoding is validated but multi-cell topology is not.

**Missing:** broad authored geometry, water, moving props, projectile traces,
authored portal graphs, large multi-cell culling measurement, and exact BVH field
parity.

**Acceptance:** native trace suite on an authored large map with several cells;
matched retail comparison; record all contents values and harness reports.

### APEX-COL-02 — branch backend differential review — Partial (`S`/`N`)

Before the S3 corrections, the r5valkyrie backend's own compiler was built and
tested: a dev-textured box rendered with lightmaps and ten line/hull traces
matched its geometry. That justified adopting the backend, but the fork had
wrong collision/visibility encodings that the engine tolerated without
crashing. The branch fixed the realtime light, mesh, lightmap, RTL, probe,
visibility, CSM and tree-index layouts against retail samples.

**Missing:** differential structural and native tests after integration; verify
that no later edit regressed the fork's successfully traced geometry.

**Acceptance:** old and new compiler outputs compared with `inspect_bsp.py`,
`validate_records.py` and the 14-check native fixture; failures retained.

## Lighting and shadows

### APEX-LGT-01 — branch lighting implementation — Partial (`B`/`N`)

The branch writes S3-shaped world lights, mesh records, two lightmap planes,
RTL pages and probes:

- World lights (0x36): brightness/attenuation/flags/order fitted to all 359
  retail records; PBR `_pbr_falloff` uses ×100000.
- Mesh records (0x50): TF2-like layout after `triCount`; a wrong field had made
  static lights wash a room white.
- Lightmaps (0x62): plane A RGBM static light + ambient fill, no sun; plane B
  bent sky direction × cbrt(sky visibility), alpha = sun visibility. The rendered
  fixture shows corner darkening and a sun patch with a pillar shadow.
- RTL (0x69/0x7A): per-page slot plane, two BC5 visibility textures and a BC4
  plane; external sidecars omit BC4. Hardware indices are world index minus
  ambients before it. A realtime spot lit the floor with a realtime pillar shadow.
- Probes (0x65): 12 SH values, sky vector, sun visibility and weights/indices at
  +0x20/+0x24, cross-checked against the R5 SDK `dlightprobe_t`.

**Missing:** point/spot light baking is not natively confirmed (the baker follows
VRAD and a `light` without `_quadratic_attn` has constant falloff); static-light
RTL/probe references are not reproduced; character lighting is untested;
props and patches do not occlude baked light.

**Acceptance:** authored indoor/outdoor fixture with point, spot and sun lights;
raw plane exports and native captures agree with a season-matched retail
control; third-person probe response checked near static and realtime lights.

### APEX-LGT-02 — lightmap quality and cubemaps — Partial (`S`/`B`)

Per-face charts, trimmed 1024-wide pages and chart-plane origins fixed corrupted
UVs, page-size mismatch and sloped-texel placement. The 32-ray sky term still
produces jagged bands on some walls; bounce light and patch/prop occlusion are
not implemented. S3 cubemaps are one VTF 7.5 in PAKFILE: 256×256, one frame per
cubemap, format 66 (Respawn-specific, about one byte per texel, probably BC6H),
9 mips, flags `0x420c`, plus a `CMA` resource. The compiler does not write it:
`EmitCubemaps()` writes 25 identical samples at world center with `guid = 0`, and
the compiled fixture's PAKFILE is empty while retail S0–S3 PAKFILEs contain
`cubemaps.hdr.vtf`.

**Acceptance:** bake and write `cubemaps.hdr.vtf` in S3 format; compare rendered
reflections; add patch/prop occluders, bounce and sky-filter improvements with
before/after captures.

### APEX-LGT-03 — CSM and alpha shadows — Partial (`N`)

CSM references include every shadow mesh plus shadow-casting props by object id,
with light-space node bounds. The barrel now casts a sun shadow. Static lights
are baked into plane A and probe SH; RTL slots and probe light references are
for realtime lights only, as in Titanfall 2.

**Missing:** alpha-tested shadow streams, multi-environment stress, menu/gameplay
isolation and controlled projected-shadow image comparison.

**Acceptance:** opaque and alpha casters in an authored fixture, paired captures
at matched cameras, and recorded engine/RPak/BSP hashes.

## Runtime acceptance gate

The S3 branch has cleared a bounded rendered-client gate: fixture room with dev
textures, per-face lightmaps, three props and a ramp; `mp_box` load; trigger
touch; and 14/14 native trace checks in `regress-2` through `regress-5`.
`regress-1` timed out before spawning, so load stability was not automatic. The
backend is now in the one-hash compiler and its three Apex compiler reports pass,
but the native result has **not** been replayed under that exact binary. It has
**not** cleared full compatibility. Before advertising Apex support:

1. reproduce the 14/14 native result under compiler
   `b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` from a
   clean checkout (compiler integration itself is complete);
2. boot with custom materials/models and no missing-material checkerboard;
3. show dome/sky/cubemaps at matched cameras;
4. run a short first-person session in the selected mode with multiplayer;
5. verify S0–S2 in their own runtimes or explicitly scope support to S3;
6. generate navmesh files and test AI/gameplay;
7. record engine/RPak/VPK/BSP hashes and all harness reports.

The earlier V16 port's rendered-client crash at RVA `0x5c93f6` and
`render_verified: false` belong to the older converter/harness evidence, not to
the S3 branch's successful client session. Do not mix the two evidence sets.
