# r5valkyrie Apex fork review and initial integration

Reviewed 17 November 2026. This is a selective source integration, not a merge of
the fork or a new Apex runtime compatibility certificate.

## Source, revision and license

- Repository: [r5valkyrie/MRVN-Radiant](https://github.com/r5valkyrie/MRVN-Radiant).
- Reviewed `main` commit: `5f7caa513171ebbaeba46d5d7348f5d31c3c1a23`, dated
  17 March 2026, subject `Add info_lightprobe entities and tweak BSP keys`.
- Retain attribution to r5valkyrie/MRVN-Radiant contributors and the original
  GtkRadiant/NetRadiant/MRVN-Radiant authors. The adapted Apex files carry
  GPL-2.0-or-later notices, compatible with these destination files; the root
  LICENSE explains the repository's per-file licensing.
- Only selected source text was retrieved into the ignored local review directory.
  No fork editor models, game-derived textures, compiled assets, new GPU libraries
  or executables were imported into this checkout.

The fork's current `games.cpp` and Apex build menu select **`apexlegends`, BSP
v47**. They do not declare separate season-specific compiler profiles. Its README
reports 85% with its own manually maintained 67-lump denominator, while its source
name table contains additional definitions. Those numbers are not comparable to
this checkout's older 26/68 count and are not playable compatibility percentages.
The fork may contain useful research for other seasons, but this review has no
basis to promise arbitrary later-season or current-retail compatibility.

## Useful work found

| Area / fork source under `tools/remap/source/apex_legends/` | Assessment |
| --- | --- |
| `apex_legends_models.cpp` | Per-model mesh bounds and generated level metadata replace inherited fixed values; bounded portions adapted below |
| `apex_legends_entities.cpp`, `apex_legends.h` | Apex-specific static-prop records, transforms, model-path handling and inline entity collision; useful candidates requiring version-specific validation |
| `apex_legends_collisions.cpp` | Substantial BVH rewrite and additional leaf handling; needs differential collision tests against our current path and native engine |
| `apex_legends_lighting.cpp`, `apex_legends_lightmaps.cpp` | World lights, probes, HDR bake and shadow infrastructure; coupled to new trace/bake APIs including `hiprt_trace.h`; not a standalone file copy |
| `apex_legends_portals.cpp`, `apex_legends_visibility.cpp` | Portal/cell research and additional metadata; current visibility path deliberately uses a debug root and requires bounded-reference review |
| `apex_legends_meshes.cpp`, `apex_legends_vertices.cpp` | More explicit vertex/mesh fields; some interpretations are not established across our S0-S3 corpus |
| Apex gamepack environment entities | Manual probe authoring controls; useful after a compatible compiler/probe pipeline is integrated |

## Incorporated now

1. **Model bounds:** `ApexLegends::EndModel` now accumulates only the model's own
   mesh range, adapted from `apex_legends_models.cpp`. It previously accumulated
   every mesh emitted so far. This is a source correctness fix; the existing Apex
   compile dispatch still only compiles world geometry, so this does not add
   brush-submodel or trigger collision support.
2. **Generated level metadata:** replace fixed world boundaries `51/51/51`, prop
   base `256` and prop count `22` with the emitted world mesh count, its 64-aligned
   prop base and actual emitted prop count. The fork's approach is adapted to our
   current vectors, using the emitted world model instead of the mutable shared
   mesh list. World meshes retain one conservative category; retail decal,
   translucent and sky partition recovery remains open. Sun/model-count semantics
   were not imported or expanded by this change.
3. **Matching prop references:** static-prop visibility object IDs now use the
   same 64-aligned base as generated LEVEL_INFO. The previous unaligned world-mesh
   count disagreed with the new metadata and the surveyed namespace relationship.

No additional lighting, navmesh, collision, static-prop record format or packaging
support is claimed from these changes. In particular, the existing TF2-derived
Apex prop serialization still needs its own version-specific review.

## Cross-check against supplied S0-S3 files

Read-only inspection used the four existing local v47 maps: S0 Canyonlands, S1
Canyonlands, S2 Canyonlands and S3 Aqueduct. These season labels describe supplied
folders, not independently identified executable builds. Default external lump
payloads were preferred where present. Source and generated artifacts stay private
under `.local/respawn/r5valkyrie-review/`.

The LEVEL_INFO prop bases in those maps are respectively **37696, 37568, 37248,
4928**, each equal to its third world boundary rounded up to 64. Their level prop
counts match the static-prop header counts. That supports the narrow metadata/ID
relationship; it does not establish culling or gameplay parity. Retail world
categories differ from each other and are not replaced with the fork's universal
all-mesh grouping as a claim of exact retail reconstruction.

Two findings prevent importing the whole writer as a verified replacement:

- The fork describes the final word of each 32-byte lit-bump vertex as a second
  normal index tagged with `0x80000000`. Under that exact interpretation, none of
  the four local samples matches the proposed relationship. The word at byte 16
  also has varied values, including many `0xffffffff`, rather than a universal
  `0x00ffffff`. This is evidence against assuming that interpretation applies to
  these samples; it does not establish which other engine build it may target.
- Its current `EmitVisTree` explicitly forces bounds of +/-50000, puts every object
  in one root and assigns total references to an **8-bit** `objRefCount` field.
  Counts above 255 need an explicit strategy. We retain the existing tree path
  rather than importing that debug culling implementation.

Earlier-season LEVEL_INFO model-count values also differ from a simple count of
nonempty model mesh ranges in the supplied corpus. That interpretation requires
separate research before changing it globally.

## Validation and limits

The compiler rebuilt successfully with Visual Studio 2022's bundled CMake using:

```powershell
& 'C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe' --build .local/respawn/remap-build --config Release --target remap -- /m
python tools/respawn/compiler_regression.py --remap install/Release/remap.exe --work-dir .local/respawn/r5valkyrie-review/regression
python -m unittest discover -s tools/respawn -p 'test_*.py'
```

The system PATH CMake is 3.19.4 and cannot use this Visual Studio 17 generator;
the existing build cache identifies the working bundled CMake. This was a local
build-tool mismatch, not a compiler source failure.

Two original compiler fixtures use one and 70 world meshes, plus two tiny OBJ
props created by the test. They verify generated counts, model bounds/range,
GAME_LUMP count agreement and exact visibility IDs across the 64-object boundary.
They require no retail assets. All **62 compiler regression reports** pass: 33
TF1/TFO, 26 TF2 and three Apex reports. These are structural checks; the model
bounds guard has no separate native brush-submodel test because that compile
path is still absent. The Python tool suite has **261 passing tests**.

No Apex game session was launched. Existing runtime limitations and the three-game
[map support audit](RESPAWN_MAP_SUPPORT_AUDIT.md) still apply. The larger fork
integration should proceed in separately tested steps: pin an engine/build and
corpus, reconcile schemas, then integrate collision/entity handling, static props,
lighting/probes and bounded visibility with native regression controls.
