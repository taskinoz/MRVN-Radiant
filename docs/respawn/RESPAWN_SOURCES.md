# Respawn research and tooling attribution

MRVN-Radiant builds on GtkRadiant, NetRadiant and NetRadiant-custom; their original
copyright/license notices and `CONTRIBUTORS` remain part of the project. Respawn
Entertainment created the game formats. Credit community reverse engineering
contributors alongside any implementation derived from their work.

## References used in the initial inventory implementation

Consulted 2026-10-07. The inventory is an original standard-library
implementation; no upstream implementation or third-party dependency is bundled.

- **snake-biscuits and bsp_tool contributors:**
  [bsp_tool](https://github.com/snake-biscuits/bsp_tool), specifically
  [respawn.py](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/respawn.py),
  [titanfall.py](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/branches/respawn/titanfall.py),
  [titanfall2.py](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/branches/respawn/titanfall2.py), and
  [apex_legends.py](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/branches/respawn/apex_legends.py).
  Research informed header/version detection, external-lump naming and entity
  header inventory. Repository declares GPL-3.0. These moving-branch references
  record the research consulted, not a pinned dependency; pin an exact commit
  and review its license before importing code.
- **Existing MRVN-Radiant contributors:** `tools/remap/source/games.h` and
  `lump_names.h` supply the local header and compiler lump-name definitions.

## Tooling register supplied for this project

The following tools and their authors are acknowledged as candidate integrations
or research references. Listing a tool does not mean it has been integrated or
verified against all targets. For tools not yet incorporated, exact revision,
license, supported asset types and game builds must be recorded at integration.

| Project and attribution | Intended role |
| --- | --- |
| [MRVN-VMT — MRVN-Radiant contributors](https://github.com/MRVN-Radiant/MRVN-VMT) | VMT to Radiant shader conversion |
| [rsx — r-ex contributors](https://github.com/r-ex/rsx) | Model/material/texture extraction research |
| [tf2vpk — pg9182 and contributors](https://github.com/pg9182/tf2vpk) | Titanfall 2 VPK extraction/creation adapter candidate |
| [TFVPKTool — barnabwhy and contributors](https://github.com/barnabwhy/TFVPKTool) | TypeScript VPK implementation reference |
| [vpk_qt — Mauler125 and contributors](https://github.com/Mauler125/vpk_qt) | Apex VPK tooling reference |
| [r5vpk — r-ex contributors](https://github.com/r-ex/r5vpk) | Apex VPK tooling reference |
| [RePak — r-ex contributors](https://github.com/r-ex/RePak) | RPak compilation; commit `adc52f7` (MIT) builds the Quake test material pak, unmodified apart from a local include-path quoting fix in its project file |
| [ABStream — RoyalBlue1](https://github.com/RoyalBlue1/ABStream) | STBSP renderer and creator; candidate for real texture-streaming columns (no licence file) |
| [LightMapExtractor — RoyalBlue1](https://github.com/RoyalBlue1/LightMapExtractor) | Titanfall 2 lightmap and realtime-lightmap extraction (MIT); cross-check for baked SKY/RTL planes |
| [BSPTricollMeshExport — RoyalBlue1](https://github.com/RoyalBlue1/BSPTricollMeshExport) | Triangle-collision mesh export; reference for unimplemented tricoll emission (no licence file) |
| [SERE](https://github.com/RoyalBlue1/SERE) / [RuiTemplate — RoyalBlue1](https://github.com/RoyalBlue1/RuiTemplate) | RUI element editor (AGPL-3.0) and RUI library template; loading screens and map UI |
| [Modelshop — IJARika](https://github.com/IJARika/Modelshop) | Respawn MDL/RMDL parsing and extraction; static-prop import research |
| [r5sdk](https://github.com/Mauler125/r5sdk) / [Apex-Material-Converter — Mauler125](https://github.com/Mauler125/Apex-Material-Converter) | Apex engine SDK and material shader-data conversion between engine versions |
| [LibreQuake — LibreQuake contributors](https://github.com/lavenderdotpet/LibreQuake) | BSD-3-Clause textures (commit `4d2da52`) for the Quake test mod; licence shipped as `LICENSE-textures.txt` |
| [apex-to-titanfall-2 — taskinoz](https://github.com/taskinoz/apex-to-titanfall-2) | Material template, STBSP and probe/shader research reimplemented in `rpak.py`, `stbsp.py` and `lightbake.h` |
| [bsp_tool — snake-biscuits and contributors](https://github.com/snake-biscuits/bsp_tool) | BSP schema and analysis research |
| [breki — snake-biscuits and contributors](https://github.com/snake-biscuits/breki) | Map reverse engineering research |
| [bsp_regen — snake-biscuits and contributors](https://github.com/snake-biscuits/bsp_regen) | Titanfall map conversion research |
| [titanfall_map_converter — p0358 and contributors](https://github.com/p0358/titanfall_map_converter) | Earlier conversion implementation and provenance |
| [respawn_cubemap_tool — snake-biscuits and contributors](https://github.com/snake-biscuits/respawn_cubemap_tool) | Titanfall 2 cubemap extraction research |
| [Titanfall2-DDS-Tool — Nekailrii and contributors](https://github.com/Nekailrii/Titanfall2-DDS-Tool) | Texture/streaming conversion research |
| [r5bsp-viewer-cpp — mrsteyk and contributors](https://github.com/mrsteyk/r5bsp-viewer-cpp) | Apex map decoding/rendering reference |
| [UnCSO2 — lateleite and contributors](https://github.com/lateleite/UnCSO2) | Titanfall Online PKG browsing/extraction; credits ekey's reversing work |
| [libuncso2 — harmonytf and upstream contributors](https://github.com/harmonytf/libuncso2) | Titanfall Online archive backend/decryption research |

RePak, tf2vpk and rsx repository descriptions were reviewed during the initial
audit. Subsequent tf2vpk corpus use is recorded below; RePak and rsx integration
and build-specific compatibility remain unverified.

## Tools actually used for local corpus work

- **pg9182/tf2vpk**, commit
  `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff`, MIT, copyright 2022 pg9182.
  Built locally using its `go.mod`/`go.sum` and used through `list`/`get` to
  extract the seven maps in [RESPAWN_SAMPLES.md](RESPAWN_SAMPLES.md). Its original
  license and source are retained under `.local/respawn/upstream`. The binary and
  third-party dependencies are not committed or redistributed. The original
  adapter `tools/respawn/extract_maps.py` invokes the executable; it contains no
  copied tf2vpk implementation. Retail/beta R1 extraction used `nosanitycheck`
  for upstream texture-flag constraints; CRC checks remained enabled. All other
  samples used default checking.
- **bsp_tool**, Titanfall/Titanfall 2 schema research: used to cross-check observed
  lump versions for the original `respawn/lump_versions.h` mapping and writers.
  The header mapping records binary format facts; no upstream parser was copied.
  Its [Titanfall schemas](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/branches/respawn/titanfall.py)
  and [Titanfall 2 schemas](https://github.com/snake-biscuits/bsp_tool/blob/master/bsp_tool/branches/respawn/titanfall2.py)
  also informed the original `tools/respawn/validate_records.py`: brush-side
  addressing, vertex-pool selection, material-sort-relative indices and mesh
  bounds; later checks include collision grid/cell/geo-set/primitive references
  and the separate R2 mesh byte layout. Grid ordering comments were checked
  against 31,951 direct-brush references in retail Angel City: X-fast ordering
  had no XY intersection mismatches, while Y-fast had 31,947. The existing
  compiler order was retained. These relationships were checked against local maps. No implementation
  was imported; these are research links, not pinned software dependencies.
- **MRVN-Radiant/MRVN-WinDeps v0.2**: official `windeps.7z` and `install.7z` used
  locally to compile and run remap. These dependency artifacts remain ignored,
  with their original files intact.
- **UnCSO2 and harmonytf/libuncso2**, GPL-3.0 repositories: README documentation
  consulted for Titanfall Online PKG extraction/decryption capabilities and ekey
  research attribution. No code was imported and no PKG decryption was needed for
  the already extracted map corpus. Review per-file notices (including Valve's
  LZMA-related files) before any future integration.

## Known-map and decompilation trials

- **id Software / John Romero Quake map source release**, retrieved through
  **fzwoch/quake_map_source**, commit `27abebaa3886bb0e3156cce3a604673d22b243f8`.
  E1M1 was used unchanged for a Titanfall 2 compile trial; GPL-2.0 COPYING and
  the upstream README remain in the ignored source checkout. COPYING also
  accompanies the local trial map. Replacement WAD textures were not imported.
- **snake-biscuits/bsp2gltf**, commit `1057d0c19e5689e2eeccf95f6ca845e34a9b1924`:
  locally built and used to export Coliseum's world render meshes. No license
  file is present at that revision; no source or binary is incorporated or
  bundled. Raw output was preserved alongside separately repaired glTF output.
  Original materialization/postprocess scripts and validation evidence are
  described in [RESPAWN_MAP_TRIALS.md](RESPAWN_MAP_TRIALS.md).
- The new collision `.map` recovery code is original; its plane/addressing facts
  use the bsp_tool research already credited above. It does not derive code from
  bsp2gltf and does not claim full render/entity recovery.

## Required provenance for incorporated work

The original Northstar test adapter and uncompressed VPK writer are documented in
[RESPAWN_NORTHSTAR_TEST.md](RESPAWN_NORTHSTAR_TEST.md). The adapter removes Quake
entities, folds brush entities into world geometry and adds pilot spawns. Its
distributable includes original/adapted MAP source and GPL COPYING. VPK layout
facts and independent CRC/byte readback use the pinned pg9182/tf2vpk revision
credited above. Northstar's mod manager and official mod/RPAK documentation were
consulted for mounting and asset aliases; no Northstar implementation was copied.
The package uses installed Coliseum materials through an alias and includes no
Respawn RPAK assets. Engine compatibility remains unverified.

NorthstarLauncher commit `42c635aef4929a8c8eaf4ee790efb6fa34ac56cc` (MIT) was
inspected locally for `primedev/util/printmaps.cpp` and filesystem mounting.
Its map discovery ignores maps within mod VPKs and enumerates loose `mod/maps`
BSPs. This informed the original adapter's 0.1.1 packaging fix, adding identical
loose map/entity members. No Northstar implementation is incorporated or bundled.

The local Northstar 1.31.13 `sh_menu_models.gnut`, `_lf_maps_shared.gnut` and
`_classic_mp_dropship_intro.gnut` were inspected for menu anchor names, the
no-intro API and the empty intro-dropship failure. The installed lobby entity
partition informed the `info_target_clientside` / `script_name` schema; only
schema facts are used with newly placed anchors, not a copied map partition.
The 0.2.0 builder's map filtering and removal of foreign lighting references are
original. Installed Coliseum names informed replacement concrete/wall materials;
no material images or Respawn asset files are distributed.

Lighting schema/plane facts were checked against **snake-biscuits/bsp_tool**,
commit `655627ea8704353ac14bd753df8ca05c15838eda` (GPL-3.0), including its Respawn
branch definitions and `bsp_tool/lightmaps/titanfall*.py`. This informed original
inspection, point-light record emission, controlled atlas probes and offline
direct-light tools. No GPL-3.0 implementation was copied or incorporated; the
research checkout stays ignored. Local TF1 Angel City and TF2 Coliseum/Glitch
provide byte-size/layout evidence. See [RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md)
for attribution, results, encoding uncertainties and engine-validation limits.

Gravemind's `games/respawn/maps` conversion research was read on 11 October 2026.
Document IDs, revisions, recorded authors, source workspace references and local
engine cross-checks are retained in [RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md).
Technical findings inform an original read-only TF2 budget auditor and future
lighting/material/collision work. No conversion source, game assets, or access
credentials were copied into the project.

TF2 GAME_LUMP/sprp work (22 October 2026) uses original code with schema facts
cross-checked against local native structs, Gravemind binary-formats revision 2,
and snake-biscuits/bsp_tool commit `655627ea8704353ac14bd753df8ca05c15838eda`
(GPL-3.0). Upstream layout credits include BobTheBob and DTZxPorter. No upstream
parser implementation was copied. The five-map retail measurements, conditional
lighting-origin evidence, affected tools and limitations are recorded in
[RESPAWN_GAME_LUMP.md](RESPAWN_GAME_LUMP.md).

TF2 tricoll and portal continuation (24 October 2026) uses the inherited
NetRadiant brush BSP/portal routines with original Respawn serialization and
Python inspection. Schema facts were cross-checked against the pinned bsp_tool
revision above, Gravemind collision revision 4 / binary-formats revision 2 /
visibility-and-limits revision 3, retail Coliseum/Glitch records and independent
native loader/triangle disassembly. No converter or GPL-3.0 implementation was
copied. Record evidence, source identities, local tests and remaining runtime
limits are in [RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md).

BobTheBob's manually ported `mp_box` was audited against the user's matching
Titanfall Online v29 source on 24 October 2026. Original bounded repair and
native-baker adapter code restore prop fields and fix ZIP/lighting records;
BobTheBob retains port credit and Respawn/Nexon retain map/asset credit. The
pinned bsp_tool v12/v13/probe schemas above were consulted as format references;
no implementation was copied. Existing tf2vpk verified retained VPK members.
Evidence, native smoke results and limits are in
[RESPAWN_MP_BOX.md](RESPAWN_MP_BOX.md). Game/mod assets remain local and ignored.

TF2 scene recovery (25 October 2026) adds an original entity parser, RSM1 render
interchange, preservation rebuilder and native comparison fixtures. The pinned
bsp_tool schema reference above informed record interpretation; no implementation
was copied. Existing NetRadiant compilation and Assimp preview imports retain
their notices. The pinned MIT tf2vpk tool extracted local Coliseum/lobby samples.
BobTheBob retains mp_box port credit; Respawn/Nexon retain map/asset credit.
See [RESPAWN_DECOMPILE.md](RESPAWN_DECOMPILE.md) for exact scope and test evidence.

TF1 VPhysics VMT patch resolution uses an original targeted parser. Patch include,
insert and replace behavior was cross-checked as a format reference against Valve's
[Source SDK 2013 materialpatch.cpp](https://github.com/ValveSoftware/source-sdk-2013/blob/019e91ccd650a34745934c65cdbbe89ffcc44ede/src/utils/vbsp/materialpatch.cpp)
(commit `019e91ccd650a34745934c65cdbbe89ffcc44ede`, Valve Source SDK license).
No upstream code was incorporated. The compiler fixture checks emitted triangle
material assignments; TFO-specific KeyValues and patch parity remain unverified.

Visibility cell merging and budget clustering (4 November 2026) are original
GPL-2.0-or-later code in `respawn/convex_cells.h` and `titanfall2_portals.cpp`,
over the inherited NetRadiant BSP/portal builder. Native cell-mask limits were
independently inspected in local TFO/TF2 client binaries; their hashes and RVAs
are in [the collision/portal notes](RESPAWN_TRICOLL_PORTALS.md). No binary,
disassembly, extracted map or external implementation is distributed.

The swept box/capsule references and patch/brush comparison fixtures
(4-5 November 2026) are original GPL-2.0-or-later mathematical/test code in
`tools/respawn/swept_{box,capsule,patch_test}.py`. They use continuous separating
axes and convex distance minimization, with no external implementation copied.
The TF2 script hull setup was independently inspected in the locally installed
server binary. Its hash, addresses, native results, and unresolved differences
are recorded in [the collision/portal notes](RESPAWN_TRICOLL_PORTALS.md).

Exact convex CM brush merging (5 November 2026) is original GPL-2.0-or-later
code in `respawn/convex_brushes.h` and `titanfall_collisions.cpp`. It uses the
existing NetRadiant brush-winding builder after an original half-space union
check. Render/IVP source brushes remain intact. Native TFO seam checks and
cross-game sweep evidence are recorded in the collision/portal notes.

CM brush bevel output (5 November 2026) reuses this project's inherited
NetRadiant `AddBrushBevels` algorithm in `map.cpp`, parameterized for collision
copies and bounded generation. Generated sides inherit source material/mapping;
`titanfall_collisions.cpp` writes separate non-discard/total counts and the
native discard suffix. This is GPL-2.0-or-later work with the inherited notices
retained. Retail count/flag checks, independent SAT/half-space comparisons and
native crease evidence are recorded in the collision/portal notes. Experimental
triangle selectors remain local diagnostics, not adopted compiler algorithms.

Triangle bevel serialization (5 November 2026) is original GPL-2.0-or-later
code in `respawn/tricoll_bevels.h`. It implements the direct/chained layouts
already documented above, without copying an external implementation. The C++
serializer was checked against independently decoded local retail references;
counts, capacity tests and native evidence are in the collision/portal notes.
The encoder does not supply the still-unfinished geometric selector. No retail
map, reference list or binary is distributed with the source tests.

Triangle header partitioning (5 November 2026) is original GPL-2.0-or-later
code in `respawn/tricoll_partition.h`, integrated into the entity patch collector
in `titanfall_collisions.cpp`. It preserves triangle/reference identity while
splitting over-budget native headers. Independent decoding tests cover dense
fans and cascading stream-capacity changes. No external implementation was
copied. The collision/portal notes record limits, validation and the still-open
geometric selector.

Convex water coverage (5 November 2026) is original GPL-2.0-or-later code in
`respawn/convex_coverage.h`. It clips bounded convex brushes and subtracts them
from disjoint dry fragments to measure union volume within cell bounds. No
external implementation or game geometry was copied. Analytic solids and
original map fixtures cover slopes, overlaps and partial cells; native smoke
evidence and remaining water limitations are in the TF1 notes.

Patch render normal generation (5 November 2026) calls the inherited GPL mesh
normal calculation in `mesh.cpp` from the Respawn path in `bspfile_shared.cpp`.
The collapsed-grid fallback and validator/tests are original local code. This
repairs copying uninitialized map control-point normals. Existing inherited
copyright notices remain in place. No external implementation was added.

For each incorporation, add the exact upstream commit/release, original authors,
license and preserved notice locations, affected local files, modifications,
target build and validation evidence here. Keep each tool's identity in release
credits and any bundled license notices. Check compatibility with this project's
GPL-2.0-or-later licensing before copying source; GPL-3.0-derived code can impose
GPL-3.0 requirements on a combined derivative. Do not assume that naming an
upstream tool permits source copying or binary redistribution.
