# Scope of work: Respawn map compatibility tracker

Date: 24 November 2026. Status: **discovery and task split**, not an acceptance
certificate. This index is the entry point for agents continuing the work. It
records what the branch evidence currently supports and separates that from what
still has to be proved.

Path convention: `.local/respawn/...` paths are relative to the checkout that
owns the artifact. Integration and older branch evidence is relative to the main
`C:/Users/Tristan/GitHub/MRVN-Radiant` checkout; closure-owned evidence is
relative to `.local/respawn/tf1-tfo-closure`. Each target SOW names the closure
directories it uses.

## Purpose

Make MRVN-Radiant fully compatible with the Respawn games it targets:

- Titanfall 1 (v29 BSP) as run by R1Delta `app-3.0.5`;
- Titanfall Online (v29 BSP) as run by TFORevive.Core `135`;
- Titanfall 2 (v37 BSP) as run by the installed Northstar (CustomServers metadata
  `1.31.16`, `Northstar.dll` metadata `1.31.10-rc3`, prior native evidence
  `1.31.13`; pin by hash, not by one label);
- Apex Legends (v47 BSP) on the installed R5Reloaded Season 3 build.

"Compatible" means an authored map can be compiled, packaged with its complete
dependency closure, loaded, rendered, collided with, lit and shadowed correctly,
and played in the pinned runtime. A written lump, a passing parser, a structural
reader or a single load report is not enough. Treat the four runtimes separately
even where two of them share a BSP version.

## Evidence levels used in the child documents

Every task and finding carries the weakest evidence that supports it. Do not
promote a row without adding the next evidence level.

| Code | Meaning |
| --- | --- |
| `S` | Source or documentation only; inferred from code, a formula or an upstream note. |
| `B` | BSP structure / selected record check against extracted game files. |
| `E` | Read-only inspection of an installed engine binary or other engine file, including a recorded disassembly at a pinned hash. |
| `N` | Recorded native session (game load, ray/hull trace, capture, match behavior), with its build and limits stated. |

Each work item also has a status: **Done**, **Partial**, **Missing** or
**Unknown**. "Done" is only relative to the item's stated acceptance gate; it is
never a whole-game compatibility claim.

## Baseline and comparison inputs

The discovery compared:

- the checked-out `tf1-tfo-compatibility` branch and every other local branch,
  including three agent worktrees, plus relevant remote-only branches;
- the current working tree's uncommitted edits and untracked tools;
- installed engine/client/server binaries and game content under the paths
  recorded in [RESPAWN_MAP_SUPPORT_AUDIT.md](RESPAWN_MAP_SUPPORT_AUDIT.md#environments-and-primary-evidence);
- retail/extracted BSP corpora and retained native reports under `.local/respawn/`;
- prior research notes, especially
  [RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md),
  [RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md),
  [RESPAWN_TF1_PHASE2.md](RESPAWN_TF1_PHASE2.md),
  [RESPAWN_APEX_FORK_REVIEW.md](RESPAWN_APEX_FORK_REVIEW.md),
  [RESPAWN_TF2_TO_APEX.md](RESPAWN_TF2_TO_APEX.md), and the branch-local
  `docs/respawn/RESPAWN_APEX_S3.md` on `apex-s3-compiler`.

The hardening fork at `http://git.local/agent/rea-safe` is the intended REA
entry point for further engine-binary work, but no REA MCP server or native
analysis provider was registered in this session. Engine facts below therefore
come from the installed files, the pinned binary hashes and previously recorded
read-only disassembly, not from a new REA session. A future agent should use
REA's pinned flow to re-check any engine claim that is currently marked `S` or
`E` from a prior report, and must preserve its evidence/provenance contract.

A separate provenance finding affects every target: retained native passes are
tied to several different compiler hashes. The original TF2 evidence build
(`6daec3b2309802af6ecfd17d2635a8a7e693b07d59325094c2dd1fcebf81ff94`; previously
`fba9223da8efaddb96a7adbc35534335ba4597a5e74dd189f9af2160ea4ccc51`) was used for
the 24 November native TF2 captures. A one-hash integration worktree now builds
as `b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110` and passes
all 69 compiler reports (37 v29, 29 v37, 3 Apex), 316 Python unit tests and six
C++ tests. Its isolated TF2 compiler replays have lump payloads identical to the earlier
build; only BSP header timestamps differ. Four TF1 fixtures replayed under that
hash (lighting, vertex formats, props and masks) matched all lump payloads and
passed paired R1Delta/TFO sessions with the local Sentry patch. The first paired
TFO session initially crashed before map load in `nvwgf2umx.dll`; that was
root-caused to the installed sentry-native 0.7.8 DLL, and a local reversible
patch let all four fixtures load and finish. The failing evidence and the
wrong-`--maps`-depth stalls are retained; see
[SOW_TF1_TFO.md](SOW_TF1_TFO.md#24-november-one-hash-replay-and-offline-closure-pass-bn)
and its TFO stack-overflow and corrected-path sections.

Bounded one-hash native sessions now also exist for TF2/Northstar and Apex/R5.
An ARES-owned profile seeded from the pinned `R2MapHarness` DLL and core mods
loaded `mp_mrvn_tf2light_stock` with four views and no errors, and a dedicated
R5 server passed 14/14 Apex S3 fixture checks with a fresh server VM. These do
not test the `R2Northstar` 1.31.16 label, Apex rendered-client parity, custom
assets, S0–S2 or a clean-checkout rebuild. Results index SHA-256
`52201694ce9cdb15b61434bbd80013e4be328266f1b686dea1a1281ba4a37bae`. Native
claims still stay bound to their recorded build and Sentry DLL state. No
branch's evidence may be claimed as a certificate for another branch's binary.
Record hashes before and after integration; see each target document for
installed engine hashes and version-label conflicts.

## Current headline assessment

| Target | Map support | Collision | Lighting and shadows |
| --- | --- | --- | --- |
| TF1 / R1Delta | Partial: authored v29 maps load; 21 November acceptance lives on `tf1-r1-acceptance`; one-hash R1 replay passes for lighting, vertex formats, props and masks; packaging, asset closure, human gameplay and nav remain gated | Partial: R1 physics/props/modes sampled on that branch; TFO physics remains launch-dependent; one-hash masks replay covers 16 trace and 16 hull cases | Partial: bake, RTL, SKY A/B, probes, opaque and cutout shadow streams implemented; visual parity and stability open |
| TFO | Partial with Core135 content/mode overrides; separate runtime, not a free extension of R1; one-hash TFO replay passes four fixtures with a local Sentry DLL patch, while the stock-DLL failure and wrong-path stalls are retained | Same writer, same sampled traces and normalized events for four fixtures; crate drops and water remain conditional | Same writer; TFO has the stronger recorded shadow-stream evidence, with startup and image-comparison limits |
| TF2 / Northstar | Most mature: v37 maps load/play in recorded Northstar runs; 24 November compiler smoke map reloaded cleanly in the 1.31.13 harness profile and again under the one-hash compiler in an ARES-owned copy of that pin; closure and all modes open | Partial/strongest: brush, bevel and patch collision natively sampled; bevel selection and broad traversal open; one-hash smoke replay repeats the two floor traces | Partial: baked maps play; probes, cubemaps, CSM and alpha shadows emitted; roof/sun/realtime-light, one-light-class-per-room and two-environment native capture sets pass load/render/shutdown; one-hash smoke replay adds four bounded views but no image comparison; opaque/alpha shadow emission is structurally certified and the alpha map loads cleanly, but runtime shadow contrast is not resolved; CMA, cubemap selection, brightness parity and full visual parity open |
| Apex / R5 S3 | Partial: S3 backend is integrated into the one-hash compiler and loads a fixture room and `mp_box` in the retained rendered-client evidence; a dedicated-server fixture now also loads under that exact binary; other seasons and custom assets unproven | Partial: 14/14 native fixture traces and prop sun shadows pass on the earlier branch build and 14/14 dedicated-server checks pass under the one-hash compiler; water, movers, large multi-cell culling and exact BVH parity open | Partial: S3 world lights, RGBM lightmaps, RTL, probes and CSM are implemented, integrated and render in the retained client evidence; one-hash replay is collision/script-only with no client lighting check, so cubemaps, alpha shadows, character lighting and bake quality remain open |

## Documents

- [Branch integration and uncommitted work](SOW_BRANCH_INTEGRATION.md): which
  branch owns which change, what must be reconciled before a single build can
  claim all targets, and what is currently stranded outside commits.
- [Titanfall 1 and Titanfall Online](SOW_TF1_TFO.md): v29 map, collision,
  lighting/shadow and release work, with paired runtime gates.
- [Titanfall 2](SOW_TF2.md): v37 map, collision, lighting/shadow and packaging work.
- [Apex Legends](SOW_APEX.md): v47/S3 map, collision, lighting/shadow and runtime work.

## Rules for agents

1. Work from a pinned target: record engine/build hashes, game version, map
   hashes, compiler hash, worktree/branch and command before claiming a result.
2. Keep retail payloads, credentials and private reports out of Git. Reference
   ignored `.local/respawn/` artifacts by path and hash.
3. Record source URL/revision, lump index/version, offsets, sample hashes and
   validation level for every new schema. Distinguish observation, derivation,
   inference and unknown.
4. Retain failing cases. A late bad TFO launch or a rendered-client crash is
   evidence, not noise to be dropped from a report.
5. Close items by satisfying the stated acceptance gate in the relevant runtime;
   update the item's status and evidence code in the same change that adds the
   implementation or test.
6. Do not merge a branch-only feature into another target by lump number alone.
   Apex shares label names with TF2 but not a verified schema or engine behavior.
