# Titanfall map support audit - 17 November 2026

Later checkpoint on the same date: [navigation export/integrity](RESPAWN_TF1_NAVIGATION.md)
adds a bounded exporter/offline CRC workflow, two paired grunt route fixtures and
live R1/TFO CRC observations. It supersedes the navigation automation limit below;
this audit retains its original scope and does not claim full Phase 2 completion.

## Result and scope

**Titanfall 2 / Northstar has the most mature playable custom-map path. Titanfall
1 / R1Delta and Titanfall Online have working, partially verified v29 authoring
paths. None has demonstrated full retail feature or release parity.**

This audit checks the current local compiler source, installed engine/game files,
extracted BSPs, and retained native reports. It reruns structural and compiler
checks; it does **not** launch new game sessions. Runtime statements below refer
to earlier recorded tests, with their controls and limitations retained. A
successful parser, a load report, and a complete playable match are different
evidence levels. No defensible overall compatibility percentage is available:
there is no complete, weighted acceptance suite for these targets.

## Environments and primary evidence

Audited compiler source: MRVN-Radiant `6a99fd41fc773531ff131efff5f954e96a6a870b`.
ARES adapters/evidence: `8b1c08b196d454a90e2d0e684dd5a49e5b8c7916`.
The existing local edit to `build_source_ports.py` is outside this audit.

| Target | Local installation/build | Boundary of the claim |
| --- | --- | --- |
| TF1 / R1Delta | `D:/Games/Titanfall`; R1Delta `app-3.0.5` | Modified R1Delta runtime; unmodified retail matchmaking and other builds are untested |
| TFO | `D:/Games/Titanfall Online`; `TFORevive.Core/mod.json` version `135` | Core135 with the content mods and explicitly reported harness overrides; separate from R1Delta |
| TF2 / Northstar | `C:/Games/Titanfall2`; `gameversion.txt` = `v2.0.11.0`; Northstar.CustomServers metadata = `1.31.15` | Existing compiler/runtime evidence includes Northstar 1.31.13; this audit does not turn it into a fresh 1.31.15 pass |

Windows version metadata on the installed Northstar DLL says `v1.31.10-rc3`,
which differs from the mod metadata. Use hashes and report-specific versions
rather than silently treating either label as an independently verified release.
No authentication, anticheat, installed files or unowned processes were changed.

Selected SHA-256 fingerprints, read again during this audit:

| File | SHA-256 |
| --- | --- |
| `install/Release/remap.exe` | `128e474f734f433dde107e3c1a509b0b835714eb153664a843c2bb0b2e70fbd2` |
| R1Delta `r1delta/bin/server.dll` | `50faad928e0715a51ad624d0a3eb8f00f7ffad9e66258dc95c960f9d11ff41e4` |
| TFO `Bin/engine.dll` | `39e2a1c83b7bea3fa1a2f98ecc6cde3016e3567a1bc89cf8926d8a613dc62ad1` |
| TFO `Bin/server_local.dll` | `8dabdd4f46218bdd72bd9c4ea53d24178c7974ec4277f6872f671ac1fe99dd7b` |
| TF2 `bin/x64_retail/engine.dll` | `58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487` |
| TF2 `bin/x64_retail/client.dll` | `002b36487fec7c98882929fbccdb506d0146bbf3270cbb964a4d21c5edf7eebc` |
| TF2 `Northstar.dll` | `2e61dcc0985bae364fa2c2fac91dbea3578bff73748cac5f22e036038a06ed50` |

The TF2 engine/client fingerprints match the independently audited profile in
[RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md) and the prop-reference investigation
in [RESPAWN_DECOMPILE.md](RESPAWN_DECOMPILE.md). That profile checks world-index
capacity and object-reference alignment; it does not certify every engine path.
The read-only R1Delta source checkout is at
`c48f0003cddc5ba3af99baa415cb5b885764f84f`; `engine/core/load.cpp` gates native
AIN initialization behind launch flags, and `server/ai/navmesh.cpp` implements
`updateain`. This confirms the dependency behind the recorded navigation test;
it does not prove that the supplied binaries were built from this exact commit.

## Fresh corpus and writer review

`inspect_bsp.py` and `validate_records.py` pass **31/31 files**, with no reported
directory or selected-record issues. Default external lump overrides are included.
This is a selected corpus, not every map shipped by each game.

| Corpus | Files / distinct main BSP hashes | Maps |
| --- | --- | --- |
| TF1 v29 | 6 / 5 | Angel City retail and identical supplied beta, Colony, Fracture, Lagoon, Relic |
| TFO v29 extracted assets | 17 / 17 | Airbase, Angel City, Boneyard, Box, Fracture, Haven, Lobby 02, Mia, Nest2, Nexus, NPE, Outpost 207, Relic, Runoff, Sandtrap, Smugglers Cove, Swampland |
| TF2 v37 | 8 / 8 | Angel City, Coliseum, Colony02, Glitch, Homestead, Live Fire Stacks, Lobby, Relic02 |

Ten available detailed extraction manifests also match their current source VPK
directory hashes and all 751 listed BSP/sidecar/entity payload hashes. Other
samples lack that complete manifest evidence. The TFO extracted dump is hashed
and checked as supplied; its original archive provenance was not reconstructed.
The separate converter output is modified and was excluded as a retail oracle.
Main BSP equality alone never establishes sidecar or runtime equivalence.

Source counting uses `lump_names.h`, `titanfall/titanfall.cpp` and
`titanfall2/titanfall2.cpp`: distinct `AddLump` destinations plus the separately
serialized `GAME_LUMP`. Conditional branches count once; a write site does not
prove field semantics or mean every map fills that lump.

| Structural measure | TF1 / R1Delta | TFO | TF2 / Northstar |
| --- | --- | --- | --- |
| Compiler target / BSP | `titanfallonline` / 29 | `titanfallonline` / 29 | `titanfall2` / 37 |
| Explicit payload write paths / named lumps | 70/75 | 70/75 | 74/81 |
| Unwritten named lumps empty throughout that target's corpus | 4 | 4 | 7 |
| Unwritten named lumps populated in the corpus | 1 | 1 | 0 |
| Surveyed named-lump representation, including agreed empty lumps | 74/75 (98.7%) | 74/75 (98.7%) | 81/81 (100%) |
| Selected fixed-record schemas / explicit write paths | 61/70 | 61/70 | 44/74 |

These percentages describe **surveyed lump representation only**. Empty lumps,
conditional fallbacks, approximate algorithms, and a complex gameplay feature all
have very different significance. The schema totals exclude variable-length
parsers and do not express validation completeness.

TF1/TFO do not emit `PHYSICS_TRIANGLES`, populated in all 23 sampled v29 files.
The existing investigation identifies precomputed virtual-mesh hull data; the
engine can build it at load, so omission is not itself evidence that maps cannot
play. Load-time/performance equivalence remains unverified. Their other four
unwritten names are `PHYSICS_LEVEL` and `VERTEX_RESERVED_5-7`, all empty here.
TF2 additionally leaves `LEAF_WATER_DATA` and `WORLD_LIGHT_PARENT_INFOS` empty;
all seven omitted names are empty in its eight samples.

Reviewing `_stub` names alone would misclassify the source: visibility generation
replaces shared placeholder vectors, while lighting has conditional baked and
fallback paths. Conversely, writing a generated record cannot establish its
retail semantics. The v29 realtime-light fallback is unshadowed; TF2 cubemap CMA
values and mesh cubemap selection remain approximations. See the
[TF1 notes](RESPAWN_TF1_LUMPS.md), [TF2 notes](RESPAWN_TF2_LUMPS.md),
[lighting](RESPAWN_LIGHTING.md) and [collision/portals](RESPAWN_TRICOLL_PORTALS.md).

## Practical feature support

"Sampled" means the specific recorded fixture passed. "Implemented/partial" means
there is code or structural evidence, with material runtime acceptance still open.
None of the rows claims arbitrary-map equivalence.

| Feature | TF1 / R1Delta | Titanfall Online | TF2 / Northstar |
| --- | --- | --- | --- |
| Author brush/patch maps, compile and load | Sampled authored v29 maps start; camera/spawn requirements apply | Sampled authored v29 maps start under Core135/content setup | Most mature path; authored and converted maps load/play in recorded Northstar runs |
| Materials, render meshes, props | Sampled; target dependencies must be mounted/packaged | Sampled; different mounted content from R1 | Custom VPK/RPak/STBSP map recipes and rendered maps; arbitrary material/model parity open |
| Pilot movement, brush/patch collision, triggers | Paired ray/hull/mask/transform tests and one standing forward-input trigger crossing | Same selected checks; runtime-specific fixes retained | Recorded displacement-floor and brush/triangle sweeps; broad traversal/combat acceptance open |
| Physics and water | Sampled dry support/buoyancy; packaged Water shaders render surfaces; underwater horizon artifact remains | Sampled dry support/buoyancy and one underwater geometry/fog scene | Generated collision/render data and map trials; no comprehensive water/physics acceptance matrix |
| Lighting, shadows, reflections | Bake/conversion/fallback data implemented; visual and realtime-light equivalence partial | Same writer, separate visual acceptance remains partial | Baked maps play; probes/shadows/cubemaps implemented; CMA, cubemap selection and full visual equivalence remain open |
| Visibility and occlusion | Generated cells/portals; structural checks, incomplete native culling proof | Generated cells/portals; same qualification | Native 1,022-cell / 6,970-directed-portal stress fixture passed selected traces/views; full culling parity and runtime areaportal switching open |
| Spawns and objectives | Sampled spawn/trigger, Hardpoint initialization and neutral capture/score gain | Same bounded pass **with temporary dialogue/sound fixes**; unmodified Core135 controls fail | Custom pilot gameplay/map scripts exist; no full all-modes acceptance certificate |
| Navigation, AI and titans | One native grunt obstacle route with staged exported AIN; one atlas NPC floor-support sample | Same route and support sample; CRC internals not independently checked | No general automatic navmesh/AI/titan solution established by this compiler audit; some shipped recipes explicitly pilot-only |
| Import/recovery and cross-game ports | Bounded inspection and partial recovery; no arbitrary lossless editable conversion claim | Shared format does not translate scripts/assets/objectives automatically | Opaque preservation and bounded editable scene recovery work for selected maps; original lighting/topology/assets are not fully reconstructed |
| Packaging/editor/release workflow | Controlled staging and shader VPK helper; complete dependency closure/integrated clean release open | Controlled mod staging; content/setup/compatibility overrides remain required | Reproducible map/mod package recipes; clean dependency closure, all editor paths, sustained multiplayer and every mode unproven |

R1Delta needs an `info_intermission`; the compiler creates one when a pilot spawn
exists. Its tested coordinate envelope is +/-16384. A water VPK must contain the
tested `water_ps40.vcs`/`water_vs40.vcs` pair; loose copies did not suffice.
The underwater artifact also appears in recorded retail controls, so it is not
proven to be solely a compiler defect.

TFO tests enable `Titanfall1.Content.Client` and `Titanfall1.Content.Shared`.
Core135 Hardpoint needs explicitly reported temporary duplicate-dialogue fixes
and repair of the supplied sound definition. Alias/path checks do not establish
waveform availability or audible playback. These passes are conditional support,
not unmodified-Core compatibility.

Navigation passes require a native-built exported v54 AIN and controlled NPC
settings. R1's private graph copy uses its engine-computed entity CRC; general
offline CRC/export automation is unresolved. No moving the NPC after spawn was
used in the final route, but only sampled positions were checked. Other hulls,
routes, combat, default animations and titan piloting remain open.

## Runtime evidence and fresh validation

Retained paired final reports checked during this audit include navigation
(`phase2-navigation/{r1,tfo}-public-api/report.json`), Hardpoint neutral capture
(`phase2-cp-capture-public/{r1,tfo}/report.json`), mask checks
(`phase2-mask-repro-final/{r1,tfo}/report.json`), standing trigger traversal
(`phase2-trigger-walk/{r1-long,tfo-long}/report.json`) and atlas support
(`phase2-titan-public/{r1,tfo}/report.json`). These selected final reports have
`loaded=true`, `finished=true`, and no reported errors. Earlier failures remain
in the same private evidence tree and in the [Phase 2 log](RESPAWN_TF1_PHASE2.md).
A generic finished report alone is not evidence that every tested behavior passed;
the log and feature-specific assertions define the result.

The TF2 native portal report is
`.local/respawn/tf2-visbudget-native/report.json` (4 November, Northstar 1.31.13).
Recorded map trials and lighting/collision investigations provide additional
bounded evidence. This audit has not replayed those sessions or certified a
fresh clean-install multiplayer run.

Fresh commands/checks on 17 November:

- `python -m unittest discover -s tools/respawn -p 'test_*.py'`: **261 pass**.
- `python tools/respawn/compiler_regression.py --remap install/Release/remap.exe --work-dir .local/respawn/support-audit-20261117/compiler`:
  **60 reports pass**, comprising 33 v29, 26 v37 and one out-of-scope Apex regression.
- Read-only corpus/source review calls `inspect_bsp.inspect`,
  `validate_records.validate` and recounts destinations in the two writers:
  **31 BSPs pass**, counts as above.
- SHA-256 fingerprints and extraction-manifest comparisons as described above.
- `audit_tf2_budget.py` on the fresh v37 regression BSP against the installed
  `engine.dll`: exact profile match, 180 estimated padded world indices of
  3,145,728, six material sorts, no issues. This tiny fixture verifies the check
  path; it does not establish production-map capacity or performance.

Private machine-specific script, corpus, provenance, binary and compiler reports
are in ignored `.local/respawn/support-audit-20261117/`. No retail payloads,
screenshots, account logs or credentials are included in this documentation.

## Work required before claiming full support

1. Broaden curved/edge/transformed collision, moving props, multiple/sloped water
   volumes, submerged props, actual projectiles and piloted titans; retain failing
   cases and verify all three runtimes independently.
2. Close visual lighting, realtime-light, shadow, reflection and culling acceptance;
   resolve/classify the R1 water artifact and TF2 approximations.
3. Automate per-target navigation generation/integrity; test more hulls and routes,
   dynamic obstacles, AI combat and titan movement.
4. Test contested/recapture objectives, deaths/respawns, other modes, audio playback,
   human multiplayer, repeated cold loads and sustained matches. TFO's current
   Hardpoint overrides must become an explicit supported configuration or be fixed
   upstream before an unmodified-Core claim.
5. Verify clean package dependency closure for custom materials/models/textures,
   streaming data and shaders, then demonstrate a repeatable editor-to-game release
   workflow on explicitly pinned builds.

A map can be useful and playable before those gates close. The current practical
assessment is **TF2: usable custom-map support with substantial remaining parity
limits; R1Delta: experimental playable support; TFO: experimental playable support
with additional configuration and mode-specific compatibility fixes**.
