# Scope of work: Titanfall 1 / R1Delta and Titanfall Online

> **Closed 27 November 2026.** This scope of work is no longer maintained. Open
> work is tracked in [GOALS.md](GOALS.md); this file is kept as the evidence
> record behind those items.

Date: 24 November 2026. Companion index:
[SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md). This is a task
list for agents, not a compatibility certificate. Keep R1Delta and TFO results
separate even when the BSP is byte-identical.

Path convention: `.local/respawn/...` paths for integration and older branch
evidence are relative to the main `C:/Users/Tristan/GitHub/MRVN-Radiant`
checkout. Closure-owned evidence under `.local/respawn/one-hash-native-replay`,
`.local/respawn/package-closure-20261124` and the target-specific one-hash
directories is relative to `.local/respawn/tf1-tfo-closure`. Absolute paths are
used for game installs and profiles outside those checkouts.

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

**No cross-runtime native certificate exists.** The retained native passes are
tied to older builds. The final one-hash integration build passes all 69 compiler
reports (37 `titanfallonline`, 29 `titanfall2`, 3 `apexlegends`), 316 Python unit
tests and six C++ tests. Under that exact hash, four TF1 fixtures now have
paired R1Delta/TFO runtime sessions: lighting, vertex formats, static props and
collision masks. The TFO lighting run initially crashed before map load in
`nvwgf2umx.dll`; that crash was root-caused to the installed Sentry DLL, and a
local reversible patch let all four fixtures load and finish. Both the original
failure and the patched passes are retained; see the replay sections below.
Native claims stay bound to their recorded build and Sentry DLL state. The
navigation CRC profile is pinned to the retail engine, not the current R1Delta
engine shim.

Compiler target is `titanfallonline`, BSP v29. The checked-out
`tf1-tfo-compatibility` branch only adds two release-packaging commits beyond
the shared base; the substantive 21 November acceptance work lives on
`tf1-r1-acceptance`, which was used as the base for both the one-hash integration
worktree and the isolated TF1/TFO closure worktree. It contains the merged v29
static-prop and RTL analyser worktrees.

On 24 November 2026 the TF1/TFO-relevant notes and tools were copied from
`tf1-tfo-compatibility` into the isolated worktree
`.local/respawn/tf1-tfo-closure` on branch `tf1-tfo-closure` at `25a227a`, based
on `tf1-r1-acceptance` at `d43d43b61e85b0097f10d41aac40df496d6a5182`. Cross-target
TF2/Apex work, Quake-port experiments and `.claude/` metadata remain in the
original worktree, untouched. The closure evidence paths below are relative to
that worktree; see [SOW_BRANCH_INTEGRATION.md](SOW_BRANCH_INTEGRATION.md).

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

## 24 November one-hash replay and offline closure pass (`B`/`N`)

The replay used the final compiler `b0a806…` to recompile four R1 acceptance
fixtures. `mp_tf1_lighting` produced replay BSP
`655c618aafb25241054a860f5f828bb377fec9f8cbce413f62a7223e9cfa5bcc` with compile
log `ca575fc1213b91703e2d04ebcbbe82230fa3e8db2c67193a43a92032210b5e955`. All
lump payload hashes match the earlier recorded BSP
`a98be3129dab75a01d68ed8e413b2edc86cfff8ab86c313a44d5c99453ba6c8a` (`[]`
differences); the whole-file hash differs in the BSP header timestamp. The three
extended fixtures also recompiled with `[]` lump payload differences; their per-lump
comparison index is
`.local/respawn/one-hash-native-replay/extended-lump-diffs.json` (SHA-256
`c808c2cf228fadfff7656b96592dabdfcd4a2975e60cf1b4bc6ff147ea009473`).

- **R1Delta lighting:** one session loaded and finished, with two traces, four
  views and no errors. Report
  `8c228d31ca3fc3d8f12a75352787ebeb4979e5c7cb6ff1fe9710aa6bc46531d4`.
- **TFO lighting, stock Sentry DLL:** three attempts all exited before map load
  with an `nvwgf2umx.dll` stack overflow (exit code `3221225725`). Report
  `c4e09a6a79449044d5d24b856713353b4017e4fde0b11aed33b7743d4b2e5f92`; log
  `ffa408987c995cc1a65da1b6d1a9558b4cff1691465e510ce2933c4cd8a118e9`. This is
  retained as a failing case, not a parity pass.
- **TFO lighting, locally patched Sentry DLL:** the same replay BSP loaded and
  finished with two traces, four views and no errors; events match the R1Delta
  report. Report
  `1b535532075368b7794775aa1b8fce5a992a27013e1cfbc79d6e68b9edeb5d11`; log
  `4879d7ca1a8355287ac1aab872edf936909e20b359870dc6852704952b880083`.
- **Extended fixtures:** `mp_tf1_vertex_formats`, `mp_tf1_props` and
  `mp_tf1_masks` were replayed in both runtimes with the patched TFO DLL. All
  loaded and finished with zero errors, and normalized trace/hull/drop/view
  events agree. See the table in the next section. The first TFO attempts used
  the wrong `--maps` depth and failed before level load; those reports are
  retained as harness/path failures, not compiler results.
- The R1 harness initially refused a `r1/addonlist.txt` with a UTF-8 BOM inside
  the opening quote. A backup was kept at
  `D:/Games/Titanfall/r1/addonlist.txt.bom-backup-20261124`; the key was repaired
  minimally and the harness restored its own addon.

Full evidence and limits are in
`.local/respawn/one-hash-native-replay/results.json` (SHA-256
`52201694ce9cdb15b61434bbd80013e4be328266f1b686dea1a1281ba4a37bae`). The same
index also records separate, bounded one-hash Northstar and Apex/R5 sessions;
those belong to [SOW_TF2.md](SOW_TF2.md) and [SOW_APEX.md](SOW_APEX.md) and are
not TF1/TFO certificates. This pass does **not** add physics launch breadth,
water, objective, cubemap or shader/material-hash coverage, and the unpatched
TFO crash alone gives no cross-runtime certificate.

## TFO startup stack-overflow root cause and local patch (`E`/`B`/`N`)

The pre-map `nvwgf2umx.dll` stack overflow is **not** BSP-output evidence. The
installed `D:/Games/Titanfall Online/Bin/sentry.dll` is upstream sentry-native
`0.7.8` (`E`: SHA-256
`768f9a5f6ea8c8dd88e3b00c0c604fee09f745831b16de54397815623dda2c26`), whose
`DllMain` calls `SetThreadStackGuarantee()` for every attaching thread. NVIDIA
D3D worker threads have small stacks, so the guarantee exhausts them before map
load. This is the regression reported in
[getsentry/sentry-native#1193](https://github.com/getsentry/sentry-native/issues/1193)
and [NVIDIA forum thread 327461](https://forums.developer.nvidia.com/t/stack-overflow-exception-in-nvwgf2umx-dll/327461).
Upstream made the auto-guarantee defensive in
[PR #1196](https://github.com/getsentry/sentry-native/pull/1196), released in
sentry-native 0.8.4.

The local patch is isolated in the closure tree:
`tools/respawn/tfo_sentry_patch.py` (SHA-256
`5077d0062e26cf1eb2c67d02c0ac60c45c514f72716c8a995d3d85e9d51335c9`). It
replaces the `DllMain` prologue at file offset `0x7c00` (RVA `0x8800`) with
`b8 01 00 00 00 c3` (`mov eax, 1; ret`). In 0.7.8 that function contains no work
other than the stack-guarantee call, so an immediate `TRUE` return is the minimal
equivalent of commenting out the call. The tool keeps an original backup,
refuses unexpected DLL hashes, and restores the installed DLL afterwards.

Controlled A/B under the same compiler and replay BSP (`B`/`N`):

| Sentry DLL | Output | Result |
| --- | --- | --- |
| Stock 0.7.8 | `.local/respawn/one-hash-native-replay/reports/r1-lighting-tfo-sentry-original-ab` | Failed before map load; exit `3221225725`. Report SHA-256 `e3b2b51cec94857ce0011fceaf10a62d785bc5544ac6abe84239d1f974e7d13a`; log `4c20deecb06a25fa9a5463faa78285b0eed9e29ea601786c99980f7802dbd63b`. |
| Locally patched | `.local/respawn/one-hash-native-replay/reports/r1-lighting-tfo-sentry-patch-tool` | Loaded and finished with two traces, four views and no errors. Report SHA-256 `1b535532075368b7794775aa1b8fce5a992a27013e1cfbc79d6e68b9edeb5d11`; log `4879d7ca1a8355287ac1aab872edf936909e20b359870dc6852704952b880083`. |

Patched DLL SHA-256:
`f93c0d4be3ee78509f043bedecd3d58eed66492357194e1043434db74f813bf1`. The
installed DLL was restored to the stock hash after the A/B. Full provenance,
including TFORevive repo pins and driver version, is in
`.local/respawn/tfo-crash-patch/report.json`.

**Limits:** this is a local third-party DLL patch, not an upstream TFORevive fix
or a substitute for upgrading to sentry-native 0.8.4+. It disables the automatic
per-thread stack guarantee, so crash reporting on tiny-stack threads is not
guaranteed. One fixture, one driver (`32.0.16.1088`) and a small number of
sessions were tested; this does not establish broad TFO stability, image parity
or a release gate. The original 24 November failure remains in the evidence.

The ARES harness now documents both blockers so they recur less often:
`C:/Users/Tristan/GitHub/ARES/harnesses/docs/tfo.md` has a `Startup blockers`
section for `--maps` depth and the Sentry DLL, and
`C:/Users/Tristan/GitHub/ARES/harnesses/README.md` points operators to
`tfo_sentry_patch.py status` before changing a fixture. ARES adapter tests:
197 OK, 1 skipped; log SHA-256
`08a8a6e21701de77d007a7e1786eeb697e6833aa09fb8d13b20960e3af668ce0`.

### Corrected-path extended native replay (`B`)

The first extended TFO runs used a fixture root while the BSP was in its
`maps/` folder. The closure harness then installed an empty mod map directory,
so TFO stayed on the loading screen and never emitted
`UICodeCallback_LevelLoadingStarted`. `map_source()` now resolves either layout
and fails before touching `Mods/` or `enabledmods.json`; ARES received the same
fix plus synthetic tests. All corrected runs used the patched Sentry DLL and
`--maps .../maps`.

| Fixture | Replay BSP / compile log SHA-256 | R1 report | ARES TFO report / log | Result |
| --- | --- | --- | --- | --- |
| `mp_tf1_vertex_formats` | `220007849ab0a54fab2a4d9ef0668974bd5c12591526eda8625a36119782185e` / `823c4289d38baa1ff76c93f1a092349205b78d15ffb9b8c83904cdd7f1f28be1` | `ecc1045ed80fac82473988b9a79f332cafb37644dfc426547d4dd96667441f04` | `1698edb8aac8a68129af934887cf63f20391c33fe6b917162f1b905e95021107` / `a7fb2ced703a538ba12c0b90a36d5dda5c7e228fd09a010786e0e4a5139865ef` | Loaded, finished, 0 errors; normalized events equal. |
| `mp_tf1_props` | `cdf3d05b266066a683b47eb8c23159367575c344eca1989390f8581d8fe7719d` / `5f91b694416ff9649caa8054d9a57dfd4914b58392436fbe70f280ca147d51ad` | `6fc8d680c0019e0bc1f5187109fed5fd295c6cd1c90977fb88e205ed7771354` | `870bbaeae6a7359b07a17320783a6f602b2deeeec2f18abd339d9303138dcd7f` / `32490d545d50d4913bac8c83829b90e6481253cda620f7993e7cb1ab3d625365` | Loaded, finished, 0 errors; R1-only `SPAWNED` marker and ARES-only bounds fields ignored. |
| `mp_tf1_masks` | `0447b9fc5ba6b55cb1108fb83eda62ca016292f5d70eaaa89674ea4213dbc3bc` / `bd8a2de0d599a67546eebf2598f1d8c9640e84921bf037dcd9de901569e1d931` | `627bf73f97217a302c5c91a231fc84fcf673ff1c48a6b3ae02fbdc4738dadc` | `386e86de1073da2cc3f430e0f02842b21c754e71f04491f083d45071b8a84cae` / `d3e17e1c0e4718d473d1c3cfc6919834c860bd4481fb9a4fcc9fc010e24db455` | Loaded, finished, 0 errors; all 34 events equal. ARES was required because the older closure TFO harness hardcodes `playersolid`. |

The older closure harness also passed the corrected vertex and props runs:
reports `831b29dbbb40a3746649e093b879395ffed92126b00022fe7c0487aae22bb8ef`
and `29d25524013084afd3957d36f28e4a15f4dc94662aa03b971577a58246fd30ec`; logs
`65c1923f803220fa4a65079fae43e090c7c9982a980cf85218804bf081a390d6` and
`7a4a631e3d02157d3d9a301872b26f59037f988c0b39ccbdda783cb026ddb7e0`. Its mask
run loaded and finished but reported 14 expectation errors because it ignored
`trace_masks`/`hull_masks`; the ARES run above is the valid mask comparison.
The failed wrong-depth reports remain under the `r1-*-tfo` report directories.

**Limits (`B`/`N`).** These are single-session traces, hulls, drop position and
view captures, not image comparisons. The props drop matches numerically but the
harnesses emit different marker/field sets. No physics launch breadth, water
fixture, mode, objective or custom-material package was replayed here.

Offline closure work in this isolated tree also produced:

- `build_tf1_package.py` now accepts the real directory VPK name emitted by
  `pack_tf1_shaders.py`/`pack_vpk.py`
  (`englishclient_<map>.bsp.pak000_dir.vpk` with the unprefixed
  `client_<map>.bsp.pak000_000.vpk` block), alongside the older renamed
  `client_<map>..._dir.vpk` form. A regression test covers both the generated
  pair and rejection of unrelated names.
- A fresh package build of `mp_tf1_water` with the native-tested shader VPK and
  loose asset source succeeded; the manifest reports one base-game material
  (`world/concrete/concrete_floor_01`) and no unverified files. Evidence:
  `.local/respawn/package-closure-20261124/water-package/manifest.json` with
  SHA-256 `be5167a9774dea6436180cb2b7e9d7dae6d728bc70890027cc203e43d3ffef8b`.
- The Water dependency audit reports `issues=[]` for two VMTs, eight files and
  two runtime resources:
  `.local/respawn/package-closure-20261124/water-dependencies.json` with SHA-256
  `6b3cc0d8a704206a5788b54e20b791b950d984c426c9d0dd919451b622c16259`. This is
  still a bounded direct-dependency audit, not full closure.
- Four retained TF1 v29 BSPs (Water, two Quake material fixtures and the packaged
  shadow fixture) validate with zero issues.
- `analyze_rtl.py` on the one-hash `tf1-realtime-lights` BSP reports four bytes
  per texel, five light records, ordered slot filling, and 2,000 sampled rays;
  raw exports are in
  `.local/respawn/one-hash-native-replay/offline-lighting/` (`tf1-realtime-rtl.json`
  SHA-256 `2b661069d4365dc8b1a6b3ef153b34fd1ce18ce02975e34cc36fcfe29608e6a3`,
  `tf1-realtime-lights.json` SHA-256
  `60d15aa7c8d6b87e302bbdcb506568a9e064183808358e98443f596cfbce585f`). These are
  offline statistics, not shader or image evidence.
- The isolated Python suite is 302 OK; log SHA-256
  `be806342facb9c9ef7cdd5cdf01bf04ace703cc79c348d3f9e22c70ae4460946`. The
  closure tree's older `compiler_regression.py` cannot be run against the
  one-hash binary because it predates the Apex metadata fix in the integration
  tree; use the integration one-hash 69-report result for compiler coverage
  instead of importing that cross-target fix here.

### Installed-map audit and TFO native cross-check (`B`/`S`/`N`, 25 November)

The all-games audit checked 34 loose TFO BSPs and 34 TFO record sets; no TFO VPK
archive was in scope, and no TF1 inventory was flagged. Its one flagged TFO
entry was stock `mp_colony.bsp`, whose declared entity-partition sidecars were
not found in the scanned loose tree. A direct stock-map launch with the two
installed content mods enabled and the reversible Sentry patch reached
`UICodeCallback_LevelLoadingStarted`, SERVER `_mapspawn`, CLIENT
`_cl_mapspawn`, `UICodeCallback_LevelInit` and
`UICodeCallback_LevelLoadingFinished (error: false)`. `TFO.exe` SHA-256
`1569b5b66dba1773dd04c7a0122bbf99a836e34177c7efcfe078944cf1faad5f`; BSP
SHA-256 `76500eebba3d7fabef3706952e267c2e1c3d9fcf664952eb4fb0802aa736dc83`.
`sentry.dll` and `enabledmods.json` were restored. This bounds the sidecar gap
to static extraction scope for one stock map; entity partitions, triggers,
navigation and gameplay remain unproven. Report:
`.local/respawn/all-maps-audit-20261125/REPORT.md` (SHA-256
`a0c58f31a7e910cd2147db1fff2c93f65f5bce5ecddad1eb9d620685ef62d7f4`).

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
vertex-format fixes are in the one-hash compiler. The 24 November replay now
covers lighting, vertex formats, static props and collision masks with identical
lump payloads and paired R1Delta/TFO sessions; broader corpus coverage under
that hash is still open.

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
On 24 November the packager was fixed to accept the directory VPK name actually
emitted by `pack_tf1_shaders.py`; a fresh Water package and dependency audit now
run offline with zero audit issues and one reported base-game material. Known
texture string-table offsets are checked by `validate_records.py`; that is not
broad corpus coverage.

**Missing:** complete custom asset dependency closure, cubemap path verification,
verification of the branch-local `sprp v12` fix on a nontrivial package, paired
native load of authored materials + models + shaders together, and a clean
editor-to-game release on pinned builds. The uncommitted
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
Hardpoint, but the other modes are startup-only. The 24 November one-hash replay
covers the lighting, vertex-format, prop and mask fixtures with paired
R1Delta/TFO sessions, including the mask fixture's 16 trace and 16 hull cases,
but not modes or navigation. TFO's Core135 Hardpoint needs explicit temporary
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
fluid keydata with nonempty brush/water/submodel fixtures. The 24 November
one-hash replay adds one staged prop drop but no repeated physics launches, so
it does not advance this gate.

On 26 November, six independent R1Delta launches of the one-hash `mp_tf1_props`
fixture were recorded under `app-3.0.5` (`server.dll`
`50faad928e0715a51ad624d0a3eb8f00f7ffad9e66258dc95c960f9d11ff41e4`,
`engine_r1o.dll` `7d85f8201f2a951a35ddb57dc8162169a1b3fa730b7a94b0caec002dcc569999`).
All six loaded and finished with `errors: []`; each recorded a valid barrel
drop with a resting height of 15.59375 or 15.625. Evidence:
`.local/respawn/certification-program-20261126/tf1-physics-breadth/RESULT.md`
(local, uncommitted). This advances only the R1Delta launch-breadth half of the
gate: it adds no TFO launches (stock Sentry still fails), no retail control, no
additional variant/model, and no `PHYSICS_TRIANGLES` A/B. The gate stays Partial.

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
parity. The one-hash `mp_tf1_masks` replay covers 16 trace and 16 hull mask
cases in both runtimes, but no broad patch sweep was replayed under that hash.

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
control; loose shaders do not suffice. The 24 November offline Water audit and
package build confirm the VPK naming and direct file dependencies, but no native
water session was replayed under the one-hash compiler.

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

The 24 November replay confirms the same BSP loads in R1Delta with four captured
views and passes offline RTL statistics (four bytes per texel, ordered slots,
five light records). With the local Sentry patch, the paired TFO session loaded,
finished, emitted the same events and captured four views; the stock-DLL failure
is retained separately. No paired image comparison or shader validation was
added.

**Targeted and styled lights (`B`/`N`, 27 November).** The shared
light writer now aims a `light_spot` at its `"target"` entity and bakes
authored styles as constant lights with a warning (see TF2-LGT-01; the TF2 side
has a native `N` pass and a style-2 runtime probe showing no style effect). The
v29 fixture `mp_tf1_targetspot` (WORLD_LIGHTS v1) carries the aimed spot normal
`(0.7295, 0, -0.6839)` for realtime (flag 30) and baked (flag 6) spots, and
`(0, 0, -1)` for the untargeted control. The first native attempts were blocked
by a machine-level desktop `BitBlt` hang that a reboot cleared. They are kept in
`.local/respawn/tf2-targeted-spot-native-20261126/RESULT.md`. After the reboot:
- R1Delta 3.0.5 (engine screenshots) and TFO Core 135 (local Sentry patch,
  window capture) both loaded, finished and captured all six views with no
  errors. The targeted pools sit toward +x in both runtimes. Top-down luminance
  centroids are 0.70/0.69 (realtime/baked) against 0.25 for the control in
  R1Delta, and 0.71/0.71 against 0.27 in TFO.
- **Stepped spot edges (fixed).** With the original compiler, both runtimes cut
  the realtime pools at the cone edge into texel-sized steps; TF2 shows smooth
  edges from the same records. Probes on copies of the BSP showed why:
  - Narrowing the record cone to 5° shrank the pool to the predicted 58 px
    disc, so TF1 applies `stopdot`/`stopdot2` with the same linear fade the
    baker uses.
  - Dilating the realtime-light index plane (lump 0x69) by one or two texels
    removed the steps.
  Slot indices cannot be blended, so a pixel whose texel lacks the light goes
  dark while the shader fade is still a few percent, which display gamma makes
  visible. Pass 1 of the bake now scores each light at its best over the texel
  centre and its eight neighbours ±1 texel. Scoring only the texel's own ±0.5
  footprint was tried natively and still stepped. With the new rule the fixture
  slots match the one-texel probe (light 1: 535 texels, light 2: 287), and the
  compiler's own output renders smooth pools in R1Delta (report `88ba6bdf…`)
  and TFO (report `ce2ab0ef…`). `remap.exe`
  `fff36c8fd728139ee50b37eb1015aef47686ecc3fad6c528309e670153f9e40c`;
  70 regression fixtures clean, 324 unit tests pass. The rule is shared with v37
  and Apex. The TF2 slot planes widen too, but the TF2 visuals have not been
  rechecked natively.
- The TF1 style-field runtime probe has not been run; TF2 showed no effect.

**Missing:** full RTL channel decoding beyond the tested slot layout, light
flag/brightness equivalence for targeted (native), styled (native) and `_pbr_falloff` lights, and
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
cases and menu/gameplay isolation. The 24 November one-hash replay used the same
lighting fixture but no generated-versus-stripped shadow A/B; the patched TFO
session only proves the fixture loads and captures views. Earlier 50-second TFO
runs only proved slow startup, not a shadow defect; use the 300-second budget.

**Acceptance:** paired captures with matched geometry, materials and camera in
both runtimes; generated BSP, not a hand-stripped variant; verify opaque and
alpha silhouettes and sky exclusion; record shader/material hashes.

### TF1-LGT-03 — probes and cubemaps — Partial (`B`/`N`)

TF1 uses the shared probe placement and bake path; third-person captures in TFO
show walkable probes fix a black-character case. Retail cubemaps exist in Angel
City and Colony, but mesh selection and TF1 cubemap content are not validated.

**Missing:** probe response across multiple hulls and environments, cubemap
choice and CMA/CRC semantics for v29, and visual equivalence of reflections. No
TF1 v29 probe/cubemap fixture was added in the 24 November pass; the one-hash
probe fixture remains a TF2 v37 environment-volume test.

**Acceptance:** authored probe/cubemap fixtures with paired native captures and
a documented rule that matches a statistically significant sample of retail
mesh assignments.

### TF1-LGT-04 — bake robustness and cross-runtime parity — Partial (`N`)

Buried texels, speckle and stair-stepped static shadows were diagnosed and
fixed; bounce lighting and chart filtering have measured before/after data.

**Missing:** agreement on fill level across both runtimes, engine shader
validation of SKY A/B and RTL channel meanings, and dense receiver comparisons
instead of vertex samples. The 24 November replay supplies the same recompiled
BSP, an R1Delta load and a patched TFO load with matched event traces, but no
matched image comparisons or raw SKY A/B exports were collected.

**Acceptance:** same BSP baked once, loaded in R1Delta and TFO with matched
captures and raw atlas exports; record all worldspawn bake keys and compiler
hash.
