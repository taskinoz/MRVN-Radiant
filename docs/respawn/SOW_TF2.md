# Scope of work: Titanfall 2 / Northstar

> **Closed 27 November 2026.** This scope of work is no longer maintained. Open
> work is tracked in [GOALS.md](GOALS.md); this file is kept as the evidence
> record behind those items.

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

Compiler provenance received a scoped `E` pass on 26 November 2026: a fresh
build from clean tracked `bd10231` source with VS2022 CMake `3.31.6-msvc6` and
MSVC `14.44.35207` reproduced `b0a80649…` byte-for-byte after normalizing the
six non-content PE timestamp bytes. Evidence:
`.local/respawn/clean-checkout-hash-verify-20261126/RESULT.md`. This confirms the
compiler identity only; it does not promote any runtime or visual gate.

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

Baseline evidence:
[RESPAWN_MAP_SUPPORT_AUDIT.md](RESPAWN_MAP_SUPPORT_AUDIT.md),
[RESPAWN_TF2_LUMPS.md](RESPAWN_TF2_LUMPS.md),
[RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md),
[RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md),
[RESPAWN_GAME_LUMP.md](RESPAWN_GAME_LUMP.md),
[RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md),
[RESPAWN_NORTHSTAR_TEST.md](RESPAWN_NORTHSTAR_TEST.md) and
[RESPAWN_MP_BOX.md](RESPAWN_MP_BOX.md).

### Integrated compiler replay

The closure branch (`25a227a`) records a bounded native replay of
`mp_mrvn_tf2light_stock` built with the integrated compiler
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110`.
The ARES-owned `R2OneHashReplay` profile was seeded from the pinned
`R2MapHarness` `Northstar.dll`
(`ff9bd1dc1606a2f3e8109d52b3d9a491b07869fc04cf600aabcdf47fb2c96547`) and core
mods; the source DLL was unchanged and the clone was removed. The replay BSP is
`a7e2e38eb1d7e4967753c69d6e80096d2068e73e036b491bf49711923cd949bc` with `[]`
lump payload differences. The session completed level load and shutdown,
repeated both floor traces at z=0.03125, produced four nonblank window captures,
and reported no script errors or crash dumps. Report SHA-256
`5d6f5f3e4be56dd76320de49cce9fdf31e8cf71ac30f89f08b7813c891af87d7`; evidence
relative to the closure checkout:
`.local/respawn/tf2-lighting-onehash-native-20261124/native-evidence.json`
(SHA-256
`ec5f6b2aa59a81e1de2bdb83cd9fb38c7fd0a5a2397bb9b250152dff0455cdc0`). This is a
load/trace/window-fallback capture replay only, with no image comparison. The
`R2Northstar` `1.31.16` label, broader visual parity and the main profile still
need their own runs.

## Map support

### TF2-MAP-01 — v37 writer coverage vs. retail corpus — Partial (`B`)

The writer covers all 81 surveyed named lumps when seven empty retail lumps are
counted; 74 explicit payload write paths cover 74 fixed-record schemas in a
different count. The eight-map corpus passes structural validation. Empty lumps
(`LEAF_WATER_DATA`, `WORLD_LIGHT_PARENT_INFOS`, `PHYSICS_LEVEL`,
`PHYSICS_TRIANGLES`, `VERTEX_RESERVED_5-7`) are intentionally not emitted.

On 25 November, six additional retail maps passed BSP inventory and selected
record validation, bringing the checked sample to 14 maps. All seven omitted
lumps were empty in the six new maps, including `LEAF_WATER_DATA` in Black
Water Canal and Drydock. The budget auditor matched the installed
`58eb1a1b…` engine profile on every sample.

| Added retail sample | Padded world indices | Material sorts | Static props |
| --- | ---: | ---: | ---: |
| `mp_coliseum_column` | 32,760 | 29 | 12 |
| `mp_lf_meadow` | 934,602 | 128 | 2,909 |
| `mp_complex3` | 1,415,442 | 341 | 10,945 |
| `mp_black_water_canal` | 1,897,926 | 385 | 19,349 |
| `mp_drydock` | 2,136,516 | 564 | 9,088 |
| `mp_wargames` | 863,514 | 620 | 8,933 |

Drydock had the highest all-visible world-index estimate at 67.9% of the
audited 3,145,728-index capacity. The estimate covers serialized world meshes.
Native draw batches, prop rendering and gameplay still require runtime checks.

Evidence is under `.local/respawn/tf2-retail-budget-20261125/<map>/`.
`extraction.json` pins the installed English client VPK directory, tool and
all extracted payloads by SHA-256. Extraction used the default sanity checks.
`inventory.json`, `records.json` and `budget.json` come from
`inspect_bsp.py --hash`, `validate_records.py` and `audit_tf2_budget.py --engine`
respectively, using the validators from `ccaf2de`.

**Installed-map audit (`E`/`B`/`N`, 25 November):** the all-games audit checked
80 TF2 BSP inventories (66 unique hashes, 74 record sets) and 37 Ion BSP
inventories (37 unique hashes, 37 record sets). Eleven map names exceed the
conservative all-visible padded-index estimate in each profile; Ion adds no new
budget category. Other TF2 flags are local validation artifacts: two loose
`MRVN.RoundtripTest` copies with empty external lumps, zero-length
`R2SurfFixValidation` duplicates of `mp_source_surf_me.bsp`, and two custom BSPs
with vertex-normal/cell-access record issues. Stock VPK copies of the same
names parsed cleanly. The representative flagged map `mp_eden` loaded in the
ARES Northstar harness with `loaded=true`, `finished=true`, `errors=[]`,
`script_errors=[]`, `crash_dumps=[]` and 5/5 checks passed; the harness reports
`draw_batches` as null, so this does not measure real batches, visibility or
brightness. The Ion profile was not natively loaded. Report:
`.local/respawn/all-maps-audit-20261125/REPORT.md` (SHA-256
`a0c58f31a7e910cd2147db1fff2c93f65f5bce5ecddad1eb9d620685ef62d7f4`).

**Remaining acceptance:** resolve approximate record fields against the
retail samples and pinned engine. Compile a production-scale authored map
with dense props and large visible areas, compare the same structural and
budget reports, and measure draw batches and visibility in Northstar.

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

**Targeted and styled lights (`B`/`N`, 26 November):** `light_spot` now honours a
Source-style `"target"`: the spot normal points at the named entity's origin and
overrides `angles`/`pitch`; a missing or coincident target warns and falls back
to the angles. The shared writer serves v29 and v37. A raw read of
`WORLD_LIGHTS` in the six 25 November retail samples found `style` = 0 and
`parent` = 0 in all 3,123 records, so TF2 has no observed record form for light
styles. Authored `style`/`_style` values now warn and bake as constant lights
instead of being dropped silently. The tracked `tf2-targeted-spot` regression
checks the aimed normal `(0.7071, 0, -0.7071)`, the missing-target fallback
`(0, 0, -1)`, style 0 and both warnings. It passed in the full compiler suite with
`remap.exe` SHA-256
`73e7e0faae4a705ab58204c57814caf943e99c037631926b338303cd4b8b2991`, alongside 324
Python unit tests. This build is not the one-hash integration build.

Native check (`N`, same compiler hash): `mp_mrvn_tf2_targetspot` ran in the ARES
harness on the `R2OneHashReplay` profile (`Northstar.dll` `ff9bd1dc…`), with
engine screenshots and the HUD hidden. It loaded and finished with no script
errors or crash dumps. The only error was the black frame from the
intentionally unlit room. Top-down luminance centroids put the targeted realtime
and targeted baked pools at 0.712 and 0.704 of the image width (+x, toward the
target), against 0.282 for the untargeted control (-x, under the light). Oblique
views agree: 0.719 and 0.723 against 0.240. Evidence:
`.local/respawn/tf2-targeted-spot-native-20261126/RESULT.md`. The TF1/TFO runtime
effect is still unverified.

Light-style runtime probe (`N`, 27 November): a copy of the same BSP had
`WORLD_LIGHTS.style` set to 2 (Source's slow pulse) on its three spot records, a
3-byte change inside lump 0x36. Ten engine-screenshot frames over about 20 s
were constant and matched the style-0 baseline: targeted realtime 6.994–6.996
(baseline 6.994), targeted baked 8.070–8.072 (8.071), control 7.941 (7.941), with
unchanged centroids. `engine.dll` still contains `r_lightstyle`/`lightstyles`
strings, but the record field alone has no visible effect at this pin. That
supports baking authored styles as constant lights. Other style numbers,
server-set style strings and entity I/O are untested.

Realtime slot margin (`B`, 27 November): the shared bake now gives a texel a
realtime light's slot when the light reaches anywhere within ±1 texel of the
texel centre, not only at the centre. The change fixes stepped spot edges that
were confirmed natively in TF1 (see TF1-LGT-01). On v37 it only widens the slot
plane; Northstar already rendered smooth edges before. The full compiler suite
passed with `remap.exe` `fff36c8f…`. Native recapture (`N`, same hash, same
harness and profile): `native-run-margin1/` loaded and finished. Its only error
is the intentional black spawn-room frame. Centroids are within 0.0004 of the
earlier run. The realtime rooms gain faint light on a few hundred edge pixels,
the baked rooms are pixel-identical, and no artefacts are visible.

**Missing:** switchable light behaviour (entity I/O toggles, or server-set style
strings, if any engine path exists), v1/v2 record emission, full shader-level
channel semantics, a controlled native RTL/SKY A/B under the one-hash compiler,
and fill-level agreement across retail maps. The `Sky`/`RTL` and CMA A/Bs below
show bounded native response under the one-hash compiler, not shader-level
channel decoding or retail brightness parity.

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
from a different runtime, not proof of the TF2 shader's use of the resource. A
bounded TF2 native CMA-only A/B is recorded below (response evidence, not shader
decode), so the compiler's placeholder 5.0 near menu anchors and 1.0 elsewhere is
unchanged. `CRC` remains written as 0.

On 26 November a bounded controlled `_ambientscale` A/B was recorded under the
one-hash compiler (`b0a80649…`). Two open-top fixture maps differ only by a
worldspawn override (`0.04` vs `0.08`); both loaded in the isolated
`R2MapHarness` profile with two matched captures and `errors: []`. Centre
luminance rose by 2.83 and 2.86 at the two cameras. The compiler default remains
`0.04`. Evidence:
`.local/respawn/tf2-brightness-ab-20261126/RESULT.md` (local, uncommitted). This
closes only the map-level A/B observation; it does **not** close retail fill
agreement, CMA/CRC semantics, reflection captures, or full brightness parity.

A bounded raw SKY A plane comparison was also recorded on 26 November for six
pinned retail extracts and the two A/B fixtures. Using the documented RGBM byte
decode and nonzero-texel luminance median, retail spans `0.013271`
(`mp_coliseum_column`) to `0.276856` (`mp_wargames`); authored `0.04` is
`0.040074` and `0.08` is `0.080147`. This reproduces the earlier Coliseum
`0.014` observation and shows the authored default is within the retail span,
but the 20× retail spread prevents any single-default parity claim. All reports
have `issues: []` and `layout_matches: true`, while `engine_decode_verified` is
`false`: shader-level meaning and matched-exposure rendering remain unproved.
Evidence: `.local/respawn/tf2-sky-plane-compare-20261126/RESULT.md`.

A native SKY-A plane-only A/B was also recorded: the two fixture BSPs differ in
47,110 bytes, all inside lump 98, with only RGB doubled in the high variant.
Under the same compiler and pinned `R2MapHarness` runtime, two matched cameras
showed mean frame luminance rising from ~153.8 to ~162.8 (mean |RGB Δ| ~9.4;
~99.7% of pixels changed) with `errors: []`. The original captures were desktop
window grabs with UI cleared; engine-framebuffer repeats with `hide_hud` are
recorded below. No retail exposure match was attempted; this is plane-response
evidence only, not shader-channel, CMA/CRC, reflection or parity proof.
Evidence: `.local/respawn/tf2-sky-plane-native-ab-20261126/RESULT.md`.

Brightness parity is also still open: the `_ambientscale` default 0.04 was
calibrated on Coliseum, the dim retail outlier. Decoded SKY A medians are 0.014
(Coliseum), 0.054 (Relic), 0.082 (Angel City), 0.169 (Colony) and 0.176 (Glitch),
while released ports sit at 0.013–0.030. The controlled in-game A/B above
confirms a bounded response but does not justify changing the default.

A bounded native CMA-only A/B was also recorded on 26 November: changing only
the four-byte CMA float inside the one-hash fixture's cubemap VTF (0.01 vs 4.0)
changed two matched window captures (~2.6 lower mean luminance at 4.0, 20–22%
of pixels changed) with `errors: []`. The direction is not consistent with a
simple brightness multiplier, so CMA semantics remain unresolved; `CRC` was not
varied. A separate bounded session captured all six cubemap source views at the
fixture origin with engine screenshots, pinned `Northstar.dll` and RUI hidden;
this is source-view capture only, not an end-to-end captured-cubemap parity
claim. Both plane-response and CMA A/Bs were then repeated with ARES engine
screenshots and `cl_drawhud 0` under the pinned `R2OneHashReplay` profile, with
all four reports successful; this removes the desktop-grab limitation for those
bounded comparisons but adds no shader or retail-parity claim. Evidence:
`.local/respawn/tf2-engine-ab-checks-20261126/RESULT.md`.

**Missing:** CMA meaning in TF2 itself (the local multiplier reading is `S`-level
for this target), `CRC` semantics (written 0), a mesh-selection rule matching a
measured retail majority, and brightness/fill agreement across retail maps.

**Acceptance:** decode CMA/CRC against pinned TF2 engine code or shader behavior;
build a rule that matches a measured majority of retail assignments; capture
exposure-matched native reflections. The bounded `_ambientscale` A/B is recorded
but does not close fill parity.

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
