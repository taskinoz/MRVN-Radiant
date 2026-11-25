# Respawn tools

Python and C++ tools for reading, converting, packaging and testing Respawn
(Titanfall, Titanfall 2, Apex Legends) maps alongside the `remap` compiler. They
were written with AI; see [AI.md](../../AI.md).

Run them from the repository root with Python 3.10 or later. Most are standard
library only. The map converters also need NumPy and Pillow:
`python -m pip install -r tools/respawn/requirements.txt`. Tools that import
each other expect this folder on the path: `$env:PYTHONPATH = 'tools/respawn'`.
Every tool prints its options with `--help`. The research notes in
[docs/respawn](../../docs/respawn/README.md) explain what each tool found and how
it was verified.

Finished maps built with the converters, with their exact recipes, are in
[Titanfall-2-Custom-Maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps).

## Map converters

These produce a Northstar mod folder and ZIP, an editable `.map`, and JSON reports.

| Tool | Converts | Notes |
| --- | --- | --- |
| `build_minecraft_ports.py` | Java Minecraft world ZIP | [RESPAWN_MINECRAFT_PORTS.md](../../docs/respawn/RESPAWN_MINECRAFT_PORTS.md) |
| `minecraft_world.py` | Anvil/NBT reader used by the converter | |
| `minecraft_scenery.py` | Sky dome and menu stage used by the converter | |
| `build_source_ports.py` | Source 1 BSP (Half-Life 2, Team Fortress 2) | [RESPAWN_SOURCE_PORTS.md](../../docs/respawn/RESPAWN_SOURCE_PORTS.md) |
| `source_engine.py` | VPK, BSP v19-21, VMT, VTF and PHY readers | |
| `build_source2_ports.py` | Counter-Strike 2 map, through Source2Viewer-CLI | [RESPAWN_SOURCE_PORTS.md](../../docs/respawn/RESPAWN_SOURCE_PORTS.md) |
| `source2_engine.py` | KV3, physics and glTF readers | |
| `build_northstar_test_mod.py` | Quake `.map` (E1M1 test) | [RESPAWN_NORTHSTAR_TEST.md](../../docs/respawn/RESPAWN_NORTHSTAR_TEST.md) |
| `build_quake_materials.py` | Quake textures to a TF2 material RPak | |
| `port_tf2_to_apex.py` | TF2 world to Apex (R5Reloaded) geometry | [RESPAWN_TF2_TO_APEX.md](../../docs/respawn/RESPAWN_TF2_TO_APEX.md) |
| `repair_tf1_port.py` | Repairs a manual Titanfall 1 to TF2 port | |
| `build_box_genesis.py` | Authored `mp_box`-style test yard | [RESPAWN_BOX_GENESIS.md](../../docs/respawn/RESPAWN_BOX_GENESIS.md) |
| `build_collision_portal_test.py` | Patch and doorway collision test mod | [RESPAWN_TRICOLL_PORTALS.md](../../docs/respawn/RESPAWN_TRICOLL_PORTALS.md) |
| `build_apex_coliseum_materials.py` | TF2 textures into Apex material templates | |

## Packaging

| Tool | Writes |
| --- | --- |
| `pack_vpk.py` | Uncompressed Titanfall 2 VPK 2.3 |
| `stbsp.py` | STBSP v8.0 material catalogue (also reads) |
| `mod_readme.md` | Tester README shipped in the Quake test mod |

## Inspection and recovery

`audit_tf1_lumps.py` compares v29 writer coverage, directory versions and selected
record validation across local BSPs; `--markdown` emits a per-lump checklist.
`prepare_tf1_baseline.py` builds original brush/patch geometry and shared native
checks. See the [Phase 2 notes](../../docs/respawn/RESPAWN_TF1_PHASE2.md) for the
commands, environment and limits of the resulting evidence.

| Tool | Does |
| --- | --- |
| `inspect_bsp.py` | Lists an rBSP's lumps and counts (read only) |
| `validate_records.py` | Cross-lump consistency checks for R1/R2 BSPs |
| `audit_tf2_budget.py` | World index budget against the engine's capacity |
| `game_lump.py` | GAME_LUMP inspection and relocation |
| `portals.py` | Cell and portal topology checks |
| `tricoll.py` | Triangle collision decoding and OBJ export |
| `rpak.py`, `rpak_apex.py` | TF2 v7 and Apex v8 RPak readers |
| `lighting.py` | Light and lightmap inspection, authored lights |
| `analyze_rtl.py` | Decodes RTL light slots per texel and tests them against lights and ray casts; summarises WORLD_LIGHTS fields |
| `decompile_bsp.py` | Recovers a TF2 scene as an editable map ([RESPAWN_DECOMPILE.md](../../docs/respawn/RESPAWN_DECOMPILE.md)) |
| `recover_collision_map.py` | Recovers collision brushes as a Radiant map |
| `extract_maps.py` | Extracts sample maps through tf2vpk |
| `probe_axial_order.py` | Scores brush-side orders against retail maps |
| `bake_direct.py` | Offline direct-light reference bake |

## Testing

| Tool | Does |
| --- | --- |
| `build_tf1_navigation.py` | Owned native AIN export and CRC packaging; requires ARES and pinned runtime ([guide](../../docs/respawn/RESPAWN_TF1_NAVIGATION.md)) |
| `tf1_navigation_crc.py` | Scoped v29 map/entity CRC and exclusive graph-copy adjustment; route acceptance remains separate |
| `compiler_regression.py` | Compiles the regression set with a given `remap` and compares, including the TF2 one-light-class-per-room world-light/flag fixture, paired opaque/alpha shadow-mesh emission, and two-environment shadow/probe isolation |
| `tfo_harness.py` | Loads a compiled TF1 map in Titanfall Online and runs traces, views and physics drops ([RESPAWN_TF1_LUMPS.md](../../docs/respawn/RESPAWN_TF1_LUMPS.md)) |
| `r5_harness.py`, `r5_harnessctl.py`, `r5_harness_smoke.py` | Local R5Reloaded map harness ([RESPAWN_R5_HARNESS.md](../../docs/respawn/RESPAWN_R5_HARNESS.md)) |
| `stage_r5_map.py`, `cast_to_obj.py`, `apex_native_regression.py` | Package/install compiled Apex maps for R5Reloaded, make prop editor copies from RSX Cast exports, and run the native S3 fixture checks ([RESPAWN_APEX_S3.md](../../docs/respawn/RESPAWN_APEX_S3.md)) |
| `test_*.py` | Unit tests: `python -m unittest discover -s tools/respawn -p "test_*.py"` |
| `CMakeLists.txt`, `*_tests.cpp` | C++ tests for the BSP reader, encodings, lightmap packing, bake and CSG; `relight_bridge.cpp` feeds `repair_tf1_port.py` into the native baker |

Build and run the C++ tests with:

```powershell
cmake -S tools/respawn -B build/respawn-tests
cmake --build build/respawn-tests --config Release
ctest --test-dir build/respawn-tests -C Release
```

TF1 water regression: the compiler suite includes separated/sloped water cells,
wet-cell world draw participation and Water/WaterBeneath shader profiles. Define
`$shadertype Water` on the volume material and `$shadertype WaterBeneath` on an
explicit reverse-facing, render-only underside. Use `_viewportals 1` for split
wet/dry cells. These profiles apply to v29; they do not generate underside
geometry or package retail material dependencies. Native evidence and remaining
R1Delta failures are in [Phase 2](../../docs/respawn/RESPAWN_TF1_PHASE2.md).

Reproduce the original rectangular water room without editing a BSP:

```powershell
python tools/respawn/prepare_tf1_water.py --remap install/Release/remap.exe --output .local/respawn/water-room
```

The new output directory contains source, BSP and spawn sidecar, material shader
profiles, shared `checks.json`, wet/dry cell checks and compiler/BSP hashes.
Pass its `maps/` directory and `mp_tf1_water` to either ARES native adapter.
Keep the spawn sidecar with the BSP when staging or renaming the map. Retail
materials are referenced but not included; R1Delta's `--material-files` accepts
an explicit local VMT/VTF dependency tree. This fixture tests two floor rays and
three views; it does not establish buoyancy or gameplay compatibility.

To distinguish surface visibility/material staging from the runtime Water shader,
add `--diagnostic-texture LOCAL.vtf`. The generator uses unique `ares_water/`
names and emits magenta/cyan UnlitGeneric VMTs plus the supplied texture under
`material-files/`; pass that directory to R1Delta's `--material-files`. Compiler
water profiles and geometry remain intact. A visible diagnostic surface proves
that control can draw; it does not verify refraction, fog or Water shader parity.
The generated manifest identifies this diagnostic mode. No VTF is bundled here.

The generator also emits `buoyancy-checks.json`: sequential wet/dry drops of
`models/containers/box_large_cardboard.mdl`, sample recording and coarse endpoint
height ranges. Pass this file to each adapter; R1 requires locally supplied
`--model-files`. Use ARES `physics_observations.py` with the matching standalone
PHY, `--floor 1 0 --motion 1`, to check the dry body's support and tail-window
translation. Checking wet `--motion 0` currently fails because the floating box
keeps bobbing. Zero entity-reported velocity alone does not establish rest.
This is a controlled sample; it does not establish broad buoyancy compatibility.


Add `--basin` to enclose the pool with solid banks, or `--flooded` to extend
water to all four room walls. These options are mutually exclusive. The flooded
layout has no dry floor: it validates wet cells on both sides, keeps spawn points
and the third camera above water, and omits `buoyancy-checks.json` rather than
emitting a misleading wet/dry pair. All three layouts compile and validate.
The same flooded BSP has a clean sampled underwater TFO view and retains the
R1Delta black band; this is a diagnostic comparison, not full water acceptance.

Audit the known direct Water dependencies in explicitly supplied local trees:

```powershell
python tools/respawn/audit_tf1_water.py --source LOCAL_MATERIAL_TREE --shader-source LOCAL_SHADER_TREE --material world/water/water_mp_angelcity_cheap --output water-dependencies.json
```

The audit follows `$bottommaterial`, checks known texture references (including
HDR-only cubemaps), distinguishes runtime render targets, and requires both
`water_ps40.vcs` and `water_vs40.vcs`. It records SHA-256 hashes and fails missing,
empty or linked resources, bad VTF headers and unsupported dependency syntax.
It supports direct `Water` VMTs and the `TextureScroll`/`WaterLOD` proxies used by
the native control. Patch/includes, conditions, other shaders/proxies and unknown
texture/material parameters fail explicitly. It does not decode textures or
shader caches, discover dependencies of other shaders/models, or resolve mounted
VPKs. A pass is a bounded file audit, not a complete package or visual check.

Use `pack_tf1_shaders.py --source LOCAL_SHADER_TREE --map mp_name --output NEW_DIR`
to package supplied `shaders/fxc/*.vcs` caches into a shader-only map VPK.
R1Delta's native Water control requires this VPK load path; loose cache files
alone did not restore the surface. Supply materials, textures, models and entity
sidecars separately. Neither command extracts or bundles retail assets.


`validate_records.py` also parses v29 embedded entities and declared `ENTITIES01`
partitions with `entity_text.py`. Duplicate output keys survive parsing. The
default partition-table sidecar takes precedence; invalid syntax, unsafe names,
case aliases and missing/linked/oversized files fail. Entity counts describe
syntax coverage, not spawn or objective correctness. For v29 it also checks the
sprp v12 static props, the stored-zip PAKFILE and realtime-light texel slots
(retail facts in `docs/respawn/RESPAWN_TF1_LUMPS.md`). Retail differences the
engine tolerates go to the report's `warnings` and do not fail validation.

`prepare_tf1_triggers.py --remap PATH --output NEW_DIR` compiles an original
floor, pilot spawns and axis-aligned/rotated trigger brushes, then writes shared
ARES `triggers` checks and compiler/source/BSP hashes. Entity origins translate
model-local brush coordinates. Touch checks use controlled player repositioning;
they do not certify walking or modes. No retail assets are bundled.

Add `--titans` to `prepare_tf1_triggers.py` to include an ARES native atlas
NPC support probe. It uses each runtime's own atlas settings name, verifies
sampled alive/native state and support/motion, then destroys the NPC. It is not
an AI navigation, piloting or combat check.


`prepare_tf1_objectives.py --remap PATH --output NEW_DIR` creates an original
v29 Hardpoint initialization fixture, shared ARES mode/spawn/floor checks and
compiler/source/BSP hashes. It references a base-game terminal model without
bundling assets. It does not certify captures, scoring, respawns, AI navigation
or human matches. See the TFO harness guide for Core135's CP dialogue-routing
issue and explicit temporary compatibility option.

Add `--capture` to the Hardpoint fixture builder to require natural match start,
a neutral-to-friendly capture, native trigger contact and a team-score gain via
the shared ARES `cp_capture` probe. The sampler does not set ownership or scores.
One capture/hold passes in both runtimes with the documented TFO compatibility
setup; contested/recapture, navigation and multiplayer acceptance remain open.
