# Scope of work: Titanfall 2 / Northstar

Date: 24 November 2026. Companion index:
[SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md). This document
tracks the v37 path only. Do not transfer an item to Apex by matching lump
numbers; Apex needs its own pinned corpus and engine checks.

Path convention: `.local/respawn/...` paths for integration and older branch
evidence are relative to the main `C:/Users/Tristan/GitHub/MRVN-Radiant`
checkout. Closure-owned one-hash evidence under
`.local/respawn/tf2-lighting-onehash-native-20261124` is relative to
`.local/respawn/tf1-tfo-closure`. Absolute paths are used for game installs and
profiles outside those checkouts.

## Pinned target and current boundary

| Runtime | Installed build | Boundary of existing evidence |
| --- | --- | --- |
| Titanfall 2 + Northstar | `C:/Games/Titanfall2`, `gameversion.txt` `v2.0.11.0`; installed `R2Northstar/mods/Northstar.CustomServers/mod.json` reports `1.31.16`; `Northstar.dll` Windows metadata reports `1.31.10-rc3` / `1.31.10.0` | Native evidence includes a fresh 24 November 2026 test in the separate `R2MapHarness` profile, whose loaded mods report Northstar `1.31.13`. The main `R2Northstar` profile was not retested at its `1.31.16` label. These labels disagree; use hashes. |

Pinned fingerprints from the installed files audited:

| Artifact | SHA256 |
| --- | --- |
| `bin/x64_retail/engine.dll` | `58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487` |
| `bin/x64_retail/client.dll` | `002b36487fec7c98882929fbccdb506d0146bbf3270cbb964a4d21c5edf7eebc` |
| `Northstar.dll` | `2e61dcc0985bae364fa2c2fac91dbe3578bff73748cac5f22e036038a06ed50` |
| `R2Northstar/mods/Northstar.CustomServers/mod.json` | `3b58d0b03e371492ad1a59a63e22cfcf0ee0f04459b583d06536b60f46b1a042` |
| `R2MapHarness/Northstar.dll` (native test profile) | `ff9bd1dc1606a2f3e8109d52b3d9a491b07869fc04cf600aabcdf47fb2c96547` |
| `R2MapHarness/mods/Northstar.CustomServers/mod.json` | `5fadd42c51c8d084404467b246f9cc55501167129db430fbdd0781d075aa58f3` |
| `.local/respawn/tf2-visbudget-native/report.json` | `cb4523cdcd2ff7be68f73d5ed743829d5697c6e25646ca4d0b90d2c778151155` |
| Original 24 November TF2 evidence build (`install/Release/remap.exe`) | `6daec3b2309802af6ecfd17d2635a8a7e693b07d59325094c2dd1fcebf81ff94` |
| Final one-hash integration build (`.local/respawn/integration-one-hash/install/Release/remap.exe`) | `b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` |

The engine hash is the one matched by `audit_tf2_budget.py`; the 3,145,728-index
/ 2,048-batch budget profile must not be applied to another build without a new
hash check.

Compiler target is `titanfall2`, BSP v37. The original evidence build passed 289
Python unit tests, six C++ reader/bake tests and the isolated `lit` and
`lit-sky-samples` fixtures; its main-tree full sweep stopped earlier on the
unrelated TF1 `sky-only` fixture (`ledge client data outside CM_BRUSHES`). The
final one-hash integration build passes the whole compiler suite: 69 reports,
zero issues, including 29 `titanfall2` fixtures. It also passes 316 Python unit
tests and six C++ tests. Isolated compiler replays of the TF2 lighting fixtures
produced lump payloads identical to the original evidence build; only BSP header
timestamp bytes differ. Broader native captures below remain tied to the earlier
`6daec3b2…` build, but one bounded one-hash native replay is recorded below.

A fresh native smoke pass on 24 November 2026 loaded that fixture as
`mp_mrvn_tf2light_stock` in the isolated `R2MapHarness` profile. The log shows
`LevelLoadingFinished`, the level script marker, a `LoadStreamBsp` load and a
clean `LevelShutdown`; the harness reports no errors, four 1280×720 captures and
two floor traces ending at z=0.03125 on both the roofed and unroofed sides.
Stock Coliseum materials replaced the magenta fallback materials used in an
earlier retained run. The shaded view has mean luminance 55.73 versus 81.13 for
the sunlit view, with a 42.05 mean per-pixel luminance difference. Evidence:
`.local/respawn/tf2-lighting-native-stock-20261124/native-run/native-evidence.json`
(harness report SHA-256 `fd26cf51c53403adc937e49d47dc50d994c3e9ca3b2cfea672ffa9a910af2113`,
build manifest SHA-256 `01fcbedddc0f16aea59e8a495d23f8e63687e622d6c9446a00c11e7c625f4584`).
This certifies load/render/shutdown for this fixture only, not shader-level
channel semantics or every light class, and it used the `1.31.13` harness
profile rather than the main `1.31.16` profile.

The same fixture was recompiled with compiler
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` and loaded
in an ARES-owned profile seeded from the pinned `R2MapHarness` `Northstar.dll`
(`ff9bd1dc1606a2f3e8109d52b3d9a491b07869fc04cf600aabcdf47fb2c96547`) and core
mods. All lump payloads matched the earlier BSP; the loaded/finished report has
the same two floor traces ending at z=0.03125, four nonblank captures, no script
errors and no crash dumps. Replay BSP SHA-256
`a7e2e38eb1d7e4967753c69d6e80096d2068e73e036b491bf49711923cd949bc`; report
SHA-256 `5d6f5f3e4be56dd76320de49cce9fdf31e8cf71ac30f89f08b7813c891af87d7`.
Evidence: `.local/respawn/tf2-lighting-onehash-native-20261124/native-evidence.json`
(SHA-256 `ec5f6b2aa59a81e1de2bdb83cd9fb38c7fd0a5a2397bb9b250152dff0455cdc0`).
This is a load/render/shutdown replay only, with window-fallback captures; it
does not test the `R2Northstar` `1.31.16` label or add image comparison.

Baseline evidence:
[RESPAWN_MAP_SUPPORT_AUDIT.md](RESPAWN_MAP_SUPPORT_AUDIT.md),
[RESPAWN_TF2_LUMPS.md](RESPAWN_TF2_LUMPS.md),
[RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md),
[RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md),
[RESPAWN_GAME_LUMP.md](RESPAWN_GAME_LUMP.md),
[RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md),
[RESPAWN_NORTHSTAR_TEST.md](RESPAWN_NORTHSTAR_TEST.md) and
[RESPAWN_MP_BOX.md](RESPAWN_MP_BOX.md).

## Map support

### TF2-MAP-01 — v37 writer coverage vs. retail corpus — Partial (`B`)

The writer covers all 81 surveyed named lumps when seven empty retail lumps are
counted; 74 explicit payload write paths cover 74 fixed-record schemas in a
different count. The eight-map corpus passes structural validation. Empty lumps
(`LEAF_WATER_DATA`, `WORLD_LIGHT_PARENT_INFOS`, `PHYSICS_LEVEL`,
`PHYSICS_TRIANGLES`, `VERTEX_RESERVED_5-7`) are intentionally not emitted.

**Missing:** field semantics for approximate records, broad corpus breadth beyond
eight maps, and production-scale checks of the engine budgets.

**Acceptance:** expand the corpus to small/large interiors, exteriors, water and
prop-heavy maps; run `inspect_bsp.py`, `validate_records.py` and
`audit_tf2_budget.py` with the pinned `engine.dll` hash; keep unknown fields
explicit.

### TF2-MAP-02 — static props and model/material closure — Partial (`B`/`N`)

The `sprp` v13 reader handles 52,588 retail placements; the compiler preserves
prop scale/skin, lighting origins and 64-aligned visibility IDs. Custom maps have
reproducible VPK/RPak/STBSP recipes and recorded loads.

`build_northstar_test_mod.py` writes the BSP, five ENT partitions, STBSP catalogue,
VPK, RPak alias JSON and loose sky-vista MDL, and verifies VPK round-trip, but it
records `ingame_tested: false`. `pack_vpk.py` is for small test packages and
`rpak.py` is read-only; neither is a production closure writer.

**Missing:** arbitrary model/material/texture dependency closure, streaming data,
all shader passes, unknown game-lump versions, a TF2 equivalent of TF1's
manifest/`--strict` closure check, and a clean cold-load deployment. The
world-index audit knows only one exact engine hash (`58eb1a1b…`) and a
conservative 3,145,728-index / 2,048-batch profile; applying it to another build
would be unverified.

**Acceptance:** clean test deployment with custom assets loads and renders;
verify exact engine hash before using a capacity profile; include a prop-heavy
stress map and record missing assets as failures.

### TF2-MAP-03 — visibility and runtime area portals — Partial (`N`)

Opt-in `_viewportals "1"` emits whole-BSP-subtree cells, portals, sky apertures,
intersection tables and per-cell object trees. A 1,022-cell / 6,970-directed-portal
stress fixture passed selected traces and three views in Northstar `1.31.13`.

**Missing:** full culling parity, water portals, global environment cells,
runtime areaportal open/close, leaks, and texture-streaming interaction.

**Acceptance:** paired rendered captures and frame-time/culling probes across a
large authored map; verify that authored area portals change at runtime; keep
the default one-cell fallback distinct from the opt-in path.

### TF2-MAP-04 — gameplay and release workflow — Partial (`N`)

Recorded loads/play include E1M1, Jump Academy 2, Trainstation, Nuke, mp_box,
Coliseum, lobby and rebuilt retail samples. Custom pilot gameplay and map scripts
exist.

**Missing:** all-mode acceptance, sustained multiplayer, navmesh/AI/titan
generation, repeated cold loads and a complete editor-to-game workflow.

**Acceptance:** a pinned build runs a repeatable authored map through spawn,
objectives, movement and reload with no missing dependencies; record mode and
duration.

## Collision

### TF2-COL-01 — brush collision and bevels — Partial (`B`/`N`)

The shared emitter preserves axial faces, side prefixes and bevel rules; 172
native box sweeps validate the bevel path. CM primitive grouping reduced a large
test map from 55,845 to 45,709 geo sets.

**Missing:** exact retail bevel generation parity; `TRICOLL_BEVEL_INDICES`
geometric selection. In a Coliseum sample, 12,658 of 20,067 unique ordinary
references target triangles without an exactly shared vertex, so vertex/edge
adjacency alone is not a valid rule.

**Acceptance:** differential collision sweeps against matched retail geometry,
plus a decision to keep the functional supporting-plane rule or decode the
retail selector fully.

### TF2-COL-02 — triangle collision — Partial (`B`/`N`)

Patch grids emit headers of at most 300 triangles with the retail vertex
encoding. Thirteen sampled displacement floors collided at their surface height
in game. Flat-triangle tie handling is covered by compiler regressions; all but
15 triangles in six TF2 maps match the rule.

**Missing:** the near-tie exceptions, broad backface/transform coverage, water
collision, moving props and projectile/titan sweeps.

**Acceptance:** retain and explain the 15 exceptions; paired native sweeps for
all patch orientations and entity transforms; explicit projectile/titan checks.

### TF2-COL-03 — water and displacement-like geometry — Partial (`B`/`N`)

`LEAF_WATER_DATA` and `PHYSICS_LEVEL` are empty in the corpus. Recorded map
trials cover displacement-floor collision but not a comprehensive water/physics
matrix.

**Acceptance:** authored water volumes with matched dry controls and native
buoyancy/underwater checks; document which water structures remain empty and why.

## Lighting and shadows

### TF2-LGT-01 — baked lightmaps and RTL — Partial (`N`)

The compiler bakes lightmaps when a map places light entities, writes character
probes, one diffuse bounce into SKY A and CSM shadow meshes; baked maps play in
Northstar. RTL A/B/C layouts, 63-slot pages and hardware light indices are
measured against Coliseum and Glitch. Current source emits ambient, sun, spot
and point lights, including `_pbr_falloff 1` scaling and spot cone/normal fields.
World-light flags now follow the retail key bit field (4/32 falloff, +8 realtime,
+16 no realtime shadows, +64 dynamic shadows; suns 24), `LEVEL_INFO.unk2` is the
last sun normal, and `"shadow" "0"` no longer drops RTL slots. `analyze_rtl.py`
reproduces the retail flag audit. v2/v1 records are inspected but not emitted.
Earlier scope notes claiming these were missing are stale.

A second 24 November fixture adds one light class per sealed room: an unlit
control with zero ambient, baked point, realtime point, spot and `_pbr_falloff 1`
spot. The control's captured centre luminance is 0.00; the four lit rooms are
32.23, 30.98, 36.20 and 36.76. A tracked compiler regression checks the expected
world-light types and flags
`[(5,0), (3,24), (2,28), (2,56), (1,4), (1,28)]`. Evidence:
`.local/respawn/tf2-light-classes-20261124/native-run/native-evidence.json`
(report SHA-256 `5c2f1d038d5bf465031a5c251d3593cfe62f9be8c013f20eb1c97e73d920501b`).
This closes the per-class native capture gate, but not brightness parity. The
one-hash integration build (`b0a80649…`) recompiled all three TF2 lighting
fixtures: `light-classes`, `tf2-alpha-shadow` and `tf2-env-volume` had identical
lump payload hashes to the `6daec3b2…` baseline. This is a compiler-output
replay, not a new native session. The replay BSP SHA-256 values are
`98759a437bf4075c36ea6186e0582082d566e0e61ef3b07561582ba8ff5dd1f5`,
`62598967909f5089e02d79d9ded397cef97cd0cc89ea4ca1ae24ce81fc5287d8` and
`74499f186835fd8ef596fe9308b6eb292e7850deda2c15295fe96eefce285fcf` in that
order; whole-BSP bytes differ from the baseline only in header timestamp fields.
Evidence: `.local/respawn/integration-one-hash-replay/integration/results.json`
(SHA-256 `29017908A2E67186981F6EA3AE5CC862A1845B15B5264A790A1808AE7A5AFB36`).

**Missing:** styled/targeted lights, v1/v2 record emission, full shader-level
channel semantics, a native RTL/SKY A/B under the one-hash compiler, and
fill-level agreement across retail maps. The one-hash smoke replay above proves
load/trace/capture only.

**Acceptance:** decode RTL channels with engine/shader evidence; compare raw
atlas planes to retail under the same exposure conditions.

### TF2-LGT-02 — probes and probe BSP — Partial (`B`/`N`)

One probe per static prop plus environment probes are written; probe BSP nodes
use a retail-compatible leaf encoding when enabled. The converter found the
engine can fall back to the KD tree, so the compiler leaves 0x06/0x07 empty.

Probe links now include baked local lights at retail weight 255.

The light-class fixture also captured five third-person player views at the
dark control and at each lit room's probe position. Centre luminance rose from
1.41 in the dark room to 25.08–26.84 in the lit rooms, so character lighting is
visible natively at multiple probe positions. The BSP accelerator was still
empty in both states, so this is not an accelerator A/B comparison.

A second 24 November fixture places two light environments 5,000 units apart.
Environment 1 applies inside a `light_environment_volume`; its local baked
point light produces probe link 3 only at the stage, while environment 0's
point produces link 2 only in gameplay. Native third-person centre RGB was
`(161.44, 46.88, 122.46)` in gameplay and `(130.55, 57.15, 153.65)` at the
stage (`ΔR -30.89, ΔG +10.27, ΔB +31.19`), so per-environment probe lighting is
visibly isolated. A tracked compiler regression checks both environments'
world-light records, shadow-mesh ranges and probe links. Evidence:
`.local/respawn/tf2-env-volume-20261124/native-run/native-evidence.json`.

**Missing:** adaptive retail probe placement, an accelerator on/off comparison,
full menu-stage scene parity, and visual parity for characters in
third/first person.

**Acceptance:** matched character captures at several positions, with and
without the BSP accelerator; compare probe counts/weights to a retail sample.

### TF2-LGT-03 — cubemaps and CMA — Partial (`B`/`N`)

Cubemap lumps, HDR VTF generation, face orientation and material path fixes are
implemented. The path bug that wrote `materials/maps//cubemaps.hdr.vtf` is fixed.
Nearest-centre mesh assignment matches retail on only 30–100% of meshes.

Local r1delta/bspdown research
(`.local/respawn/r1delta-src/engine/r2port/bspdown/README.txt`, rule 13b)
treats `CMA` as a per-cubemap exposure multiplier when converting R2 cubemaps for
R1: it applies `clamp(gain * CMA, min_scale, scale)` with map-dependent ratios,
and six sampled maps have CMA values 0.86–8.89. This is R1 shader/loader evidence
from a different runtime, not proof of the TF2 shader's use of the resource. No
TF2 native A/B isolates CMA, so the compiler's placeholder 5.0 near menu anchors
and 1.0 elsewhere is unchanged. `CRC` remains written as 0.

Brightness parity is also still open: the `_ambientscale` default 0.04 was
calibrated on Coliseum, the dim retail outlier. Decoded SKY A medians are 0.014
(Coliseum), 0.054 (Relic), 0.082 (Angel City), 0.169 (Colony) and 0.176 (Glitch),
while released ports sit at 0.013–0.030. No default change is made without a
controlled in-game A/B.

**Missing:** CMA meaning in TF2 itself (the local multiplier reading is `S`-level
for this target), `CRC` semantics (written 0), a mesh-selection rule matching a
measured retail majority, and brightness/fill agreement across retail maps.

**Acceptance:** decode CMA/CRC against pinned TF2 engine code or shader behavior;
build a rule that matches a measured majority of retail assignments; run a
controlled `_ambientscale` A/B; capture native reflections.

### TF2-LGT-04 — CSM and alpha shadows — Partial (`B`/`N`)

CSM AABB trees, object references, `SHADOW_ENVIRONMENTS`, opaque shadow meshes and
alpha-shadow meshes are emitted. Sky meshes are excluded from the shadow streams.
Light-space node orientation was fitted exactly from retail object centres.

Two 24 November fixtures add structural regressions. The paired opaque/alpha
fixture emits one opaque mesh (material sort `-1`) and one alpha mesh (material
sort `2`), with the compile-only sky shell absent from both vertex streams. The
environment-volume fixture checks two `SHADOW_ENVIRONMENTS` ranges and confirms
the stage owns no gameplay shadow meshes. The native runs used compiler
`6daec3b2…`; their BSP hashes are
`e082000126dc63f165d853d17caf50f856493bd992fe567cf9b54a7185eafeca` (alpha) and
`42705e90def4e3c1eb7acba69fd2adeeb43f2267bc8ee28dc88ee17d5174eec0` (environments),
with harness reports `2bbb793fdc6a5a7d7c28a09d1ecb205782f22d770ee5889a26ecfcf8515f7b81`
and `54d8b942e595588e733df59fcea1d9370f26a3a12228b770331f64dea696e224`.
The one-hash compiler recompiled both fixtures with identical lump payloads;
whole-BSP hashes vary only with the header timestamp. The native alpha fixture
loaded and shut down cleanly, but its top-down deltas against the no-caster
control are near the capture noise floor, so runtime alpha-shadow visibility is
not claimed. Evidence:
`.local/respawn/tf2-alpha-shadow-20261124/native-run/native-evidence.json` and
`.local/respawn/tf2-env-volume-20261124/native-run/native-evidence.json`.

**Missing:** a runtime capture that resolves opaque versus alpha shadow contrast,
cascade resolution/behavior for small holes, and menu/gameplay shadow isolation
beyond the structural environment ranges.

**Acceptance:** paired native captures with a visible, material-matched shadow
delta; cascade comparisons against retail; record the Northstar version and
engine hash.
