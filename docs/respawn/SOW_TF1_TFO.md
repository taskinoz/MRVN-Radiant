# Scope of work: Titanfall 1 / R1Delta and Titanfall Online

Date: 24 November 2026. Companion index:
[SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md). This is a task
list for agents, not a compatibility certificate. Keep R1Delta and TFO results
separate even when the BSP is byte-identical.

## Pinned targets and current boundary

| Runtime | Build used by the recorded evidence | Boundary |
| --- | --- | --- |
| R1Delta / Titanfall 1 | R1Delta `app-3.0.5`, game at `D:/Games/Titanfall`, modified runtime | Unmodified retail matchmaking and other versions are untested. Native AIN export is launch-gated. |
| Titanfall Online | TFORevive.Core `135`, game at `D:/Games/Titanfall Online`, with the documented content mods and harness overrides | Core135 without its temporary Hardpoint fixes is not a supported baseline. The current `enabledmods.json` disables `OldLobby`, `TestPlaylist` and both Titanfall1 content mods, so the installed configuration is not the recorded test configuration. |

### Installed-file and compiler fingerprints (`E`)

| Artifact | SHA256 / version |
| --- | --- |
| Original 21–24 November evidence build (`install/Release/remap.exe`) | `6daec3b2309802af6ecfd17d2635a8a7e693b07d59325094c2dd1fcebf81ff94` |
| Final one-hash integration build (`.local/respawn/integration-one-hash/install/Release/remap.exe`) | `b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` |
| Baseline-audit compiler in `RESPAWN_MAP_SUPPORT_AUDIT.md` | `128e474f734f433dde107e3c1a509b0b835714eb153664a843c2bb0b2e70fbd2` |
| `phase2-rtl-fixed` build (`c9c63fe`) | `49e50ff1d270dd5c3a2d42b23ed5f7d0c477d67bcca096eb507c352e3be8ae2a` |
| R1Delta 3.0.5 server.dll | `50faad928e0715a51ad624d0a3eb8f00f7ffad9e66258dc95c960f9d11ff41e4` |
| R1Delta 3.0.5 engine_r1o.dll | `7d85f8201f2a951a35ddb57dc8162169a1b3fa730b7a94b0caec002dcc569999` |
| Retail TF1 `engine.dll` used by the navigation CRC profile | `0214a40436eca77f160d12763ab8f392a8ce2268bfe0a973188e426ae4c0263c` |
| TFO `engine.dll` | `39e2a1c83b7bea3fa1a2f98ecc6cde3016e3567a1bc89cf8926d8a613dc62ad1` |
| TFO `server_local.dll` | `8dabdd4f46218bdd72bd9c4ea53d24178c7974ec4277f6872f671ac1fe99dd7b` |
| TFORevive.Core / Core.Client / TF1 content mods | version `135` / `135` / `1` |

**No cross-runtime native certificate exists.** The compiler hashes above differ,
and the retained native passes are tied to older builds. The final one-hash
integration build passes all 69 compiler reports (37 `titanfallonline`,
29 `titanfall2`, 3 `apexlegends`), 316 Python unit tests and six C++ tests, but
the R1Delta and TFO native sessions have not been replayed under that exact hash.
Native claims stay bound to their recorded build. The navigation CRC profile is
pinned to the retail engine, not the current R1Delta engine shim.

Compiler target is `titanfallonline`, BSP v29. The checked-out
`tf1-tfo-compatibility` branch only adds two release-packaging commits beyond
the shared base; the substantive 21 November acceptance work lives on
`tf1-r1-acceptance`, which was used as the base for the one-hash integration
worktree. It contains the merged v29 static-prop and RTL analyser worktrees.
The checked-out tree additionally has uncommitted physics and Quake-port
notes/tools; see [SOW_BRANCH_INTEGRATION.md](SOW_BRANCH_INTEGRATION.md).

Baseline evidence: [RESPAWN_MAP_SUPPORT_AUDIT.md](RESPAWN_MAP_SUPPORT_AUDIT.md),
[RESPAWN_TF1_LUMPS.md](RESPAWN_TF1_LUMPS.md),
[RESPAWN_TF1_PHASE2.md](RESPAWN_TF1_PHASE2.md),
[RESPAWN_TF1_LUMP_CHECKLIST.md](RESPAWN_TF1_LUMP_CHECKLIST.md),
[RESPAWN_TF1_NAVIGATION.md](RESPAWN_TF1_NAVIGATION.md),
[RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md) and
[RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md).

## Branch-local acceptance evidence (`N`)

`tf1-r1-acceptance` records a 21 November R1Delta round and treats R1Delta as
the acceptance benchmark because TFORevive is unfinished. Evidence is under
`.local/respawn/r1-*-20261121/`. It adds results not present in the checked-out
branch:

- **Physics:** ramps, curved patches, a three-barrel stack, long fall onto an
  8-unit slab, throws at 800/2500 u/s and rotated drops. 11 of 12 stations pass
  in all four runs with identical heights; the remaining tumbling throw is still
  rolling at 25 s because VPhysics barrels have almost no rolling resistance.
- **Static props and vertex formats:** rays stop on upright, yawed and tipped
  barrels; lit-bump/unlit draw, while lit-flat/unlit-TS drew black before being
  mapped to supported v29 formats.
- **Lighting and water:** sun with a sharp pillar shadow, baked and realtime
  point lights draw; the flag-14 spotlight pool was not distinguishable in the
  reviewed view. Two pools get separate water records, correct wet/dry cells and
  plausible buoyancy heights.
- **Collision and modes:** transformed brush/patch masks and rays pass; tdm,
  ctf, lts, cp and exfil all start and report their mode in R1Delta, and cp
  initializes three hardpoints. Only Hardpoint has been played to capture and
  score; other modes are startup-only checks.
- **Compiler fixes:** sprp v12 layout, retail light flags, probe links to baked
  lights, SKY B alpha sun occlusion, LEVEL_INFO sun vector, entity NUL handling,
  real bounds for mesh-less brush models and vertex-format conversion.
- **Retained shadow runs:** `.local/respawn/tf1-shadow-final-20261120/results.json`
  reports 63 cases with zero issues; TFO light-isolation runs report
  `loaded=true`/`finished=true` for full-cutout, cutout-visible, sun-metadata and
  package cases, and `regression-alpha-flags-complete/results.json` reports 65
  cases with zero issues. These are record checks and session outcomes, not
  controlled image comparisons, and some TFO launches still crash in
  `nvwgf2umx.dll`.

These are branch-local results. They must be integrated and reproduced from a
single compiler build before they count toward a release gate.

## Map support

### TF1-MAP-01 — semantic parity of the v29 writer — Partial (`B`/`S`)

The writer has 70 unique lump paths and 61 selected record schemas; the corpus
checker reports 74/75 represented names when the empty lumps are counted.
`PHYSICS_TRIANGLES` is the one populated retail lump not emitted. The blob layout
and engine parser are now decoded in
[RESPAWN_TF1_LUMPS.md](RESPAWN_TF1_LUMPS.md#vphysics-physics_collide), and
`tools/respawn/physics_triangles.py` can generate field-equivalent hulls, but
retail bytes are not reproducible and no native load-time A/B was recorded. The
engine builds the virtual-mesh hulls at load, so this remains an optimization
rather than a proved load blocker. The optional writer was deliberately left out
of the one-hash compiler; see
[SOW_BRANCH_INTEGRATION.md](SOW_BRANCH_INTEGRATION.md).

**Missing:** field-level semantics for most other records; validation of
`LEAF_WATER_DATA` and exotic vertex-format paths. The static-prop and
vertex-format fixes are in the one-hash compiler, but still need a native replay
under it.

**Acceptance:** a nonempty generated fixture for every named lump the target
corpus populates, with `validate_records.py` checks and a paired R1/TFO load;
for `PHYSICS_TRIANGLES`, either emit the decoded hulls with a load-time
comparison, or keep the documented native fallback and accept the unmeasured
cold-load cost.

### TF1-MAP-02 — materials, models and package closure — Partial (`B`/`N`)

`build_tf1_package.py` produces a TFO mod and an R1Delta addon with dependency
reporting, an optional shader-only VPK, hashes and zips. Loaded package folders
are recorded. R1Delta needs `info_intermission`, a +/-16384 coordinate envelope,
per-map model VPKs, and the `water_ps40.vcs`/`water_vs40.vcs` pair inside a VPK.

**Missing:** complete custom asset dependency closure, cubemap path verification,
string-table offsets, verification of the branch-local `sprp v12` fix on a
nontrivial package, and a clean editor-to-game release on pinned builds. The uncommitted
`build_tf1_quake_textures.py` builds VTF/VMT material trees from LibreQuake DDS
outputs; it is untracked and untested. The untracked `tf1_materials.py` and
`tf1_models.py` convert TF1 materials/models to TF2 assets; they are a separate
cross-game port experiment, not proof of v29 support.

**Acceptance:** a map with authored/custom materials, models and shaders loads
from a clean deployment in each runtime; hashes and manifests cover every file;
no loose-only shader dependency passes the gate.

### TF1-MAP-03 — entities, objectives and navigation — Partial (`N`)

Hardpoint initialization, one neutral capture/score gain, a standing trigger
walk and one native grunt obstacle route are recorded in both runtimes. AIN
export/offline CRC packaging now has paired fixtures and live CRC observations.

**Missing:** contested/recapture objectives, respawns, human multiplayer,
hull/route breadth, moving dynamic obstacles, combat, default animations and
titan piloting. The branch-local R1 run starts tdm/ctf/lts/cp/exfil and scores
Hardpoint, but the other modes are startup-only. TFO's Core135 Hardpoint needs explicit temporary
dialogue/sound fixes, so an unmodified-Core claim is not available.

**Acceptance:** repeatable all-mode fixtures in both runtimes with no mode-specific
overrides unless the override is an explicitly supported configuration; multiple
hulls and routes with native AIN/CRC checks.

## Collision

### TF1-COL-01 — VPhysics and physics stability — Partial (`B`/`N`)

Brushes, flat patches, isolated drops, buoyancy controls and a sequenced crate
fixture are recorded. A negative-zero IVP bug on z=0 floors was fixed. Later
work showed the remaining crate failures are launch-dependent: a bad TFO launch
sinks every crate wherever it lands, while retail Angel City rested every crate
in four launches. The current working tree records this and forbids judging a
change from a single launch.

**Missing:** cause of bad sessions; full curved/stacked/thrown coverage in both
runtimes with at least six launches per variant (the R1 branch has four runs and
one still-rolling throw); validation of `PHYSICS_COLLIDE` model/solid lengths, material tables and
fluid keydata with nonempty brush/water/submodel fixtures.

**Acceptance:** six or more independent launches per variant, with byte-identical
BSPs and recorded hashes; no compiled-floor crate passes through the floor;
retail control run in the same harness; failures retained with full logs.

### TF1-COL-02 — patch collision and bevel selection — Partial (`B`/`N`)

Patch grids emit TRICOLL headers/triangles in both v29 and v37. Exact convex
merging fixes reproduced shared-edge misses, and 156 front-facing world
ray/hull results agree across formats. Four dome triangle hull comparisons are
unresolved.

**Missing:** backfaces, transformed patch entities, other orientations, moving
props, projectile-specific masks, titan hulls, and byte-level selection of
`TRICOLL_BEVEL_INDICES`. The existing rule is a functional superset, not retail
parity.

**Acceptance:** paired native sweep suites for every orientation and entity
transform, plus projectile/titan checks; a documented decision to retain a
functional bevel rule or reproduce retail lists exactly.

### TF1-COL-03 — water and `LEAF_WATER_DATA` — Partial (`N`)

Wet-cell world draw participation (0x200000), Water/WaterBeneath shader profiles
and a rectangular water room are implemented. TFO renders floor/fog in one
underwater scene; R1Delta retains a black band in the upper view, and an
underwater horizon artifact also appears in recorded retail controls.

**Missing:** cell assignment against real visibility cells (especially
single-cell maps), sloped/multiple volumes, submerged props, buoyancy breadth and
a classified R1 artifact. A shader-only VPK is required for the native Water
control; loose shaders do not suffice.

**Acceptance:** wet/dry, sloped and flooded fixtures in both runtimes with
matched retail controls, including underwater views, physics and dependency
audit; classify the R1 band as compiler or runtime before claiming parity.

## Lighting and shadows

### TF1-LGT-01 — RTL, SKY and realtime lights — Partial (`N`)

The v29 realtime-light plane now stores bake slots as hardware indices; both
runtimes light a covered room from two realtime lights while the all-255 control
stays black. A compiler regression covers flags, order and slot contents. SKY A
is linear; one diffuse bounce and texture reflectivity are written. The R1
acceptance branch also writes SKY B alpha sun occlusion, sets the LEVEL_INFO sun
vector from the last sun and links baked lights from probes; its R1 fixture shows
sun, baked point and realtime point pools.

**Missing:** full RTL channel decoding beyond the tested slot layout, light
flag/brightness equivalence for styled, targeted and `_pbr_falloff` lights, and
a calibrated fill level. Retail SKY A medians span 0.014–0.176 while released
ports sit at 0.013–0.030; the default 0.04 ambient fill was calibrated on the
dim Coliseum outlier.

**Acceptance:** per-runtime image comparisons for point/spot/sun, static and
styled lights; decode the remaining channels against engine shader behavior;
choose a default or explicit per-map calibration backed by captures.

### TF1-LGT-02 — sun, CSM and shadow streams — Partial (`N`)

A prop-free fixture exposed inverted v29 CSM bounds; the compiler now emits a
zero-size root with no references in that case. Gameplay sun direction,
64-aligned CSM prop indices, opaque shadow meshes and a separate alpha stream
are implemented. Full-budget TFO runs show the generated opaque stream casts a
shadow and the stripped control does not. A cutout fixture with 40-unit holes
shows round lit holes in TFO; small holes fall below cascade resolution.

The R1 acceptance branch loaded its shadow fixture with 24 opaque and 12
alpha-tested shadow triangles, passed floor/roof traces and produced three
engine captures, but this was not a controlled projected-shadow image
comparison. Some TFO launches in the same round hit an `nvwgf2umx.dll` stack
overflow, so the TFO lighting result stays inconclusive.

**Missing:** controlled projected-shadow image comparison in TFO and R1Delta,
behavior of the compiler-generated opt-out (only a binary-stripped control has a
successful TFO launch), broader multi-environment
cases and menu/gameplay isolation. Earlier 50-second TFO runs only proved slow
startup, not a shadow defect; use the 300-second budget.

**Acceptance:** paired captures with matched geometry, materials and camera in
both runtimes; generated BSP, not a hand-stripped variant; verify opaque and
alpha silhouettes and sky exclusion; record shader/material hashes.

### TF1-LGT-03 — probes and cubemaps — Partial (`B`/`N`)

TF1 uses the shared probe placement and bake path; third-person captures in TFO
show walkable probes fix a black-character case. Retail cubemaps exist in Angel
City and Colony, but mesh selection and TF1 cubemap content are not validated.

**Missing:** probe response across multiple hulls and environments, cubemap
choice and CMA/CRC semantics for v29, and visual equivalence of reflections.

**Acceptance:** authored probe/cubemap fixtures with paired native captures and
a documented rule that matches a statistically significant sample of retail
mesh assignments.

### TF1-LGT-04 — bake robustness and cross-runtime parity — Partial (`N`)

Buried texels, speckle and stair-stepped static shadows were diagnosed and
fixed; bounce lighting and chart filtering have measured before/after data.

**Missing:** agreement on fill level across both runtimes, engine shader
validation of SKY A/B and RTL channel meanings, and dense receiver comparisons
instead of vertex samples.

**Acceptance:** same BSP baked once, loaded in R1Delta and TFO with matched
captures and raw atlas exports; record all worldspawn bake keys and compiler
hash.
