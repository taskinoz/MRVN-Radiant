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
| `decompile_bsp.py` | Recovers a TF2 scene as an editable map ([RESPAWN_DECOMPILE.md](../../docs/respawn/RESPAWN_DECOMPILE.md)) |
| `recover_collision_map.py` | Recovers collision brushes as a Radiant map |
| `extract_maps.py` | Extracts sample maps through tf2vpk |
| `probe_axial_order.py` | Scores brush-side orders against retail maps |
| `bake_direct.py` | Offline direct-light reference bake |

## Testing

| Tool | Does |
| --- | --- |
| `compiler_regression.py` | Compiles the regression set with a given `remap` and compares |
| `r5_harness.py`, `r5_harnessctl.py`, `r5_harness_smoke.py` | Local R5Reloaded map harness ([RESPAWN_R5_HARNESS.md](../../docs/respawn/RESPAWN_R5_HARNESS.md)) |
| `test_*.py` | Unit tests: `python -m unittest discover -s tools/respawn -p "test_*.py"` |
| `CMakeLists.txt`, `*_tests.cpp` | C++ tests for the BSP reader, encodings, lightmap packing, bake and CSG; `relight_bridge.cpp` feeds `repair_tf1_port.py` into the native baker |

Build and run the C++ tests with:

```powershell
cmake -S tools/respawn -B build/respawn-tests
cmake --build build/respawn-tests --config Release
ctest --test-dir build/respawn-tests -C Release
```
