# Known-map compile and Coliseum recovery

Tested locally on 2026-10-07. All outputs remain under ignored `.local/respawn/`;
game assets and upstream executables are not committed.

## Quake E1M1 to Titanfall 2

Used **The Slipgate Complex**, the original Quake E1M1 `.map`, from
[fzwoch/quake_map_source](https://github.com/fzwoch/quake_map_source), commit
`27abebaa3886bb0e3156cce3a604673d22b243f8`. The repository README identifies the
John Romero October 2006 source release; its GPL-2.0 COPYING was retained beside
the local copy. No upstream map changes were made. Classic brush `.map` syntax is
supported by Radiant; actual editor GUI loading was not tested in this session.

```powershell
install/Release/remap.exe -game titanfall2 -bsp .local/respawn/map-trials/e1m1-tf2/e1m1.map
python tools/respawn/validate_records.py .local/respawn/map-trials/e1m1-tf2/e1m1.bsp --output .local/respawn/map-trials/e1m1-tf2/validation.json
```

The compiler produced a **2,253,204-byte v37 BSP**, with **1,257 collision
brushes**, and passed the selected geometry/collision record checks. Outputs:
`.local/respawn/map-trials/e1m1-tf2/` (map, BSP, entity partitions, COPYING,
build log and validation report).

This is a geometry/compiler trial, not a playable port: Quake materials/WADs were
not converted into Respawn textures, and Quake entities, monsters, triggers,
doors, spawns and game logic still require target-specific conversion. Missing
material-image warnings are expected. Lighting and visibility remain compiler
stubs. No VPK/RPAK packaging or game runtime test was performed.

## Coliseum with bsp2gltf

Built [snake-biscuits/bsp2gltf](https://github.com/snake-biscuits/bsp2gltf), commit
`1057d0c19e5689e2eeccf95f6ca845e34a9b1924`, locally using MinGW GCC 12.2 and
`-std=c++20 -O2`. No upstream code was changed or incorporated into this project.
There is no license file at this revision; the source and executable remain
local, and are not bundled for redistribution.

The tool exports world render meshes to glTF; it does not reconstruct `.map`
brushes, entities or static props. Its loader ignores external lump overrides.
An original preparation script at `.local/respawn/prepare_coliseum.py` therefore
materialized the effective default lumps into a separate rendering-only BSP.
GAME_LUMP was omitted to avoid relocating its absolute offsets; that prepared
file is not suitable for engine use. The original extracted BSP and sidecars
were untouched.

Input: `mp_coliseum.bsp`, v37 revision 30, SHA-256
`16fbc5383350607e1de4e972c5d229b1effa329f7ffc5af65f46ea8277062669`.

Run `.local/respawn/bsp2gltf.exe coliseum-render-input.bsp` from
`.local/respawn/map-trials/coliseum/`. Upstream writes `bsp.gltf`,
`bsp.vertices.bin`, and `bsp.indices.bin` in the current directory.

The export contains **13,065 vertices**, **10,920 triangles**, and **15 material
groups**. Triangle count agrees with the source world model. Buffer lengths,
accessor spans, finite coordinates and vertex indices were checked. An original
local postprocess, `.local/respawn/check_map_trials.py`, produced `coliseum.gltf`
and its two companion buffers, preserving the raw upstream output. It adds
POSITION min/max, marks byte colors normalized, and rotates normals with the
same coordinate transformation upstream already applies to positions. These
are selected checks, not a complete Khronos glTF-validator run. The export has
material names but no texture images, props, entity models or baked lighting.

## Partial editable collision recovery

The original `tools/respawn/recover_collision_map.py` reconstructs brush planes
from the validated R1/R2 collision bounds and cutting-plane references. It writes
classic Radiant `.map` syntax with all brushes in worldspawn and one placeholder
material. It refuses to overwrite its output. This is separate from bsp2gltf's
render-mesh export.

```powershell
python tools/respawn/recover_collision_map.py .local/respawn/samples/tf2-coliseum/maps/mp_coliseum.bsp .local/respawn/map-trials/coliseum/coliseum-collision.map
install/Release/remap.exe -game titanfall2 -bsp .local/respawn/map-trials/coliseum/coliseum-collision.map
```

Recovered **12 collision brushes**. Their `.map` compiled back to a v37 BSP;
selected record checks passed and all 12 brush origins/extents matched the source
with **zero AABB error**. Degenerate bevel-face warnings are expected where a
cutting plane only touches a box edge. All **48 cutting planes** were also
matched after recompilation: normal components agreed within 1e-5 and maximum
plane-distance error was **zero**. This is not a complete Coliseum decompile:
collision brushes alone omit its detailed render geometry, triangle collision
and prop collision. Entity grouping/transforms, materials/UVs, props and lighting
are not reconstructed. Stored model coordinates are flattened into worldspawn.

The output folder also includes `verification.json` with export counts, repairs,
source hash and recovery limitations. The Python test suite now has 41 passing
tests, including plane distance/winding and invalid-plane recovery tests.
