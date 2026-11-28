# MRVN-Radiant goal list: retail-compatible, retail-complete maps

Started 27 November 2026. This replaces the scope-of-work documents
(`SOW_*.md`), which are closed and kept as the evidence record behind each item
here.

**The goal:** MRVN-Radiant can author, compile, light, package and ship a map
that loads and plays in each target runtime like a retail map. "Compatible" means
the runtime accepts the map and nothing renders, collides or plays wrongly.
"Complete" means the map can use every feature retail maps of that game use.

| Release | Target | Runtime pin |
| --- | --- | --- |
| 1.0 | Titanfall 1 | R1Delta `app-3.0.5` (acceptance benchmark) |
| 1.0 | Titanfall Online | TFORevive Core `135` (secondary; local Sentry patch kept for testing) |
| 1.0 | Titanfall 2 | Northstar (`R2OneHashReplay` / `R2MapHarness` profiles; pin by `Northstar.dll` hash) |
| 1.0 | Apex Legends Season 3 | R5Reloaded SDK 2.3, `R5pc_r5launch_N1094_CL456479` |
| 1.0 (sub-items) | Apex Legends Seasons 0–2 | Installed under `F:/Games/Apex Detours/Apex s0`–`s2`; no mod loader, scripts edited by hand |
| 1.1 | Apex Legends via R5Flowstate | `R5pc_r5-301_J28_CL11570498_FSv30_1`, game version `v3.0.1.28`, SDK `R5FlowstateSDK005` |

Navigation was previously deferred to "version 2" in
[RESPAWN_COMPATIBILITY.md](RESPAWN_COMPATIBILITY.md). It is in scope here,
because a retail-complete map needs AI and titan navigation.

## How to use this list

- Each item is one thing that is missing, wrong or unproven. Tags:
  - `[missing]`: not implemented.
  - `[wrong]`: implemented, but writes a value known or suspected to differ from
    retail.
  - `[unproven]`: implemented, but no in-game check yet.
  - `[research]`: the format or engine behaviour is not decoded yet.
- Tick an item only after an in-game check in the named runtime with a pinned
  compiler hash. Record the evidence path under `.local/respawn/` next to the
  tick. A written lump, a passing parser or one load report is not enough.
- Keep TF1 and TFO results separate even when the BSP is byte-identical. Never
  carry an item from TF2 to Apex because the lump numbers match.
- Retain failing runs as evidence.

---

## 0. Shared work (all targets)

### Build, process and release

- [x] **ALL-01 Commit the outstanding work** `[missing]`: the slot-margin
  fix, targeted spots for TF2 and Apex, the `tf2-targeted-spot` regression and
  the docs are uncommitted on `main`.
  - Done 27 November 2026: committed. The Quake-port and TF1→TF2 asset tools
    the first audit called untracked are already tracked.
- [ ] **ALL-02 One compiler build, all runtimes** `[unproven]`: no single
  compiler hash has passed native runs in all four runtimes. The newest native
  evidence is spread over `b0a80649…`, `73e7e0fa…`, `fff36c8f…` and `4d8f394d…`.
  Done when one hash passes the native fixture set for every target.
- [x] **ALL-03 Regression for the realtime slot margin** `[missing]`: a
  tracked fixture that fails if realtime light slots lose the ±1 texel margin.
  The margin fixes stepped spot edges in TF1, TFO and Apex.
  - Done 27 November 2026: `tools/respawn/lightbake_tests.cpp` lights a
    30-unit disc and checks the texels one and two steps outside the cone.
    Building with centre-only scoring fails it. The Apex writer's own copy of
    the slot code (`apex_legends_lightmaps.cpp`) is not covered by this test.
- [ ] **ALL-04 Image comparison harness** `[missing]`: every lighting gate needs
  matched-camera, exposure-matched captures against a retail control. Existing
  checks are luminance centroids and load/trace events only.
- [ ] **ALL-05 Editor-to-game workflow** `[missing]`: one editor action per
  target profile that compiles, bakes, packages and stages the map, with clear
  errors and a reproducible manifest. Today this is a chain of scripts under
  `tools/respawn`.

### Editor and entity definitions

- [ ] **ALL-06 Entity definitions match retail** `[missing]`: the gamepacks
  define 23 classes (TitanfallOnline), 23 (Titanfall2) and 2 (ApexLegends). The
  ENT partitions of six retail TF2 maps alone use 70 distinct classes, before
  counting the BSP entity lump. Each game needs every retail class with its
  keys, spawnflags and partition (`env`, `fx`, `script`, `snd`, `spawn`).
  - Progress 27 November 2026: each gamepack now has a generated
    `retail_entities.ent` covering every retail class the hand-written
    `entities.ent` lacks: 45 (TitanfallOnline, from TF1), 71 (Titanfall2) and
    76 (ApexLegends). It lists each retail key, with a default only where most
    retail entities share the value.
  - Still open: key meanings, spawnflags and editor models. Radiant loading
    them is not yet checked (HV-03).
- [ ] **ALL-07 Separate TF1 gamepack** `[missing]`: TF1 and TFO share the
  `TitanfallOnline` gamepack. R1Delta requires things TFO doesn't, such as
  `info_intermission`, the ±16384 envelope and per-map model VPKs.
- [ ] **ALL-08 Asset browsers** `[missing]`: browse and place retail materials
  and models from VPK (TF1/TFO), RPak v7 (TF2) and RPak v8 (Apex) without
  extracting them by hand. Apex props need RSX Cast exports converted with
  `cast_to_obj.py` today.
- [x] **ALL-12 Entity partitions match retail** `[wrong]`: the writers routed
  classes to the BSP lump and `.ent` files by hand-written prefix rules. TF2
  used TF1's rules, putting 43 of 90 retail classes in the wrong place
  (lights, triggers, game-mode markers). The two Apex rule lists disagreed with
  each other and with retail on 20 of 50 S3 classes.
  - Done 27 November 2026: `tools/respawn/entity_corpus.py` surveys retail maps.
    Every class sits in exactly one partition per game (5 TF1, 14 TF2 and 6 Apex
    maps). The generated `tools/remap/source/respawn/entity_partitions.h` now
    routes all 231 known classes. The old rules remain only for classes retail
    maps never use.
  - Apex inline `*coll` collision now follows retail: triggers and volumes
    only, not `func_brush`.
  - Checked in game: the TF2 targeted-spot map (lights now in `_env.ent`)
    renders identically in Northstar (`native-run-partitions/`), and the Apex
    map loads and spawns in the S3 client (`apex-cube-run/`).

### Lighting baker (shared `lightbake.h` and the Apex copy)

- [x] **ALL-09 Light styles** `[research]`: authored `style` bakes as a
  constant light with a warning on TF1/TF2. TF2 ignores the record field at
  runtime. Apex still copies `style` into the record without a retail check.
  Decide per game whether any switchable or flickering light path exists
  (entity I/O, server-set style strings), and implement it or document that it
  doesn't exist.
  - Done 27 November 2026: no game has a style path in the record. All 3,123
    TF2 records and all 31,262 Apex S0–S3 records have style 0. A style-2
    record changed nothing in Northstar or R1Delta (TF1-15). All three writers
    now bake styled lights as constant lights with a warning. Script-driven
    light switching is a separate gameplay feature (TF2-14).
- [ ] **ALL-10 Default fill level** `[wrong]`: the `_ambientscale` default 0.04
  was calibrated on Coliseum, the dimmest retail map. Decoded retail SKY A
  medians span 0.013–0.277, so no single default matches retail. Choose a
  per-map calibration rule backed by captures.
- [ ] **ALL-11 Bake quality** `[missing]`: TF1, TFO and TF2 have one diffuse
  bounce and chart filtering. Apex has no bounce. In Apex, props and patches
  don't occlude baked light, and the 32-ray sky term leaves jagged bands on some
  walls.
- [x] **ALL-13 Heap address in the Apex sky-ambient light** `[wrong]`: in some
  Apex builds the `emit_skyambient` world light's `normal.x/.y` (lump 0x36,
  +0x18) holds a 64-bit heap address that changes run to run, where it should
  be zero. Seen in the `apex-alpha-shadow` and `apex-probe-placement`
  regression outputs back to 27 November 2026, so it predates the APEX-16
  work. **Fixed 28 November 2026.** There was no stale pointer: the normal was
  never written. `WorldLight_t ambient = {}` does not zero `Vector3` members,
  because `BasicVector3()` (`libs/generic/vector.h`) is user-provided and empty,
  so they keep stack garbage. Every remap lump record that was declared with
  `T x{}` / `= {}` now uses `ZeroedRecord<T>()` (`remap.h`). A before/after
  regression compare changes only Apex lump 0x36; every other lump in every
  game is byte-identical, and Apex output is now identical run to run. The
  `apex-probe-placement` fixture asserts that sky-ambient normals are zero.
  Maps rebuilt with the fix load and render in R5Reloaded (the APEX-18 run,
  28 November 2026).

---

## 1. Titanfall 1 — R1Delta (release 1.0)

Working today: authored v29 maps load and finish; there are paired R1Delta/TFO
replays for lighting, vertex formats, props and masks; Hardpoint captures and
scores; sun, baked, realtime point and aimed spot lights render with smooth
edges.

### Map format

- [ ] **TF1-01 `PHYSICS_TRIANGLES` not emitted** `[missing]`: the only populated
  retail lump the writer omits. The engine rebuilds the hulls at load. Either
  emit the decoded hulls (`tools/respawn/physics_triangles.py`) and measure load
  time, or document the cold-load cost.
- [ ] **TF1-02 Field semantics for unvalidated records** `[unproven]`: 9 of 70
  written lump types have no schema in `validate_records.py`, and semantic
  parity is unverified for every row of
  [RESPAWN_TF1_LUMP_CHECKLIST.md](RESPAWN_TF1_LUMP_CHECKLIST.md).
- [ ] **TF1-03 Unused vertex formats** `[unproven]`: `VERTEX_UNLIT_TS` and
  `VERTEX_BLINN_PHONG` have writer paths but no fixture.
- [ ] **TF1-04 Corpus coverage** `[unproven]`: one generated fixture for every
  lump the retail corpus populates, each validated and loaded.

### Geometry and visibility

- [ ] **TF1-05 Visibility on large maps** `[unproven]`: cells and portals are
  generated, but native culling, water portals and opt-in portal geometry have
  no large-map proof.
- [ ] **TF1-06 3D skybox and sky camera** `[unproven]`: no TF1 native check of
  a `sky_camera` scene.

### Collision and physics

- [ ] **TF1-07 Physics launch breadth** `[unproven]`: six R1Delta launches of
  the props fixture are stable. Still needed: curved, stacked and thrown
  variants with at least six launches each, plus a retail control in the same
  harness.
- [ ] **TF1-08 `PHYSICS_COLLIDE` contents** `[unproven]`: model/solid lengths,
  material tables and fluid keydata with nonempty brush, water and submodel
  fixtures.
- [ ] **TF1-09 Patch collision breadth** `[unproven]`: backfaces, transformed
  patch entities, all orientations, moving props, projectile masks and titan
  hulls. Four dome hull cases are unresolved.
- [ ] **TF1-10 `TRICOLL_BEVEL_INDICES` selection** `[wrong]`: the current rule is
  a functional superset, not retail's selection. Decode the retail rule or
  record the decision to keep the functional one.
- [ ] **TF1-11 Water** `[unproven]`: `LEAF_WATER_DATA` cell assignment against
  real visibility cells (single-cell maps especially), sloped and multiple
  volumes, submerged props and buoyancy breadth.
- [ ] **TF1-12 R1Delta underwater black band** `[research]`: classify it as a
  compiler or runtime defect. Retail controls show a similar horizon artefact.

### Lighting, shadows and reflections

- [ ] **TF1-13 RTL channels** `[research]`: only the slot layout is decoded.
  Decode the remaining channels against shader behaviour.
- [ ] **TF1-14 Light brightness equivalence** `[unproven]`: point, spot, sun and
  `_pbr_falloff` lights against retail captures.
- [x] **TF1-15 Light style runtime probe** `[missing]`: never run on TF1 (TF2
  showed no effect). Feeds ALL-09.
  - Done 27 November 2026: style 2 on all three spot records; 12 frames over
    about 27 s in R1Delta 3.0.5 matched the style-0 baseline within ±3% (HUD
    text only). Contact sheet `tf1-style2-contact.png` (HV-02).
- [ ] **TF1-16 SKY A/B meaning** `[research]`: no shader validation of the
  sky planes.
- [ ] **TF1-17 Projected shadows** `[unproven]`: controlled image comparison of
  opaque and alpha-tested shadow casters. Only a hand-stripped control has
  shown the shadow difference, never the compiler's opt-out.
- [ ] **TF1-18 Probes** `[unproven]`: character lighting across hulls and
  environments; no TF1 v29 probe fixture yet.
- [ ] **TF1-19 Cubemaps** `[unproven]`: cubemap selection per material sort,
  path verification and reflection equivalence against Angel City and Colony.
  - Progress 27 November 2026:
    - The v29 writer now honours `env_cubemap`; before, it always wrote one
      cubemap at the spawns.
    - Cubemaps now include realtime point and spot lights.
    - Checked in R1Delta with the stock `models/dev/envballs.mdl` (ARES
      `r1_harness.py` `"cubemap_balls": true`), against retail `mp_angel_city`:
      `tf1-envballs-contact.png`.
    - The test rooms are dark, so the reflections are subtle.

### Materials, models and packaging

- [ ] **TF1-20 Dependency closure** `[missing]`: complete closure for custom
  materials, models and shaders. The current audit covers direct dependencies
  only.
- [ ] **TF1-21 Clean-deployment load** `[unproven]`: an R1Delta addon with
  custom materials, models and shaders loads from a clean install. No
  loose-only shader may pass. The Water shaders must be in a VPK.
- [ ] **TF1-22 Static props on a real package** `[unproven]`: the `sprp v12`
  fix has not been checked on a nontrivial packaged map.

### Entities, modes and gameplay

- [ ] **TF1-23 All retail modes** `[unproven]`: tdm, ctf, lts, cp and exfil only
  start; Hardpoint is the only mode played to capture and score. Needed:
  contested and recapture objectives, respawns, evac/epilogue flow, dropship
  and titan drops, plus every other mode retail maps ship.
- [ ] **TF1-24 Human multiplayer session** `[missing]`: sustained play with
  several human players.
- [ ] **TF1-25 Retail gameplay entities** `[research]`: inventory the classes
  retail maps use (ziplines, turrets, spawn types, hints, triggers) and check
  each one in game.

### Navigation and AI

- [ ] **TF1-26 AI graph generation** `[missing]`: AIN graphs are exported by the
  engine itself, behind launch flags. The compiler can't produce them, and
  stamping a new CRC on an old graph is not regeneration.
- [ ] **TF1-27 AI breadth** `[unproven]`: multiple hulls and routes, moving
  obstacles, combat, spectres and titans. Only grunt and atlas routes are
  recorded.

---

## 2. Titanfall Online — TFORevive Core 135 (release 1.0)

Uses the same v29 writer as TF1. Every TF1 item above also needs its own TFO
check; only the TFO-specific gaps are listed here.

- [ ] **TFO-01 Unmodified Core 135** `[unproven]`: Hardpoint needs temporary
  dialogue and sound fixes, so there is no claim for unmodified Core 135.
- [ ] **TFO-02 Physics launch variance** `[research]`: a bad TFO launch sinks
  every crate. Find the cause, then run six launches per variant.
- [ ] **TFO-03 Water and crate drops** `[unproven]`: these currently work only
  in some launches.
- [ ] **TFO-04 Projected shadows** `[unproven]`: same gate as TF1-17. TFO has
  the stronger shadow evidence but no controlled image comparison.
- [ ] **TFO-05 Mod package from a clean install** `[unproven]`: the TFO mod
  package with custom assets, using the recorded content-mod set.
- [ ] **TFO-06 Stock `mp_colony` ENT sidecars** `[research]`: the declared
  partition files were not found in the scanned loose tree. The map loads, but
  its entities, triggers and navigation weren't checked.
- Sentry: the local DLL patch stays in place for testing. It isn't a goal.

---

## 3. Titanfall 2 — Northstar (release 1.0)

Working today: v37 maps load and play. Baked, realtime, spot and `_pbr_falloff`
lights render, one light class per room. Probes with per-environment isolation,
CSM and alpha shadow meshes, cubemaps, and an opt-in 1,022-cell portal fixture
also work.

### Map format

- [ ] **TF2-01 Approximate record fields** `[wrong]`: resolve the fields still
  approximated against the 14 sampled retail maps and the pinned engine.
- [x] **TF2-02 World light v1/v2 records** `[missing]`: the compiler reads them
  but doesn't emit them.
  - Closed 27 November 2026, not needed: all 14 sampled retail TF2 maps use
    `WORLD_LIGHTS` version 3, which the compiler writes.
- [ ] **TF2-03 Production-scale map** `[unproven]`: a dense authored map near
  retail budgets (Drydock reaches 67.9% of the 3,145,728-index capacity), with
  real draw batches and visibility measured in Northstar.
- [ ] **TF2-04 Main Northstar profile** `[unproven]`: retest on the main
  `R2Northstar` profile (labelled `1.31.16`). Evidence so far is from the
  `1.31.13` harness profile.

### Geometry and visibility

- [ ] **TF2-05 Culling parity** `[unproven]`: full culling on a large authored
  map, plus water portals, global environment cells and leaks.
- [ ] **TF2-06 Runtime area portals** `[missing]`: authored area portals don't
  open or close at runtime.
- [ ] **TF2-07 Default visibility** `[wrong]`: without `_viewportals "1"` the
  map is a single cell. Retail maps are multi-cell, so the opt-in path should
  become the proven default.
  - Progress 27 November 2026: with `_viewportals`, world faces are now split
    per cell by default, giving one cell per mesh (the `portal-budget`
    fixture went from 64 to 1.00 cells per mesh). Retail TF2 averages 1.31
    and TF1 Angel City 1.52.
    - Checked in Northstar and R1Delta with the three-room fixture
      (`.local/respawn/apex-cells-20261127/tf2-cells-contact.png`,
      `tf1-cells-contact.png`).
  - Still open:
    - `_viewportals` itself is still opt-in.
    - Culling gains aren't measured (HV-04).
- [x] **TF2-31 Split meshes lose spawn entities** `[research]`: in Northstar a
  split three-room fixture (`.local/respawn/apex-cells-20261127/titanfall2-cells`)
  loads, renders and collides, but has no `_spawn.ent` entities: 0
  `info_spawnpoint_human`, against 2 in the identical unsplit build.
  - The `.ent` files, partition lump, world bounds and spawn cells are the same
    in both builds.
  - The BSPs differ in meshes, vertices, LEVEL_INFO, probes and lumps 0x1E and
    0x7F.
  - Until the cause is found, splitting stays opt-in for TF1/TF2.
  - Fixed 27 November 2026 (`git log`: "Fix lost spawns with cell-split
    meshes").
    - Cause: building the cell graph before meshing put its portal planes
      ahead of the collision planes in the plane lump.
    - A lump bisection in Northstar pinned it down: swapping in the cell graph
      plus plane lump from the unsplit build restored the spawns, while
      swapping probes, shadow meshes or visibility trees didn't.

### Collision

- [ ] **TF2-08 Bevel generation** `[wrong]`: exact retail bevel parity and the
  `TRICOLL_BEVEL_INDICES` selector. Vertex/edge adjacency is ruled out: 12,658
  of 20,067 Coliseum references have no shared vertex.
- [ ] **TF2-09 Flat-triangle tie exceptions** `[research]`: 15 triangles in six
  maps don't follow the tie rule. Explain or reproduce them.
- [ ] **TF2-10 Collision breadth** `[unproven]`: backfaces, transforms, moving
  props, and projectile and titan sweeps.
- [ ] **TF2-11 Water** `[missing]`: authored water volumes with buoyancy and
  underwater checks. `LEAF_WATER_DATA` and `PHYSICS_LEVEL` are empty in retail;
  document why.

### Lighting, shadows and reflections

- [ ] **TF2-12 RTL and SKY channel meaning** `[research]`: the planes respond in
  game, but there is no shader-level decode or retail exposure match.
- [ ] **TF2-13 Brightness parity** `[unproven]`: retail fill spans about 20×;
  see ALL-10.
- [ ] **TF2-14 Switchable lights** `[research]`: entity I/O toggles or style
  strings, if any engine path exists. Feeds ALL-09.
- [ ] **TF2-15 CMA value** `[wrong]`: the placeholder is 5.0 near menu anchors
  and 1.0 elsewhere. The in-game A/B contradicts a simple multiplier.
- [ ] **TF2-16 CRC value** `[wrong]`: always written as 0. Semantics unknown.
- [x] **TF2-17 Cubemap mesh assignment** `[wrong]`: the nearest-centre rule
  matches retail on only 30–100% of meshes. Needs a rule that matches a
  measured majority.
  - Done 27 November 2026: retail uses `envmap_volume` entities.
    - The highest-`priority` volume containing a mesh's bounds centre gives
      the cubemap; meshes outside every volume fall back to the nearest.
    - Match against seven retail TF2 maps: 80.3% (Angel City 94%, Colony 95%),
      against 29% for nearest-only.
    - Apex S3 follows the same rule: World's Edge 62.6% (nearest 17.6%),
      Firing Range 88.1%.
    - The TF2 and Apex writers apply it (volume `cubemapID`, or `target`
      naming an `env_cubemap`), checked by the `tf2-envmap-volume` regression.
  - Still open:
    - The remaining mismatches, possibly from per-face assignment before
      merging.
    - No in-game reflection check of the rule.
- [x] **TF2-18 Probe placement** `[wrong]`: one probe per static prop plus
  environment probes. Retail placement is adaptive. Compare counts and weights
  against a retail sample.
  - Closed 27 November 2026: the description was out of date.
    - Since 6 November (`afd25b4`) probes follow walkable surfaces: a 64-unit
      lattice 24 and 72 units above lit floors, median neighbour spacing 48
      against retail's 56–129 (Gravemind lighting note).
    - Weights match retail: 255 on over 99.9% of light links in Colony and
      Angel City, and on ours.
    - Light links per probe vary with light density in both (retail 0–4).
  - Remaining probe work is TF2-19 (accelerator).
- [x] **TF2-19 Probe accelerator** `[unproven]`: the probe BSP (0x06/0x07) is
  left empty and the engine falls back to the KD tree. Run an on/off
  comparison.
  - Done 28 November 2026: the description was out of date; current builds
    write the probe BSP (`EmitLightprobeBsp`).
    - A/B in Northstar: the targeted-spot map against a copy with 0x06/0x07
      emptied, third-person pilot at five spots (lit pools, dark corners,
      dark spawn).
    - Captures differ by under 0.1 grey levels
      (`.local/respawn/tf2-targeted-spot-native-20261126/probebsp-contact.png`).
    - The tree only speeds lookups up; it's kept, as retail ships it.
- [x] **TF2-20 Alpha shadow contrast** `[unproven]`: the alpha-shadow fixture
  loads, but its shadow delta is at the capture noise floor.
  - Progress 28 November 2026: the old fixture had no sky around the yard
    and no sun visible on the floor.
    - In a sky-roofed, sunlit yard
      (`.local/respawn/apex-cells-20261127/build_alpha_tf2.py`,
      `tf2-alpha-contact.png`), Northstar draws the same sun shadow for a box
      in the alpha stream as in the opaque stream (Coliseum concrete).
    - With a missing material it still casts one, because TF2's magenta
      fallback texture is opaque.
  - Done 28 November 2026: cut-out check with Angel City's
    `world/metal/chain_link_fence`
    (`build_alpha_tf2.py --fence`, level rpak aliased to `mp_angel_city`).
    - In the alpha stream the fence box casts a chain-link patterned shadow.
    - In the opaque stream the same box casts a solid one
      (`tf2-fence-contact.png`).
- [x] **TF2-21 Cascades and small holes** `[unproven]`: compare cascade
  behaviour with retail.
  - Done 28 November 2026: a sunlit yard under a roof of slabs with slits 8,
    16, 32, 64 and 128 units wide (`build_alpha_tf2.py --holes`).
    - In Northstar every slit, down to 8 units, lights a stripe on the floor,
      seen from under the roof and from about 1,000 units away
      (`.local/respawn/apex-cells-20261127/tf2-holes-contact.png`).
    - Cascade selection and resolution are the engine's. The compiler only
      supplies shadow meshes and the CSM tree, and these don't limit hole size.
- [ ] **TF2-22 Menu and gameplay isolation** `[unproven]`: full menu-stage scene
  parity beyond the structural environment ranges.

### Materials, models and packaging

- [ ] **TF2-23 Dependency closure** `[missing]`: arbitrary model, material and
  texture closure, with a `--strict` manifest check like TF1's.
- [ ] **TF2-24 Production RPak and STBSP writers** `[missing]`: `pack_vpk.py`
  is for small tests and `rpak.py` is read-only. Texture streaming (STBSP) and
  every shader pass are needed.
- [ ] **TF2-25 Unknown game-lump versions** `[research]`: decode them or reject
  them explicitly.
- [ ] **TF2-26 Clean cold load** `[unproven]`: a prop-heavy map with custom
  assets loads from a clean deployment, with missing assets recorded as
  failures. `build_northstar_test_mod.py` still records
  `ingame_tested: false`.

### Entities, modes and gameplay

- [ ] **TF2-27 All retail modes** `[unproven]`: Attrition, Bounty Hunt,
  Hardpoint, CTF, LTS, Pilots vs Pilots, Frontier Defense, Coliseum, Live Fire
  and the rest, each with spawns and objectives.
- [ ] **TF2-28 Sustained multiplayer and repeated cold loads** `[missing]`.
- [ ] **TF2-29 Retail gameplay entities** `[research]`: ziplines, titan spawns
  (`info_spawnpoint_titan`), dropship paths, minimap, loading screen and 3D
  sky, all checked in game.

### Navigation and AI

- [ ] **TF2-30 Navmesh generation** `[missing]`: there is no automatic navmesh.
  Calling in a titan without a navmesh failed in game. Frontier Defense and AI
  need navmesh files for every hull.

---

## 4. Apex Legends Season 3 — R5Reloaded (release 1.0)

Working today: the S3 backend is in the compiler. The fixture room and a
recovered `mp_box` render in the S3 client, with 14/14 native trace checks.
Per-face lightmaps, realtime spots with smooth edges and aimed targets, prop sun
shadows and trigger touch also work.

### Map format

- [ ] **APEX-01 BSP reader** `[missing]`: `LoadR5BSPFile()` is unimplemented
  (`apex_legends_bsp.cpp:49-50`), and `EmitStubs()` has no Apex definition.
- [ ] **APEX-02 Field semantics and lump versions** `[unproven]`: bounded
  validators for every lump, and an explicit failure path for unsupported
  versions.
- [ ] **APEX-03 Rendered-client replay on the current compiler** `[unproven]`:
  the 14-check fixture passes on a dedicated server under `b0a80649…`. The
  rendered-client run used an earlier binary, and the targeted-spot client run
  used `4d8f394d…`.
- [ ] **APEX-04 Retail-map audit flags** `[research]`: 31 retail inventory rows
  report "Lump range is outside the payload". They are classed as an extraction
  scope issue, not proven.

### Geometry and visibility

- [ ] **APEX-05 Multi-cell visibility** `[missing]`: `EmitCells` writes exactly
  one cell and `EmitPortals` only sky portals. Retail World's Edge has 265 cells.
  - Progress 27 November 2026: worldspawn `"_viewportals" "1"` now builds the
    TF2 cell and portal graph for Apex (the cell, cell BSP and portal records
    are byte-identical to TF2's), with one visibility root per cell.
    - A three-room fixture compiles to 19 cells, 65 portals and a sky
      aperture.
    - It renders like the single-cell build in the S3 client
      (`.local/respawn/apex-cells-20261127/cells-contact.png`).
  - Still open:
    - Culling isn't measured (APEX-06).
    - It's still opt-in.
- [ ] **APEX-06 Authored portal graphs and culling** `[missing]`: measure
  culling on a large multi-cell map.
  - Progress 27 November 2026: world meshes now split along the cells, so
    culling can work at all.
    - Before, merged meshes spanned every cell.
    - Retail S3 puts 92–99% of meshes in a single cell (World's Edge 1.12
      cells per mesh).
    - With `_viewportals` the writer clips faces down the cell BSP; the
      fixture is now 1.00 cells per mesh and renders correctly.
  - Still open: measuring culling in game. `cl_updatevisibility 0` freezes
    nothing visible in the S3 client, so this needs a draw-call capture
    (see HV-04).
- [ ] **APEX-07 BVH field parity** `[unproven]`: the tree encoding has the
  retail shape, but exact field parity isn't checked.

### Collision

- [x] **APEX-08 Brush-entity collision** `[missing]`: a general brush-submodel
  collision emitter. The trigger `*coll` path is a special case.
  - Done 27 November 2026:
    - `func_brush` is written to `_script.ent` without `*coll`, as in retail,
      and collides through its BSP model.
    - `apex_native_regression.py` gained side, top and hull traces and a
      bounds check: 18/18 pass on a fresh S3 dedicated server.
- [ ] **APEX-09 Movers** `[missing]`: `func_brush`, doors, platforms and
  rotating brushes.
  - Progress 27 November 2026:
    - Retail S3 has no brush doors: doors are `prop_door` models, and
      `func_brush` entities named `train_brush` are moved by script.
    - Moving a compiled `func_brush` with `SetOrigin` moves its collision with
      it (traces checked).
  - Still open: `prop_door` and `script_mover` setups.
- [ ] **APEX-10 Collision breadth** `[unproven]`: broad authored geometry,
  projectile traces, moving props and every contents value.
- [ ] **APEX-11 Water** `[missing]`.

### Lighting, shadows and reflections

- [ ] **APEX-12 Point and spot baking** `[unproven]`: the baker follows VRAD,
  so a `light` without `_quadratic_attn` has constant falloff. Check this
  against retail.
- [ ] **APEX-13 Static-light RTL and probe references** `[missing]`: not
  reproduced from retail.
- [x] **APEX-14 Light style** `[wrong]`: copied into the record without a
  retail check. Feeds ALL-09.
  - Done 27 November 2026: all 31,262 retail S0–S3 world lights have style 0.
    The writer now writes 0 and warns, like the Titanfall writers.
- [x] **APEX-15 Cubemaps** `[wrong]`: `EmitCubemaps()` writes 25 identical
  samples at the world centre with `guid = 0`, and the PAKFILE is empty. Retail
  S0–S3 ship `materials/maps/<map>/cubemaps.hdr.vtf`: VTF 7.5, 256×256, one
  frame per cubemap, format 66, 9 mips, flags `0x420c`, plus a `CMA` resource.
  - Progress 27 November 2026: one cubemap per `env_cubemap` (or one above the
    mean spawn) is rendered from the light occluders and sun, using the TF2
    renderer. It is written to a new PAKFILE lump whose VTF header matches
    retail World's Edge field for field. The S3 client loads the map and
    renders as before (`apex-cube-contact.png`).
  - In-game check with the built-in `weapon_cubemap` (chrome `envballs`
    viewmodel, `give weapon_cubemap`), compared with the old build:
    - Without a PAKFILE, the chrome ball reflects an engine fallback outdoor
      scene.
    - With the compiled cubemap it reflects our rooms. The renderer now adds
      point and spot lights, and unlit walls are black when the map has no sky
      ambient. Before that change the ball showed a flat grey-blue tint.
    - Decoded faces: `apex-cube5-faces.png`. Chrome-ball comparison:
      `apex-envballs-chrome-zoom.png` (HV-01).
  - Done: the user judged the current reflections (HV-01 row C) good,
    27 November 2026. Remaining quality work is APEX-29.
- [ ] **APEX-29 Cubemap content quality** `[wrong]`:
  - CMA is 1.0 (meaning unknown, as TF2-15).
  - There is no bounce light, and PBR lights are left out of the cubemaps.
  - Reflections are not compared with a retail map.
- [x] **APEX-16 Character lighting** `[unproven]`: check the third-person probe
  response near static and realtime lights.
  - Fixed 28 November 2026. A character in a sealed, unlit room was lit like
    one in a spot pool, because every probe had SH DC 0.12. Causes:
    - Probe placement and lighting traced only through HIPRT. Builds without
      it treated every ray as a miss, so probes saw the sun through walls.
      The probe ray batches now fall back to the CPU brush tracer.
    - Remap keeps faces that look into the void, and their seeds became probes:
      56 of 72 sat above roofs or behind outer walls. Probes whose axis rays
      leave the map without meeting a visible or sky brush are now dropped,
      unless a player spawn sees out (a leak), in which case all are kept with
      a warning.
    - The spot cone gated probe light links, so no probe linked a 25° spot.
      The cone now only ranks lights.
    - Probe spacing is now 96 (it was 128). Retail S3 nearest-neighbour
      medians are 89 (World's Edge) and 192 (Firing Range).
  - Checked by the `apex-probe-placement` regression.
  - Verified in the S3 client in third person
    (`.local/respawn/tf2-targeted-spot-native-20261126/apex-char-contact-new.png`;
    the old run is `apex-char-contact.png`):
    - in the unlit room the character is now dark;
    - characters in the realtime spot pools and the baked spot pool are lit.
  - Not compared with retail probe values. The probe sun and sky terms still
    ignore `_light` and `_ambient` brightness (they use colour only); see
    ALL-11.
- [x] **APEX-17 Alpha-tested shadows** `[missing]`.
  - Progress 27 November 2026: written in the retail S3 layout.
    - Opaque shadow meshes first, then one alpha mesh per material sort
      (drawType 0, sort index), with position and float32 UV in 0x7D, and
      indices continuing 0x7E.
    - Checked by the `apex-alpha-shadow` regression.
    - A sunlit test map loads in the S3 client.
  - Verified in game 28 November 2026 in a sky-roofed, sunlit yard
    (`.local/respawn/apex-cells-20261127/build_alpha.py`, `alpha-contact.png`).
    - A box with an opaque material (Firing Range concrete, staged with
      `--pak mp_rr_canyonlands_staging`) casts the same sun shadow from the
      alpha stream as from the opaque stream.
    - With a material missing from the loaded packs, the alpha stream cast no
      shadow: the engine alpha-tests the material's texture.
    - The first attempt had pointed the sun upward (`angles` pitch −70 without
      `pitch`) and had no sky, so no sun reached the floor.
- [ ] **APEX-18 Shadow environments** `[done, awaiting HV-05]`: multi-environment
  stress, menu/gameplay isolation and a controlled shadow image comparison.
  - **Retail rule** (S3 Firing Range, 28 November 2026): `light_environment`
    `*0` owns everything outside any volume. A `light_environment_volume` brush
    entity claims its region for `*1`. Each environment has its own contiguous
    range of shadow meshes, CSM nodes and CSM references (meshes 0–5 and 6–29),
    and its own CSM tree. Child and reference indices are absolute across trees.
  - **Compiler, 28 November 2026:** world lights, shadow environments and CSM
    trees follow `lightEnvironmentIndex` order. Shadow casters are split per
    triangle by the volume holding their centroid. Lightmap texels, probes and
    cubemaps use the sun and ambient of the environment that holds them.
    Volumes come from the entity's brushes, or from decompiled
    `*trigger_brush` keys. The `apex-shadow-environments` regression fixture
    checks the ranges, the world-light order and the per-environment suns.
    Single-environment maps are byte-identical, except maps with no
    `light_environment`: their CSM tree now uses the default shadow direction.
  - **In game** (R5Reloaded, `.local/respawn/apex-envs-20261128`): the engine
    applies the environment that holds the camera to the whole view.
    - Standing at x=-300, the yard has `*0`'s white sun; at x=+300 it has
      `*1`'s warm sun.
    - The west pillar's shadow falls to +Y (`*0`), the east pillar's to -Y
      (`*1`).
    - The single-environment control map casts +Y in both halves.
  - **Not covered:** more than two environments in game. Apex S3 has no
    in-map menu stage, so "menu isolation" means volume isolation here.
- [ ] **APEX-19 Lightmap quality** `[missing]`: see ALL-11.

### Materials, models and packaging

- [ ] **APEX-20 Custom assets** `[missing]`: custom textures, models and RPak
  assets with cold-load closure, plus texture streaming and STARPaks. Map
  materials currently have to be in an already loaded pak.
- [ ] **APEX-21 RPak version coverage and GUID collision checks** `[missing]`.
- [ ] **APEX-22 No missing-material checkerboard** `[unproven]`: an authored map
  with arbitrary props.
- [ ] **APEX-23 Repeatable stage cycle** `[unproven]`: compile, stage, load and
  uninstall from a fresh deployment, every time.

### Entities, modes and gameplay

- [ ] **APEX-24 Trigger classes** `[unproven]`: only `trigger_multiple` is
  tested.
- [ ] **APEX-25 Modes and playlists** `[unproven]`: survival (ring/deathfield,
  loot, drop path) plus every playlist beyond the tested Flowstate-script setup,
  with full mode discovery recorded.
- [ ] **APEX-26 Multiplayer first-person session** `[missing]`.
- [ ] **APEX-27 Retail gameplay entities** `[research]`: ziplines, doors,
  minimap, loading screen and level RPak contents.

### Navigation and AI

- [ ] **APEX-28 Navmesh files** `[missing]`: R5 maps use separate `.nm` files
  per hull; none are generated.

### Seasons 0–2 (sub-items)

S0–S3 retail maps share rBSP 47, header revision 30, lump version 0 and 64-byte
static props. Only S3 has been run in game.

- [ ] **APEX-S0 Season 0 runtime gate** `[missing]`: load a compiled map in the
  S0 install. Hand-edit the scripts to register it, since there is no mod
  loader.
- [ ] **APEX-S1 Season 1 runtime gate** `[missing]`: same as S0.
- [ ] **APEX-S2 Season 2 runtime gate** `[missing]`: same as S0.
- [ ] **APEX-S02-1 Per-season differences** `[research]`: diff the retail
  corpora for each season, covering lump content, cubemap format and RTL
  sidecar size. Notes disagree on S3's size: 6.5 bytes per texel in
  `SOW_APEX.md`, 6.0 in Gravemind. Add a season switch to the compiler only
  where the seasons differ.
- [ ] **APEX-S02-2 Staging without a mod loader** `[missing]`: a staging tool
  that patches level lists and scripts in place and can be fully undone.

---

## 5. Apex Legends via R5Flowstate (release 1.1)

R5Flowstate runs a Season 30-era client (`r5apex_dx12.exe`, `client_s30.dll`)
against a Season 3 dedicated server. It has a mod loader (`mods/`, `mods.vdf`)
and ships `r5f-modtool.exe`. ARES has a rendered-client harness for it
(`harnesses/adapters/flowstate_harness.py`, verified on Firing Range on
20 November 2026).

Observed on 27 November 2026, from the Firing Range extraction
(`.local/respawn/flowstate-probe-20261127/`):

- The map VPKs are server only (`englishserver_*`/`server_*`). The
  `mp_rr_canyonlands_staging_mu1` BSP is rBSP v47, revision 30, with 24 lumps
  holding data: entities, collision, the vis tree and world lights, but no
  lightmaps, RTL or probes.
- There is no client map VPK. Each map ships RPak v8 files: the map pak plus
  `_client_perm`, `_client_temp` and `_loadscreen`. Where the client gets its
  geometry and lighting is not confirmed; the RPaks are the likely place.
- Navmeshes ship as `maps/navmesh/<map>_<hull>.nm`.

Goals:

- [ ] **FS-01 Client map format** `[research]`: find where the S30 client loads
  render geometry, lightmaps, RTL, probes and cubemaps for a map. Check whether
  that is a BSP inside an RPak, which version, and which lumps.
- [ ] **FS-02 Server BSP** `[unproven]`: check that the S3 writer's v47 output
  is accepted as the server half, and decide which lumps belong in the server
  VPK.
- [ ] **FS-03 Client writer** `[missing]`: emit the client-side map data in the
  S30 format once FS-01 is decoded, with the season-30 lighting layouts (BC7
  lightmap copy `0x61` and lightmap header flag `0x08` were seen in later-season
  maps).
- [ ] **FS-04 RPak v8 writer** `[missing]`: package map materials, models and
  client map data into the per-map RPaks (`map`, `client_perm`, `client_temp`,
  `loadscreen`).
- [ ] **FS-05 Mod packaging** `[missing]`: a Flowstate mod (`mods.vdf`, playlist
  and level registration) that installs and uninstalls cleanly. Evaluate
  `r5f-modtool.exe`.
- [ ] **FS-06 Navmesh** `[missing]`: the `.nm` files per hull; shares work with
  APEX-28.
- [ ] **FS-07 Rendered-client gate** `[missing]`: the 14-check fixture,
  lighting and targeted-spot fixtures, and a gameplay session through the ARES
  Flowstate harness.
- [ ] **FS-08 Lighting, collision and gameplay parity** `[missing]`: repeat the
  Apex section 4 items that apply to the S30 client.

---

## Human validation

These items need a person: a judgement call, a visual check or access only you
have. Screenshots are under
`.local/respawn/tf2-targeted-spot-native-20261126/` unless an item says
otherwise.

**Blocked on you (open):**

| Item | What's needed | Blocks |
| --- | --- | --- |
| HV-03 | Open each gamepack in MRVN-Radiant and check the generated `retail_entities.ent` loads | ALL-06 |
| HV-04 | A RenderDoc/PIX draw-count capture of the Apex cell fixture, or a convar that locks visibility | APEX-06, making multi-cell the default |
| HV-05 | Check `.local/respawn/apex-envs-20261128/apex-envs-contact.png` (two light environments) | APEX-18 |

Agents: add new rows here when work waits on the user, and remove them when
answered.

- [x] **HV-01 Apex cubemap reflections**: `apex-envballs-chrome-zoom.png`
  shows the `weapon_cubemap` chrome ball in each test room.
  - Row A: old build (engine fallback).
  - Row B: first compiled version (grey tint).
  - Row C: current version (dark room, bright patches from the spot pools).
  - Please judge row C, ideally in game: `give weapon_cubemap` on an
    MRVN-compiled map.
  - Confirmed by the user, 27 November 2026: row C looks good.
- [x] **HV-02 TF1 light-style probe**: `tf1-style2-contact.png`. Confirm the
  pools look steady across the four style-2 frames (columns 2–5) and match the
  baseline (column 1).
  - Confirmed by the user, 27 November 2026: the lights look steady.
- [ ] **HV-04 Draw-call capture for Apex culling**: R5Reloaded S3 has no
  convar that locks world visibility. To prove multi-cell culling (APEX-06),
  capture a frame of `.local/respawn/apex-cells-20261127/cells` (staged as
  `mp_mrvn_cells`) in RenderDoc or PIX from room A facing the end wall, and
  compare the draw count with the `one` build. Or name a convar you know
  locks visibility.
- [ ] **HV-05 Apex light environments**:
  `.local/respawn/apex-envs-20261128/apex-envs-contact.png`. The map is one
  yard, with environment `*0` (white sun) in the west half and `*1` (warm sun,
  opposite direction) in the east half.
  - Top row: the west pillar casts to the right and the east pillar to the
    left.
  - Middle left: the single-environment control, where the east pillar casts
    to the right.
  - Middle right and bottom row: the whole view follows the environment the
    camera stands in.
  - Please confirm the shadows and colours look right.
  - Open question for your judgement: the far floor in the top-left view looks
    warm even though the camera is in `*0`. It could be fog or the distant
    cubemap.
- [ ] **HV-03 Editor entity definitions**: open MRVN-Radiant with each gamepack
  (TitanfallOnline, Titanfall2, ApexLegends) and check that the entity list
  loads with the new `retail_entities.ent` classes and no XML errors.
