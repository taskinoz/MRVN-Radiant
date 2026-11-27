# Scope of work: branch integration and stranded changes

> **Closed 27 November 2026.** This scope of work is no longer maintained. Open
> work is tracked in [GOALS.md](GOALS.md); this file is kept as the evidence
> record behind those items.

Date: 24 November 2026. Companion index:
[SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md). This document is
about **where work lives**, not just what is missing. An implementation that
exists only on a branch cannot be used by agents working from `main` or
`tf1-tfo-compatibility`.

Path convention: the `.local/respawn/...` worktree and replay paths in this
document are relative to the main `C:/Users/Tristan/GitHub/MRVN-Radiant`
checkout. Closure-owned evidence cited from the other SOWs is relative to
`.local/respawn/tf1-tfo-closure`.

A follow-up isolation step on 24 November 2026 created that worktree at
`.local/respawn/tf1-tfo-closure` on branch `tf1-tfo-closure` at `25a227a`, based
on `tf1-r1-acceptance`. TF1/TFO-relevant notes and tools were copied there from
`tf1-tfo-compatibility`; TF2/Apex work, Quake-port experiments and `.claude/`
metadata stayed in the original tree. This document copy tracks the closure
evidence without changing the TF2/Apex integration worktree.

## Local branch snapshot

| Branch | HEAD at discovery | Role |
| --- | --- | --- |
| `tf1-tfo-compatibility` | `d58cc3e` | Checked-out nominal integration branch; only `57ede40` plus two Surf Beginner packaging commits beyond research. |
| `main` | `8022aef` | Upstream-facing editor base; zero unique Respawn commits and no `docs/respawn/` or `tools/respawn/`. Ancestor of every other branch here. |
| `respawn-format-research` | `e7b684a` | Broad research base (96 commits over `main`) and best TF2 base; currently also `origin/HEAD`. |
| `tf1-v29-record-validation` | `75be801` | Older patch-equivalent subset; not a viable base. Deletes `build_tf1_package.py` and its test relative to research. |
| `tf1-r1-acceptance` | `d43d43b` | R1Delta acceptance round from 21 November. |
| `apex-s3-compiler` | `709e770` | Apex Season 3 compiler re-check. |
| `worktree-agent-a3ab36d0a2ab9e330` | `679c81b` | v29 static props, pakfile, RTL slots and remaining vertex lumps. |
| `worktree-agent-a8c1fe6dd9981cfbd` | `e9adf3f` | RTL slot analyser and TF1/TF2 light-slot report. |
| `worktree-agent-a95a22bff3ad7b0d1` | `a9a3e92` | Optional TF1 physics-triangle lump writer. |

Remote-only branches with possibly relevant unmerged work:
`cleanup/remap_lumps`, `debug_dialogs`, `fixes/2026`, `opengl3`,
`portal_stubs`, `remap-refactor`, `vpk_test`, `water`, `actions_update`.

Topology: `main` → `respawn-format-research` (`e7b684a`) → `57ede40`. The
collision fix `57ede40` is the common point for `tf1-tfo-compatibility`,
`tf1-r1-acceptance` and `apex-s3-compiler`. The three agent worktrees fork
directly from `e7b684a`. `tf1-v29-record-validation` forks earlier at `53fd030`;
all 20 of its unique SHAs are patch-equivalent to research commits, but the
branch lacks seven later research patches and is not equivalent to research
HEAD. No single original branch contained all four target areas.

## One-hash integration performed 24 November 2026

A separate worktree at `.local/respawn/integration-one-hash` was created from
`tf1-r1-acceptance` at `d43d43b61e85b0097f10d41aac40df496d6a5182` on branch
`integration-one-hash`. `apex-s3-compiler` was merged with `--no-commit --no-ff`;
`tools/respawn/README.md` was the only conflict, resolved by keeping the r1 side,
adding the Apex staging row and retaining the `compiler_regression.py` row.
`b58f103` and `d58cc3e` from `tf1-tfo-compatibility` were cherry-picked with
`--no-commit` (both touch only `tools/respawn/build_surf_beginner_release.py`).
`tf1-v29-record-validation` was archived, not merged. Nothing was committed in
either worktree.

The first integrated compiler hash was
`2a8b09d9730095f8d095e0f2860e3451e5d90d77ccc65da81904a02776fcfe33`. Three
Apex-only defects were then fixed in the same worktree: exact texture-name lookup
(`compat\overlap` no longer reuses `compat\overlap_extra`), vertex-type selection
for flags `0x600` before its component bits, and a non-degenerate prop fixture.
The final one-hash compiler is
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110`.

Decisions on the remaining questions:

1. `PHYSICS_TRIANGLES` stays an optional Python post-process on the agent branch.
   It decodes and regenerates equivalent hulls, but retail bytes are not
   reproducible and no load-time native A/B was recorded. Do not enable it in
   the compiler default or carry it into the one-hash build.
2. `fixes/2026` (`5eaa964`) is rejected: the `<cstdint>` fix is already present,
   and commenting out `Shared::MakeLightmapUVs()` conflicts with the current
   conditional rewrite.
3. Remote `water` (`d51258c`) is rejected as superseded. Its brush-content and
   axial-side experiments are old; current `ApplyShaderType()` applies
   `contentFlagsClear`, and the Water/WaterBeneath shader types already clear
   `CONTENTS_SOLID` while `water`/`slime` surface pars use retail content flags.
   The one-hash suite includes the separated/sloped water fixtures.
4. Uncommitted main-tree work is intentionally preserved, not copied into the
   integration worktree: it is either audit evidence or cross-target/in-progress
   TF1-to-TF2 work. See BRANCH-02.

## Initial branch-to-feature matrix (BRANCH-01: Partial)

| Branch | Work beyond its base | Maps to | Initial disposition |
| --- | --- | --- | --- |
| `tf1-tfo-compatibility` | 2 commits after `57ede40`: `b58f103`, `d58cc3e` (Northstar and Thunderstore release packaging for Surf Beginner) | TF1-MAP-02, BRANCH-05 | Keep release scripts, but this is not the TF1 acceptance base. |
| `tf1-v29-record-validation` | 20 commits after `53fd030`: `ef4db21`…`75be801` (water, CSM, Hardpoint, navigation, shadow streams) | SOW_TF1_TFO items | **Archive, do not merge.** All 20 patches are equivalent to research work with different SHAs; the branch lacks later IVP-zero, packager, RTL lighting, sun-shadow and lightmap fixes and deletes two package tests. |
| `tf1-r1-acceptance` | 17 commits after `57ede40`: `679c81b`…`d43d43b` (static props, RTL analysis, light flags, SKY B, water pools, modes, R1 harness and acceptance round) | SOW_TF1_TFO all sections; BRANCH-03 | **Needed**; best TF1 acceptance base. Contains merges of `worktree-agent-a3ab36d0a2ab9e330` (`f8c3744`) and `worktree-agent-a8c1fe6dd9981cfbd` (`c918828`). |
| `apex-s3-compiler` | 11 commits after `57ede40`: `788a2e8`…`709e770` (r5valkyrie backend, staging tools, native regression, S0–S3 encoding, 22-bit trees) | SOW_APEX all sections; BRANCH-05 | **Needed**; must be integrated separately from TF1 output. |
| `worktree-agent-a3ab36d0a2ab9e330` | `679c81b` (v29 static props, pakfile, RTL slots, remaining vertex lumps) | TF1-MAP-01/02, TF1-LGT-01 | Needed, but already merged into `tf1-r1-acceptance`; do not cherry-pick twice. |
| `worktree-agent-a8c1fe6dd9981cfbd` | `e9adf3f` (RTL slot analyser and TF1/TF2 light-slot report) | TF1-LGT-01, TF2-LGT-01 | Needed, already merged into `tf1-r1-acceptance`. |
| `worktree-agent-a95a22bff3ad7b0d1` | `aa0cc2c`, `a9a3e92` (decode and optionally emit TF1 `PHYSICS_TRIANGLES`) | TF1-MAP-01 | Optional/experimental; not merged. The emitter is a Python post-process, not native compiler integration. Keep only if load-time measurement justifies emitting the blob. |

## Integration questions — resolved above

The branch order, optional-emitter decision, conflict handling and remote-branch
dispositions are recorded in the one-hash integration section. BRANCH-02 remains
open only because the pre-existing working-tree changes are deliberately kept
uncommitted, not because their disposition is unknown.

## Uncommitted work in the checked-out tree

`git status` at discovery showed:

- modified `docs/respawn/RESPAWN_TF1_LUMPS.md`: replaces the "crates near the
  origin" conclusion with launch-dependent TFO physics evidence. At least six
  independent launches are needed to judge a change; a single launch cannot.
- modified `docs/respawn/RESPAWN_TF1_PHASE2.md`: the matching summary correction.
- modified `tools/respawn/build_northstar_test_mod.py` and
  `tools/respawn/test_northstar_package.py`: preserve Quake `func_*` geometry
  except `func_illusionary`, convert doors/platforms/buttons to closed static
  geometry, and preserve Worldspawn liquid surfaces with TF1 Water/slime
  materials. This is an in-progress Quake-port change, not a v29 writer change.
- untracked `tools/respawn/build_tf1_quake_textures.py`: builds TF1 VTF/VMT
  trees from LibreQuake DDS outputs; ignores normal/specular inputs and depends
  on the modified `adapt_map`.
- untracked `tools/respawn/tf1_materials.py`: library converting TF1 VMT/VTF
  materials to TF2 RePak assets; no CLI entry point or tracked caller.
- untracked `tools/respawn/tf1_models.py`: recompiles TF1 MDL v52 models as
  TF2 MDL v53 with external `r2studiomdl`.
- newly added untracked `docs/respawn/SOW_*.md` and the
  `docs/respawn/README.md` link: the deliverables from this audit. Commit them
  as one planning set.
- untracked `.claude/worktrees/`: worktree metadata, not project source; do not
  commit.

**Risk:** these edits and tools are easy to lose when switching branches or
cleaning the tree. Commit them to an explicitly named branch or stash them with
a dated note before any integration work. They also cross target boundaries
(TF1→TF2 asset conversion), so keep them separate from v29 acceptance commits.

**Disposition on 24 November 2026:** all listed paths remain in their original
worktree, uncommitted, and were not copied into `.local/respawn/integration-one-hash`.
The audit SOW documents and research-note updates were copied into that worktree
after the integration; the Quake-port, TF1 texture/model/material tools and
`.claude/` metadata were not. This preserves the user's pre-existing work and
keeps cross-target experiments out of the one-hash compiler evidence.

## Integration work items

### BRANCH-01 — complete the branch-to-feature matrix — Done

The table above covers all local branches with exact SHAs and maps them to the
target documents. The three agent worktrees were checked against
`tf1-r1-acceptance`: the first two are already merged there, and the
physics-triangle branch is deliberately not merged. The one-hash worktree is a
new integration product, not an original branch.

**Acceptance met:** no unmerged feature is referred to only by branch name; each
row has a reviewed merge, cherry-pick, archive or intentional-keep decision.

### BRANCH-02 — rescue or discard uncommitted work — Partial

All pre-existing modified/untracked paths remain in the original worktree,
uncommitted. The dated rationale is recorded above; audit SOW and research-note
updates were copied into the integration worktree, but the Quake-port and
cross-target asset tools were not. No stash or commit was made on the user's
behalf.

**Acceptance:** all remaining changes intentionally kept with a dated rationale;
the one-hash worktree has its own uncommitted, integrator-owned changes. A clean
working tree or user-directed commit/stash is still required for final closure.

### BRANCH-03 — reconcile overlapping v29 agents — Done

`worktree-agent-a3ab36d0a2ab9e330` and `worktree-agent-a8c1fe6dd9981cfbd` are
already merged into `tf1-r1-acceptance`; their v29 static-prop, PAKFILE, RTL and
vertex-format changes are in the one-hash build through that base.
`worktree-agent-a95a22bff3ad7b0d1` is recorded and rejected for the compiler
default: its optional Python PHYSICS_TRIANGLES writer has only field-level
validation and no native load-time A/B.

**Acceptance met:** each branch has a unique contribution and a merge, cherry-pick
or archive decision; the one-hash build passes the v29 compiler regression set.

### BRANCH-04 — classify remote-only branches — Done

| Remote branch | HEAD | Classification |
| --- | --- | --- |
| `actions_update` | `aa914f5` | Superseded: research/main already use checkout/upload-artifact v7. |
| `cleanup/remap_lumps` | `ac1f119` | Superseded: named lump versions and `TRICOLL_TRIS` enums are already present. |
| `debug_dialogs` | `b1496e0` | Editor-only server dialog work; no map/collision/lighting changes. |
| `fixes/2026` | `5eaa964` | Rejected: `<cstdint>` fix already present; commenting out `Shared::MakeLightmapUVs()` conflicts with the current conditional rewrite. |
| `opengl3` | `ea43049` | Editor renderer WIP; not target map support. |
| `portal_stubs` | `905fc76` | Superseded/conflicting: old raw portal stubs vs. real TF1/TF2 portals and the split Apex S3 visibility backend. |
| `remap-refactor` | `b5d9762` | Incompatible 2023 layout: mass moves/deletions and `.mrvn-map` export; not integrated with research/apex. |
| `vpk_test` | `673b5ef` | Unique WIP archive-VPK plugin; possibly useful, but research uses Python VPK tooling. |
| `water` | `d51258c` | Rejected as superseded: old brush-content/axial-side experiment. Current shader types apply `contentFlagsClear`; Water/WaterBeneath clear `CONTENTS_SOLID`, and water/slime surface pars already carry the retail content flags. One-hash water fixtures pass. |

**Acceptance met:** each branch is classified; `fixes/2026` and `water` were
reviewed against current source and rejected with reasons; no still-needed fix is
left only on a remote branch.

### BRANCH-05 — one build, all targets — Partial

One compiler was built from the integrated worktree at
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110`. It passes:

- `compiler_regression.py`: 69 reports, zero issues — 37 `titanfallonline`,
  29 `titanfall2` and 3 `apexlegends` (the older 33/26/Apex counts were expanded
  with the R1 acceptance, TF2 lighting and Apex metadata fixtures). Log SHA-256
  `59A51342D428086D6933BFCE7040053942B3F2B5588538C8B3B36DA348B9ED4F`.
- Python unit tests: 316 OK.
- C++ tests: 6/6 passed with VS2022 CMake.
- Isolated TF2 compiler replay: the three lighting fixtures have identical lump
  payload hashes to the baseline build; whole-BSP bytes differ only in the
  header timestamp. Results SHA-256
  `29017908A2E67186981F6EA3AE5CC862A1845B15B5264A790A1808AE7A5AFB36`.

After the documentation sync, the same binary was re-verified: 316 Python tests
OK, 69/69 compiler reports clean with the same 37/29/3 split, and fresh TF2
replay lump comparisons returned `[]` against both the original baseline and the
recorded integration run. Re-verification evidence:
`.local/respawn/integration-one-hash-replay/full-suite-reverify.log` (SHA-256
`FA571D077B8810D8388ADF8FBBD7A7371B563039D1C0F2E2130ADFE2A9BA5DA9`) and
`.local/respawn/integration-one-hash-replay/replay-reverify.json` (SHA-256
`0A77BE5E692B0E02170BAB8A2383EB0DA3D02309BB0407CAE1765CCE2515AFBB`).

**Bounded one-hash native replays:** the 24 November closure pass recompiled four
TF1 fixtures with this hash — `mp_tf1_lighting`, `mp_tf1_vertex_formats`,
`mp_tf1_props` and `mp_tf1_masks` — with `[]` lump payload differences and paired
R1Delta/TFO sessions. The paired TFO lighting session initially failed before map
load with an `nvwgf2umx.dll` stack overflow; that was root-caused to the
installed sentry-native 0.7.8 DLL, and a local reversible patch let all four
fixtures load and finish. The original failure and patched passes are retained,
but fixture-scoped replay with a local third-party DLL patch is not a release
gate. The TFO harness path bug that made the first extended attempts stall at
the loading bar is fixed and documented in ARES; ARES adapter tests pass 197 OK,
1 skipped. Details are in
[SOW_TF1_TFO.md](SOW_TF1_TFO.md#24-november-one-hash-replay-and-offline-closure-pass-bn)
and its following TFO stack-overflow and corrected-path sections.

A separate ARES-owned Northstar profile, seeded from the pinned `R2MapHarness`
DLL and core mods, replayed `mp_mrvn_tf2light_stock` under this compiler with
`[]` lump payload differences, four captured views and no errors; the
[TF2 scope](SOW_TF2.md#integrated-compiler-replay) records the fingerprints. A
fresh dedicated R5 server replayed the Apex S3 14-check fixture under the same
binary with a new server VM and 14/14 checks passing. Results index SHA-256
`52201694ce9cdb15b61434bbd80013e4be328266f1b686dea1a1281ba4a37bae`.

On 26 November the compiler provenance gate received a scoped `E` pass. A fresh
build directory configured from the clean tracked `bd10231` source tree with
VS2022 CMake `3.31.6-msvc6`, generator `Visual Studio 17 2022` / `x64`, and MSVC
`14.44.35207` produced a raw `remap.exe` at
`3bceeb96f35b5561eb66f03c7b07ad6a0645910350ed0e584f9b86556e6cdbb6`. It differs
from the evidence binary at exactly six byte offsets: the COFF timestamp and
MSVC's repeated debug timestamp. Normalizing those non-content fields to the
evidence value `0x6b04ef61` yields
`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` exactly.
The same result was obtained from a rebuild in the original build directory.
Evidence and scripts:
`.local/respawn/clean-checkout-hash-verify-20261126/RESULT.md`. This resolves
compiler provenance without a new hash, so no report or native replay requires
regeneration. It does not close any runtime gate.

**Bounded response and breadth evidence (26 November, no gate promoted):** under
the one-hash compiler, a controlled `_ambientscale` A/B, a raw retail SKY A plane
comparison, a native SKY-A-only A/B, a native CMA-only A/B, a six-view engine
cubemap-source capture and four engine-framebuffer repeats with the HUD hidden
all recorded clean, bounded responses. CMA direction contradicts a simple
multiplier, `CRC` was not varied, `engine_decode_verified` remains `false`, and
no exposure-matched retail pair was captured, so shader-level CMA/CRC/SKY/RTL
meaning and retail brightness parity stay open. `light_spot` `"target"` aiming
has separate native `N` evidence under the current main compiler `73e7e0fa…`, not
the one-hash binary. R1Delta physics had six stable launches; TFO breadth remains
Sentry-scoped. Details are in [SOW_TF2.md](SOW_TF2.md) and the certification
matrix under `.local/respawn/certification-program-20261126/MATRIX.md`.

**Still open:** a full cross-runtime one-hash certificate has not been recorded.
The `R2Northstar` 1.31.16 label, Apex rendered-client parity, custom assets,
S0–S2, physics launch breadth, controlled image comparisons, and broader native
passes still tied to earlier hashes (especially TF2's `6daec3b2…`) remain open.
The 25 November installed-map audit adds bounded representative loads but does
not close those gates. BRANCH-05 remains Partial.
