# Respawn compatibility work

## Objective and release gates

Version 1 targets authoring and compiling maps, importing models/materials,
configuring objectives/spawns/triggers, baking lighting, and packaging the complete
map and its dependencies for Titanfall, Titanfall Online, Titanfall 2, and a
specified Apex build. Navigation mesh generation belongs to version 2.

A target is compatible only after an authored map is packaged and tested in that
target's runtime. A nonempty lump or a successful compiler invocation does not
establish compatibility. Track Titanfall and Titanfall Online separately even
when their BSP versions agree. Apex profiles must identify the actual game build
and supported runtime; a v47 implementation does not establish current retail
support.

## Initial source audit (2026-10-07)

| Area | Evidence in this checkout | Required work |
| --- | --- | --- |
| BSP loading | `LoadBSPFile`/`LoadBSPFilePartially` dispatch commented out in `tools/remap/source/bspfile_abstract.cpp`; R1/R2 have decompile helpers, R5 loader is empty | Bounded version-aware readers, sidecars, unknown-data preservation, schema validation |
| Existing read helpers | `CopyLump` copies offsets without a file-size argument; `LoadEntFile` skips a fixed ten bytes | Validate file ranges before copying; parse entity headers by line |
| Geometry | Separate R1/R2/R5 emitters exist | Check record layouts, counts, index limits and cross-lump references against samples |
| Collision | R1 grid/brush emitters and R5 BVH code exist; triangle collision incomplete per existing README | Independently verify player, titan, projectile, prop and trigger collision |
| Visibility | Cell/portal lumps emitted from stub vectors in game writers | Generate cells, portal topology, bounds and references from authored geometry |
| Lighting | Shared lightmap UV code and legacy lighting code exist; game writers emit lighting stubs | Implement each target's world lights, lightmaps, probes and required shadow data |
| Static props | Game-lump writers exist; Apex writer reuses Titanfall 2 structures | Verify per-version static-prop schemas and asset references |
| Entities | Entity partition and trigger emitters exist | Verify partition/header variants and runtime classes, keyvalues, scripts and objectives |
| Packaging | No integrated Respawn VPK/RPAK export established by this audit | Verify tool versions, dependency closure, manifests, archive dialect and runtime mounting |
| Local build prerequisites | `windeps` absent at audit time | Set up dependencies from `COMPILING.md` before native compiler validation |

The initial audit had no local sample corpus. Subsequent work used the supplied
installations, built and ran remap on Windows, and exercised its writers; see
[RESPAWN_SAMPLES.md](RESPAWN_SAMPLES.md) for evidence and limits. No in-game
complete compatibility test or Qt6 editor build has been completed. The user has
loaded the experimental E1M1 Northstar mod in-game; its white materials, blocked
passages and lighting defects prompted further work. That confirms a partial
runtime geometry test, not complete map compatibility.

## Implemented foundation

- `tools/remap/source/respawn/bsp_reader.h`: bounded native directory and opaque
  lump reads, default/client external overrides, big-endian metadata and streamed
  version handling. Reads preserve bytes; there is no complete typed map decoder.
- `remap -info`: now reports actual rBSP version, revision and lump metadata without
  invoking the incomplete decompile path.
- `LoadEntFile`: recognizes both entity header variants by line and removes
  intermediate NUL terminators when combining partitions.
- R1/R2 writers: set known nonzero lump versions for their generated layouts.
  Apex's separate v0 records are unaffected. This fixes header metadata; existing
  stub payloads still need replacement.
- Tools-only CMake builds no longer require Qt or compile gtkutil. MSVC release
  optimization and the compiler's Unix-only rpath flag are configured correctly.
- Native reader tests have a standalone CMake project at `tools/respawn` and run
  in CI alongside the Python inventory/extraction tests.
- Shared mesh construction classifies lighting using each mesh's material.
  Apex selects vertex formats by the complete two-bit field, preserving the
  tangent-space unlit pool. All three emitters now write mesh bounding radii.
- R1/R2 collision emission initializes missing axial faces, preserves the side
  prefix for boxes following sloped brushes, and writes axial texture references
  in +X/-X/+Y/-Y/+Z/-Z order. Unrepresentable brush/side indices fail explicitly.
- R1/R2 triangle emission uses the full vertex-pool offset before calculating
  material-sort-relative indices, avoiding an intermediate 16-bit truncation.
- R1/R2/R5 texture emission compares whole NUL-terminated names at each texture
  record's offset, so a longer material name cannot alias its prefix. Names
  without `textures/` are preserved instead of erasing past the string's end.
- R1/R2 collision bounds round centers and expand extents conservatively,
  preserving the existing two-unit margin for fractional brushes. Invalid or
  unrepresentable bounds, contents indices and cell ranges fail explicitly.
  Worlds with no ordinary grid brushes initialize finite grid bounds; sky-only
  worlds are covered by the compiler regression.

## Selected record validation

The known Quake E1M1 compile and Coliseum glTF/partial collision-map recovery
are recorded in [RESPAWN_MAP_TRIALS.md](RESPAWN_MAP_TRIALS.md), including artifact
locations, exact upstream revisions, checks and limitations.

`tools/respawn/validate_records.py` independently decodes selected little-endian
v29/v37 records using the Python standard library. It checks record strides,
supported lump versions, brush side/plane/texture references, parallel side
records, model mesh ranges, material sorts, triangle vertex references,
position/normal references and basic mesh bounds. Default sidecars override
embedded payloads; client-only overrides are not selected. Unsupported targets
are rejected rather than decoded with the R1/R2 schema.
The validator also checks collision grid dimensions and cell counts, cell
geo-set ranges, primitive ranges, brush/contents references and parallel
collision bounds. Triangle and static-prop collision payloads remain unvalidated.
R2 mesh records use their separate byte layout even where checked offsets agree.

```powershell
python tools/respawn/validate_records.py 'D:/samples/maps/example.bsp' --output records.json
python tools/respawn/compiler_regression.py --remap install/Release/remap.exe --work-dir .local/respawn/new-regression
```

The compiler regression requires a new working directory. It creates original
sloped/axial geometry, fractional coordinates, four material types and overlapping
material names, then compiles R1/R2/R5 outputs. It verifies complete material
identity and deduplication on all three profiles, conservative collision bounds
on R1/R2, and compiles separate R1/R2 sky-only fixtures.
R1/R2 outputs receive the selected record checks and an explicit axial material
order check. R5 receives structural checks and vertex-pool presence checks only.
This is not a playable-map test. Collision bevels, texture projections, lighting,
tangents, visibility, assets and packaging still need separate verification.
The standalone native tests include texture-name boundary cases and collision
encoding checks across 4,096 fractional intervals, plus invalid/overflow cases.

## Inspection tool

`tools/respawn/inspect_bsp.py` uses Python 3.10+ with no third-party dependencies.
It reads the 128-entry rBSP directory, records version/revision and lump metadata,
checks internal payload ranges and overlaps, inventories adjacent external lumps
and entity partitions, and optionally calculates SHA-256 hashes. Files are never
rewritten. Raw unknown lumps remain opaque.

```powershell
python tools/respawn/inspect_bsp.py 'D:/samples/titanfall/maps' --hash --output titanfall-inventory.json
python tools/respawn/inspect_bsp.py 'D:/samples/titanfall2/maps/example.bsp' --output example-inventory.json
python -m unittest discover -s tools/respawn -p 'test_*.py' -v
```

Input folders are scanned recursively. Input must already be extracted; the tool
does not extract VPKs or RPAKs. Keep `.bsp_lump`, `.bsp_lump.client` and `.ent`
files alongside their BSP with original names. Output records both default and
client variants without choosing one as the runtime's effective payload. Sidecar
hashes cover entire files, independent of virtual offsets in the BSP directory.

Lump names come from the local compiler's `lump_names.h` for exact versions 29,
37 and 47. These are hints, not schema validation. Other versions get numeric
IDs. Versions with major >= 49 and high half = 1 are provisionally treated as
external layouts based on the referenced Apex research. Other nonzero high-half
values produce an unresolved-layout warning and skip payload range validation.
Big-endian headers can be inventoried but are not
claimed as compiler targets. External payload size is reported independently of
directory length because their relationship needs verification per build.

Exit code 1 means a file could not be inspected or structural errors were found;
valid files remain in the report when other files fail. Exit code 0 means these
limited checks passed. It does not mean the BSP is engine-compatible. No record
decoding, decompression, entity semantic validation or asset resolution occurs.

## Archive sample extraction

`tools/respawn/extract_maps.py` wraps an explicitly supplied tf2vpk executable. It
extracts map/BSP/lump/entity files into a new empty destination, writes binary
output directly, and records archive-directory, tool and output hashes in an
`extraction.json` manifest. Game archives are never modified. Failed extraction
leaves an incomplete manifest and requires a new destination for another run.

```powershell
python tools/respawn/extract_maps.py --tool .local/respawn/tf2vpk.exe --archive 'C:/Games/Titanfall2/vpk/englishclient_mp_coliseum.bsp.pak000_dir.vpk' --destination .local/respawn/samples/tf2-coliseum-new
cmake -S tools/respawn -B .local/respawn/native-tests
cmake --build .local/respawn/native-tests --config Release
ctest --test-dir .local/respawn/native-tests -C Release --output-on-failure
```

The optional `--relaxed-flags` switch disables tf2vpk's metadata sanity checks for
archives whose historical flags it rejects; it does not disable CRC verification.
The choice is recorded in the manifest. The adapter removes inherited debug
settings so a caller's environment cannot silently disable CRC checks.

## Implementation sequence

1. **Build and sample baseline.** Build editor/remap on Windows, record game and
   runtime builds, extract a small local corpus from each installation, and store
   metadata/hashes in local reports. Include small interiors, outdoor areas,
   static props, displacement/terrain, water, sky, and scripted trigger examples.
   Keep copyrighted sample payloads out of Git. Gate: reproducible builds and
   inventories for each distinct target format.
2. **Read and preserve.** Implement readers with bounded counts and ranges,
   versioned records, partition parsing, external overrides and compressed data
   where observed. Preserve unknown lumps byte-for-byte; account for absolute
   game-lump offsets when relocating data. Gate: parsed corpus without unexpected
   failures; lossless preservation checks and cross-reference validation.
3. **Playable geometry.** Verify render meshes/material sorting, brush and triangle
   collision, static props, entity partitions, and minimal world metadata. Begin
   with an authored sealed room, then a ramp and prop scene. Gate: load, spawn,
   movement and weapon traces verified in each target runtime.
4. **Visibility and lighting.** Replace cell/portal and lighting stubs; implement
   probes, cubemaps, sky/real-time lighting representations and shadow structures
   required by each version. Gate: authored indoor/outdoor scenes with correct
   visibility, lighting and prop response under runtime observation.
5. **Assets and packaging.** Import models/materials/textures through attributed
   adapters; resolve model/material/texture dependencies, streaming assets and
   archive manifests. Implement staged VPK, RPAK and STARPAK outputs as required
   by the target. Prefer external tool
   adapters first; pin supported releases and validate their actual capabilities.
   Gate: a packaged map with custom assets loads from a clean test deployment.
6. **All-in-one release.** Wire verified stages into the editor with target
   profiles, progress, actionable errors and reproducible manifests. Verify
   game objectives/spawns/triggers using minimal per-runtime scripts and entity
   definitions. Gate: repeatable create/import/compile/bake/package workflow for
   every supported build, with explicit supported versions in release notes.

The first vertical slice should be chosen from the supplied runtime builds and
samples. Work on other versions must not silently inherit an unverified schema.

## Evidence and attribution

Lighting tools and measured corpus evidence are documented in
[RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md): v29/v37 inspection, raw atlas-plane
exports, controlled v37 atlas probes, authored point-light records, an offline
occlusion baker and a bounded native chart packer. Engine texel decoding,
dense baking, probes, CSM and cross-game lighting remain incomplete.

For every new schema, record source URL and exact upstream revision, target build,
sample hash, lump index/version, field offsets/sizes, relationships, confidence,
and validation performed. Separate observed facts from hypotheses. Synthetic
tests exercise parsers; real-file comparisons and runtime tests establish format
and engine compatibility.

See [RESPAWN_SOURCES.md](RESPAWN_SOURCES.md) for the attribution register. Record
copied/adapted files, license obligations and modifications before incorporating
upstream implementation. Attribution alone is not a license grant.
