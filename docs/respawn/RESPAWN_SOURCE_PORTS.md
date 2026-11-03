# Source engine map ports

`tools/respawn/build_source_ports.py` converts a compiled Source BSP (v19-v21: Half-Life 2,
Team Fortress 2 and other Source 2013-era games) to a Northstar test mod. Readers for VPK, BSP,
VMT and VTF are in `tools/respawn/source_engine.py`; no external Source tools are needed.

```powershell
python tools/respawn/build_source_ports.py --bsp "...\Half-Life 2\hl2\maps\d1_trainstation_02.bsp" --game-dir "...\Half-Life 2\hl2" --name trainstation02 --display-name "Trainstation (HL2)" --output NEW_DIRECTORY --remap install/Release/remap.exe --repak PATH_TO_REPAK.exe --material-template PATH_TO_NATIVE_MATERIAL_BASE
```

For Team Fortress 2, pass both `--game-dir ...\Team Fortress 2\tf` and `--game-dir ...\Team Fortress 2\hl2`
(TF2 also reads its bundled HL2 textures; untested). Its `info_player_teamspawn` RED/BLU spawns become teams 2 and 3.

## What converts

- Brushes, from the BSP's brush list, which keeps every original brush. Each side's plane and
  texinfo vectors become a Valve 220 face. Remap divides texinfo texels by the shader image size,
  so each texture's PNG keeps the BSP's texdata size and UVs match Source exactly. Units are 1:1.
- Static brush entities (`func_brush`, `func_wall`, `func_lod`, `func_wall_toggle`). Doors,
  breakables, triggers and moving brushes are dropped, so their openings are open.
- Player clip becomes the `_clip` material. Water, monster clip and other non-solid contents are dropped.
- Displacements, as `patchDef2` patches of their (2^power+1)² vertex grid. The grid is transposed
  where rows x columns would face into the surface; facing them the wrong way made them invisible.
  Patches are Bezier-sampled, so terrain is slightly smoothed.
- Materials: VMTs are resolved through the map's pakfile first, following cubemap `patch`
  materials to their base, and grouped by `$basetexture`. Textures are converted to BC1, capped at 1024 px.
  Alpha is composited onto dark grey; clear `$translucent` glass becomes invisible solid.
- Lights: `light` and `light_spot` become static baked lights, `light_environment` the sun.
  Source lights without distances get `_zero_percent_distance` = 100*sqrt(brightness/2), clamped 256-2048.
- 2D skybox: the six faces are reprojected into the Minecraft ports' azimuthal sky dome.
  The camera-fixed 3D skybox room is found as the smallest group of touching brushes around
  `sky_camera` and removed with everything inside it.
- Static props, from the `prps` game lump: LOD 0 of each body part's first model (MDL, VVD with
  fixups, `.dx90.vtx`), placed with Source's AngleMatrix, with the skin's materials. Triangle winding
  is kept: Respawn front faces wind clockwise like Source's (every triangle in RSM1 recovered from retail
  maps has `cross(b-a, c-a)` against its normal). Reversing it, as the first props build did, drew props
  inside out. Meshes are cut into lightmap charts (connected faces sharing a dominant
  axis, projected along it at 16 units per luxel). They go to remap in an RSM1 file named by the
  new worldspawn key `_remap_props`, which adds render meshes alongside the brushes, unlike
  `_remap_mesh`, which replaces brush rendering. Props with collision get one nodraw brush per
  convex piece of their `.phy` (IVP ledges, metres with Y down, converted to inches with Z up).
  Only the ledge tree's leaves are pieces: internal nodes also point at ledges, the convex hull of
  their whole subtree, and reading those filled Jump Academy's spawn cave with solid.
  Cutout and translucent prop parts (foliage cards, wires, glass) are skipped, as are props
  inside the 3D skybox room. `--no-props` leaves props out.
- Spawns: TF2 team spawns, otherwise HL2 ground `info_node`s at the two ends of the map's main axis.
  `--spawns X1 Y1 X2 Y2` overrides this.

Not converted: dynamic and physics props (`prop_dynamic`, `prop_physics`), the 3D skybox's
contents, water, decals, overlays, normal maps and cutout transparency.

## Results

`d1_trainstation_02` (0.1.0): 1,893 brushes, 3 displacements, 134 textures, 444 world meshes. It
compiled, passed validation and loaded in Northstar. All 8 spawns probed clear. Textures, sun
shadows, the overcast sky and the displacement grass rendered. Below the horizon the sky dome's
floor shows where the 3D skybox's distant city used to be.

With props: 290 of 299 placed (9 are in the 3D skybox), 31,142 lightmap charts, 1,512 collision
pieces, 69 cutout or translucent prop meshes skipped, 740 world meshes. Trees, street lamps,
benches, fences and the monument rendered lit, with baked shadows. Traces hit the trees and lamps
at their trunks and posts. Traces at two benches were inconclusive. That build drew props inside out
and gave multi-piece props an extra hull around the whole model; the 3 November rebuild fixes both and
loaded with all 8 spawns clear.

Team Fortress 2 was not installed on the test machine (its folder had no maps), so `ctf_2fort` is untested.

`jump_academy2_rc9` (TF2 rocket-jump map, the official BSP from jumpacademy.tf, without TF2 installed):
8,808 brushes, 1,194 displacements, 2,194 static props (186 unreadable without TF2's models), 356
textures, of which 152 are TF2 stock textures and became flat grey. Its 264 `trigger_teleport`s become a
server script that checks each player against the trigger boxes every 0.05 s, which carries both
the fall resets and the course doors. Two triggers placed in game sent the player to the right
destinations. The map is about 30,000 units across, so it needed the large-map settings below:
48 units per luxel on six 2048-pixel pages, 670 meshes, a 414 MB BSP. Tested in game: both spawns
and the teleport destination stand on floor, 13 of 13 sampled terrain displacements collide at their
surface height, the course doors show their labels, and there is no magenta. Earlier builds showed
magenta z-fighting on the terrain because remap drew the nodraw displacement collision patches; it now
skips them.

## Large maps

- Displacements render from their full grid, but collide through a 5x5 nodraw copy
  (`_remap_contents_N 0` turns off the render patch's collision): remap makes one collision piece per
  grid quad, and a thousand displacements overflow its 16-bit ranges.
- remap coarsens the collision grid when primitives spanning many cells would overflow the 16-bit
  GeoSet ranges.
- Meshes split per material and lightmap page. `_remap_lightmap_by_material 1` packs lightmaps
  material by material, so each material spans one or two pages; with hundreds of materials this
  took Jump Academy from 4,002 meshes to under 700.
- `_remap_luxelsize` (default 16) and `_remap_lightmap_pagesize` (default 1024) set lightmap
  resolution and page size. The builders use 2048-pixel pages and raise the luxel size until the map
  fits six pages (the most tested in game) and 1,000 meshes. `--luxel-size` and `--mesh-cluster`
  set the starting values.

# Counter-Strike 2 (Source 2) map ports

`tools/respawn/build_source2_ports.py` converts a CS2 map package. Source 2 resources are read through
[Source2Viewer-CLI](https://github.com/ValveResourceFormat/ValveResourceFormat) (release 20.1): it
exports the world's render meshes and textures to glTF and dumps the physics and entity lumps as
KeyValues3 text, which `tools/respawn/source2_engine.py` parses. Compiling and packaging are shared
with the Source 1 converter.

```powershell
python tools/respawn/build_source2_ports.py --vpk "...\game\csgo\maps\de_nuke.vpk" --vrf PATH_TO\Source2Viewer-CLI.exe --gameinfo "...\game\csgo\gameinfo.gi" --export EXPORT_DIRECTORY --name nuke --display-name "Nuke (CS2)" --output NEW_DIRECTORY --remap install/Release/remap.exe --repak PATH_TO_REPAK.exe --material-template PATH_TO_NATIVE_MATERIAL_BASE
```

- Coordinates: Source2Viewer writes Source (x, y, z) inches as glTF (y, z, x) metres.
- Render meshes become RSM1 charts (`_remap_props`). CS2 world meshes are far above the Titanfall 2
  world index budget (about 1M triangles; `de_nuke` is 3.6M), so vertices are snapped to the smallest
  grid (1, 2, 3, 4, ... units) that fits 950k triangles. Each triangle keeps its own texture coordinates
  and normals, so texture seams survive. Cutout and blended materials, tools, wires, decals and the
  skybox buildings are left out. Textures are base colour only, with the material's colour factor.
- Collision comes from `world_physics.vmdl_c`: each convex hull's face planes (`m_Hull.m_Planes`,
  normal and offset; `m_pRegionSVM` holds unrelated split planes) become a nodraw brush, and the
  triangle meshes are welded at 6 units and paired into two-triangle collision patches. Hulls and meshes
  whose collision attribute interacts as player clip become `_clip`; bullet-, grenade- and sound-only
  ones are dropped.
- Spawns are `info_player_terrorist` and `info_player_counterterrorist`; `light_environment` becomes the
  sun and `light_barn`/`light_rect`/`light_omni` become static point lights using `range` and
  `brightness_legacy`.

- Textures smaller than 4x4 are enlarged: Source2Viewer exports constant-colour materials as 1x1
  images, and an rpak with a BC1 texture smaller than one block never finishes loading. The game hangs
  at the map change, spinning in `rtech_game.dll` under Northstar's pak-load hook, before any
  `LoadPakAsync` line is logged.

`de_nuke`: 818k render triangles (4-unit grid), 5,987 collision hulls, 29,304 collision patches,
173 lights, 626 meshes, six lightmap pages at 16 units per luxel, a 469 MB BSP. In game it loads with
7 of 8 spawns clear for a pilot. The yards, roofs, silo, catwalks and props render with baked sun
shadows; walls facing away from the sun are very dark (no bounce light). Traces hit the yard, roofs
and lower floors at the render heights from above and below. Doors, glass, decals, the chain-link
fence cards, foliage and the skybox city are missing.
