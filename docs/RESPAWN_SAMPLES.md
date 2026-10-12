# Local sample evidence (2026-10-07)

Samples were read from the installations supplied by the project owner. Archive
contents, binaries and detailed inventories remain in ignored `.local/respawn`;
no game payloads are committed. This file records observations, not an assertion
that generated maps load in these games.

## Corpus

| Target / source | Sample | BSP version | SHA-256 of main BSP |
| --- | --- | --- | --- |
| Titanfall retail | `mp_angel_city` | 29 | `d4dfe151032b470db2a9fae3c51d7c3ea9bea15f85d2dbf55502fcfbfa6094ef` |
| Archived Titanfall beta folder | `mp_angel_city` | 29 | `d4dfe151032b470db2a9fae3c51d7c3ea9bea15f85d2dbf55502fcfbfa6094ef` |
| Titanfall Online asset dump | 17 maps, including `mp_box`, `mp_lobby_02` | 29 | Local inventory available; full-dump payload hashes not yet calculated |
| Titanfall Online mods/data | 15 maps, including split-lump mod maps | 29 | Kept separate from the asset-dump inventory |
| Titanfall 2 | `mp_coliseum` | 37 | `16fbc5383350607e1de4e972c5d229b1effa329f7ffc5af65f46ea8277062669` |
| Apex season 0 folder | `mp_rr_canyonlands_64k_x_64k` | 47 | `8ed8378ecb38aef78a49f6df46732d2d5c4b2bbde8951454b8b5a3336573f05c` |
| Apex season 1 folder | `mp_rr_canyonlands_64k_x_64k` | 47 | `af8657fd9b3e66fc4574584da6a29a6d901dffb620c9353896efc2d39cf20db1` |
| Apex season 2 folder | `mp_rr_canyonlands_mu1` | 47 | `2578f8a60e1daf1085658b1d93c1cd064b8bc4d6cd0da5e70619eacfdd69854a` |
| Apex season 3 folder | `mp_rr_aqueduct` | 47 | `894d7b9516c8cd794324b629de5d52c8733d1a1705c906508db12142beb00617` |

Retail and beta Angel City BSPs are identical in this supplied corpus. This sample
cannot establish a distinct beta schema. Season names describe source folders;
runtime executable versions have not yet been independently fingerprinted.

The extracted seven-map corpus and both Online inventories passed the Python
directory-range/overlap checks. Hashes and source archive provenance for the
extracted corpus are stored with `extraction.json` and
`.local/respawn/reports/extracted.json`.

## Observed header and partition differences

- R1 sample revision: 519. R2 and the selected Apex samples: 30. Revision is not a
  fixed game-format identifier.
- R1/R2 planes and texture data use lump version 1. Lit vertices and lightmap
  headers use version 1. Observed triangle indices use version 2 and collision
  bounds/headers version 1.
- R1 world lights use version 1; the R2 sample uses version 3. The generated R2
  world-light stub is a v3 layout. The selected Apex directory entries use v0.
- R1/R2 external entity headers are `ENTITIES01`; Apex examples include
  `ENTITIES02 num_models=10` and `ENTITIES02 num_models=24`.
- Retail/beta, R2 and Apex seasons 0–2 samples carry adjacent external lump
  overrides. The selected season 3 sample embeds its lumps with no extracted
  overrides. Sidecars are full payloads, not reads at directory virtual offsets.

These observations were cross-checked against bsp_tool's Titanfall and Titanfall
2 version tables before correcting the generated R1/R2 directory tags. Broader
typed field validation beyond the selected record checks below remains outstanding.

## Verification performed

- 41 Python synthetic tests: inventory parsing, malformed headers/ranges,
  overlaps, sidecars, entity headers, extraction path filtering, binary output,
  no overwrite, explicit flag handling and failure manifests; selected typed
  records, brush-side prefixes, plane/texture references, vertex-pool addressing,
  mesh bounds, unsupported encoding and default/client payload selection.
  Partial brush recovery tests check plane distance/winding and invalid planes.
- Known-map E1M1 compilation and Coliseum render/collision recovery trials are
  recorded separately in [RESPAWN_MAP_TRIALS.md](RESPAWN_MAP_TRIALS.md).
- Selected collision grid/cell/geo-set/primitive and contents references are
  checked as well; malformed slices, contents IDs and grid dimensions have
  synthetic coverage. Triangle and static-prop payloads are not decoded.
  Expanded checks passed the same 37-file corpus; report:
  `.local/respawn/reports/collision-corpus-set2.json`.
- Native C++17 reader/partition tests built with MinGW GCC 12.2 and passed CTest.
- Native reader consumed all 128 lump slots of the seven extracted maps plus
  Online's `mp_box` and `mp_lobby_02`, using adjacent overrides where present.
- Full remap target built with MSVC 19.44 / VS 2022 on Windows using official
  MRVN-WinDeps v0.2. The new `-info` path ran on the R2 sample.
- A local copy of `regression_tests/q3map2/degenerate_winding/maps/degenerate_winding.map`
  compiled successfully under `titanfallonline`, `titanfall2`, and `apexlegends`.
  All three generated files passed the structural inspector; emitted R1/R2
  nonzero tags matched the corrected version selection.
- The selected v29/v37 record validator passed 37 local BSP files: 34 from the
  Titanfall Online installation (dump, mod and depot paths), the retail/beta
  Angel City samples and Titanfall 2's Coliseum. These are file instances, not
  37 distinct maps or engine builds. Report: `.local/respawn/reports/records-corpus.json`.
- Original two-brush regression geometry (slope followed by box), with flat-lit,
  bump-lit, unlit and tangent-space unlit materials, compiled under all three
  compiler profiles after the fixes. R1/R2 outputs passed selected record checks
  and authored collision-face material order checks. Apex passed structural
  checks and required vertex-pool presence checks. Outputs and build logs:
  `.local/respawn/compiler-regression-final/`. Missing-image warnings are expected;
  the fixture uses shader definitions without game textures.
- Before the fixes, the selected validator found zero bounding radii in the old
  generated smoke outputs. The new sloped-brush fixture also exposed an access
  violation from uninitialized missing axial faces; the corrected emitter
  compiles it successfully.
- The second regression set includes five brushes with fractional X coordinates,
  overlapping material names emitted long-name-first, and repeated materials.
  All three profiles passed material identity/deduplication checks. R1/R2 also
  passed conservative collision-bound checks and separate sky-only compilations.
  Outputs: `.local/respawn/compiler-regression-set2-final/`.
- Native CTest passes both the reader tests and encoding tests. Encoding coverage
  includes 4,096 fractional intervals, signed-field overflow, non-finite bounds,
  texture string termination, exact name matching and short unprefixed names.

The regression fixture uses missing Quake material images; those warnings are
expected in this compile-only smoke test. It is not a playable Respawn test map.
The compiler still emits lighting/portal stubs. No game runtime, VPK/RPAK export,
asset import, or editor GUI behavior was tested.

## Local build environment

The system PATH CMake is too old to expose the VS 2022 generator; the Visual
Studio bundled CMake 3.31.6 was used for remap. Windows SDK metadata access needed
execution outside the filesystem sandbox. The compiler executable is
`install/Release/remap.exe`, with Assimp and its required runtime DLLs alongside
it. Runtime dependencies were copied from `.local/respawn/runtime/install`;
the older build dependency package contains
Qt5, so a full editor build still needs Qt6 as described by the CI setup.

The compiler-only build uses `-DBUILD_RADIANT=OFF -DBUILD_PLUGINS=OFF
-DBUILD_TOOLS=ON`. Its successful build emits existing legacy warnings; this work
does not assert a warning-free build.

## Collision brush axial side order (2026-10-12)

`tools/respawn/probe_axial_order.py` checks the six axial brush-side slots that
come before each brush's cutting planes. A slot flagged `0x4000` (replaced by a
non-axial side) should lie on the side its cutting planes face. If a discarded
slot's cuts all point the same way along its axis, that slot shows which sign
comes first:

| Sample | Unambiguous slots: +X first | Unambiguous slots: −X first |
| --- | ---: | ---: |
| TF2 `mp_glitch` | 0 | 24 |
| TF1 `mp_angel_city` | 98 | 1,758 |

Texture vectors confirm that slots pair by axis (X, X, Y, Y, Z, Z), not by sign
(bsp_tool's `+XYZ -XYZ` decompile order). The emitter therefore writes
−X, +X, −Y, +Y, −Z, +Z. An earlier change to +X first was reverted. Coliseum has
no discarded slots and cannot tell the orders apart. This test uses flag
placement only. It does not show how the runtime uses each slot.
