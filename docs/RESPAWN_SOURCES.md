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
  extract the seven maps in `RESPAWN_SAMPLES.md` (local research notes). Its original
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
  described in `RESPAWN_MAP_TRIALS.md` (local research notes).
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
provide byte-size/layout evidence. See `RESPAWN_LIGHTING.md` (local research notes)
for attribution, results, encoding uncertainties and engine-validation limits.

Gravemind's `games/respawn/maps` conversion research was read on 11 October 2026.
Document IDs, revisions, recorded authors, source workspace references and local
engine cross-checks are retained in `RESPAWN_GRAVEMIND.md` (local research notes).
Technical findings inform an original read-only TF2 budget auditor and future
lighting/material/collision work. No conversion source, game assets, or access
credentials were copied into the project.

For each incorporation, add the exact upstream commit/release, original authors,
license and preserved notice locations, affected local files, modifications,
target build and validation evidence here. Keep each tool's identity in release
credits and any bundled license notices. Check compatibility with this project's
GPL-2.0-or-later licensing before copying source; GPL-3.0-derived code can impose
GPL-3.0 requirements on a combined derivative. Do not assume that naming an
upstream tool permits source copying or binary redistribution.
