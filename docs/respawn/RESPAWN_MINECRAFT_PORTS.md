# Minecraft UMA and Glitch test ports

2 November 2026. Local, editable geometry ports of the user-selected worlds:

| World | Author | Input version | Selected blocks | Generated brushes | Textures |
| --- | --- | --- | ---: | ---: | ---: |
| [UMA](https://www.planetminecraft.com/project/ru-titanfall-2-uma/) | BirthdayTrain | Java 1.17.1 | 47,400 | 18,110 | 125 |
| [Glitch](https://www.planetminecraft.com/project/glitch-titanfall-2/) | Oblivering | Java 1.20.4 | 44,811 | 8,169 | 31 |

Glitch's author describes the Minecraft source as 55% complete and permits
derivatives with credit. Retain both authors' credits. These conversions are
local artifacts, not a publication or redistribution of the downloaded worlds.
Minecraft textures/models come from the official Java 1.20.6 client, SHA-1
`05b6f1c6b46a29d6ea82b4e0d42190e42402030f`, downloaded from the URL in the
user's installed launcher manifest. Minecraft assets remain Mojang/Microsoft's;
Titanfall assets remain Respawn's. Tool code is GPL-2.0-or-later.

## Outputs

Ignored `.local/respawn/minecraft-ports/{uma,glitch}-v5/` contains:

- `mp_minecraft_NAME.map`: editable classic MAP source for MRVN-Radiant.
- `assets/`: editor textures, shader declarations and native material inputs.
- `MRVN.MinecraftUma-0.5.1.zip` / `MRVN.MinecraftGlitch-0.5.1.zip`: Northstar mods.
- Matching `-source-0.5.1.zip`: MAP, editor PNG/shader assets and notes.
- Conversion, visibility-coverage, BSP-validation and spawn reports.

Delete any older copy of the mod folder, then extract into
`Titanfall2/R2Northstar/mods`. Load locally with `map mp_minecraft_uma tdm` or
`map mp_minecraft_glitch tdm`. Both use the installed Coliseum base pak plus their
own resident texture/material RPaks. They have four start and four respawn
positions for each team, baked sun/ambient lighting with sun shadows, solid brush
collision, a Minecraft sky dome and a block-built multiplayer menu stage.

## Converting a world

`tools/respawn/build_minecraft_ports.py` converts any Java world ZIP. It reads palette
Anvil chunks without extracting arbitrary paths, resolves blockstate variants and
multipart models, turns nonzero model boxes into brushes, merges full cubes with identical
faces, converts textures to resident BC1 RPak assets, compiles with remap and packages a
Northstar mod.

```powershell
python tools/respawn/build_minecraft_ports.py --name my_map --display-name "My Map (Minecraft)" --author AUTHOR --source-url URL --world WORLD.zip --jar OFFICIAL_CLIENT.jar --output NEW_DIRECTORY --remap install/Release/remap.exe --repak PATH_TO_REPAK.exe --material-template PATH_TO_NATIVE_MATERIAL_BASE
python -m unittest discover -s tools/respawn -p test_minecraft_ports.py -v
```

The material template is a paired `_wld.json/.uber` and `_colpass_wld.json/.uber` native TF2
world material, as used by the Box Genesis builder. Pass the base path before these suffixes.

Unset options are worked out from the world, and printed:

| Option | Default | Set it when |
| --- | --- | --- |
| `--bounds X1 Y1 Z1 X2 Y2 Z2` | Largest group of chunks with authored blocks, fullest height band | It picked a test copy or cut part of the build |
| `--anchor X Y Z` | Centre of the build; Y is the commonest walkable surface | The compile reports too few spawn sites on that floor |
| `--spawns X1 Z1 X2 Z2` | 15% in from each end of the longest axis | Team starts belong elsewhere |
| `--kill-z Z` | 768 units below the lowest block | The map has a death pit |
| `--invisible-block NAME[:MIN_Y]` | `barrier`, plus glass in any layer covering a quarter of the build | Other blocks are the author's containment |
| `--iron-bar-ziplines` | Off | Iron bar lines stand in for ziplines |
| `--fill-floor-notches` | Off | The world's terrain is missing a piece at its edge; enclosed pits stay open |
| `--spawn-open-sky` | Off | Spawns land in sealed rooms; don't use it under roof beams |
| `--terrain` | Off | The world is natural terrain (see below) |
| `--luxel-size N` | 16 | The compile exceeds the 1,000-mesh budget at the largest cluster |
| `--loadscreen IMAGE --loadscreen-template BASE` | Coliseum's image | You have a 1920x1080 capture |
| `--material-templates DIR` | Off: glass and holes drawn opaque | Always, once you have run `extract_material_templates.py`: glass blends, bars and levers are cut out, water shows |
| `--cutout-leaves` | Off | Leaves should show holes (more faces to draw) |
| `--redstone` | Off (`survival_games` preset: on) | The world has piston doors, iron doors or TNT traps worth working |

Check each new map in-game. A good loading screen needs a capture from a built map, so build
twice: once to take the shot (`impulse 200` hides the weapon, `cl_drawhud 0` the HUD), then
with `--loadscreen`. Presets `uma` and `glitch` hold the inspected settings for those worlds;
UMA's roof glass is `white_stained_glass:50`.

## Natural worlds: Survival Games

7 November 2026. *The Original Survival Games Map* (2012, probably Vareide) is a
forest island about 1,000 blocks across in a glass dome, saved before Minecraft
1.13. `upgrade_minecraft_world.py` upgrades it with the official 1.20.6 server
(`--forceUpgrade`, 75 s). At 48 units per block the island is 48,000 units, so
the `survival_games` preset converts the 321-block square around the cornucopia
(2.8 million blocks). Three limits fell in turn:

- **Collision brush index (16 bits).** One brush per exposed block gave 306,164
  brushes. Hiding buried faces and filling caves sealed from the sky still left
  140,036, because the bumpy surface merges poorly. `--terrain` therefore makes
  every textured material `$contentflag nonsolid` and adds collision as the same
  cubes merged by occupancy alone, as `_nodraw` boxes: 116,076 render brushes and
  39,358 collision brushes. Hidden faces use `_nodraw_ns` (nodraw and nonsolid):
  a plain `_nodraw` side is solid and would make its render brush collide. remap
  now leaves brushes with no contents out of the collision lumps
  (`CollisionBrushes`); before, they were emitted and spent the index.
- **Mesh budget.** With 23 lightmap pages, each texture was split once per page:
  1,166 meshes at the largest cluster. The worldspawn key is
  `_remap_luxelsize` (`_lightmapscale` has no effect on Respawn lightmaps);
  32 units gives 16 pages and 899 meshes.
- **Spawns.** No single floor height in terrain, so terrain mode accepts any
  height that passes the open-floor checks.

The BSP is 385 MB (lightmaps 134 MB, realtime-light lightmaps 151 MB), the player
ZIP 90 MB. It loads in Northstar with no script errors. 16 lightmap pages is more
than any earlier converted map used.

With water, glass and cutouts (7 November) the same build had 1,062 meshes even at
the largest cluster; the mesh count tracks remap's lightmap charts (one per mesh),
and a 40-unit luxel, which does not divide the 48-unit block, gave more charts
(1,366), not fewer. The preset now uses 48 units: 12 pages and 871 meshes
(64 units: 867).

## Glass, water and redstone (7 November 2026)

**Glass and cutouts.** With `--material-templates` (see
[RESPAWN_MATERIAL_TEMPLATES.md](RESPAWN_MATERIAL_TEMPLATES.md)) glass, stained
glass, panes and ice use the translucent template; textures with holes (more than
2% of texels below alpha 128) use the alpha-tested one. Their textures keep alpha,
uncompressed. In terrain mode a face against a see-through block of another
material is no longer hidden, so stone behind glass shows; faces between two
identical glass blocks still hide. UMA rebuilt this way: 15 stained-glass
textures blend and 9 textures (iron bars, levers, torches) are cut out; in
Northstar the yellow panes show the floor and walls behind them and levers draw
as thin handles with no backing.

**Water.** Titanfall 2 has no swimming. As in its single-player levels (BT-7274's
crash site), water is a see-through surface over a kill volume. Each top water
cell becomes a 1/16-block slab at 14/16 of the block (still water's surface) with
the tinted `water_still` texture, render-only. Columns deep enough to go under get
a kill volume from their bed to 64 units below the surface: pilots wade through
water up to about 1.3 blocks deep and die where they would be fully under.
Columns merge into rectangles by surface height, each reaching down to its deepest
bed. The level script tests players against them (with an overall box first) in
its fall-death loop, every 0.1 s. Survival Games: 133,204 water blocks, 585
surface brushes, 560 kill volumes; the boxes are also written to
`water-kill-volumes.json`.

**Redstone** (`minecraft_redstone.py`, `--redstone`). Redstone parts within two
blocks of each other form a circuit (which covers power passing through one
block). Circuits with an input and a moving output become script movers:

| Minecraft | Titanfall 2 |
| --- | --- |
| Button | Use key while looking at it within 2.5 blocks; springs back after 1.5 s |
| Lever | Use key; toggles |
| Pressure plate | On while a pilot stands on it |
| Piston, retracted | The block in front moves one block out |
| Sticky piston, extended | Head and the block it holds move one block back |
| Door | Swings 90 degrees about its hinge edge |
| TNT | Explodes 2 s later (radius damage over 4 blocks), once |

Every output of a circuit switches together: repeater delays, torch inversion and
clocks are not simulated, so puzzle or sequenced circuits only approximate the
original. Dispensers, lamps, note blocks and wire stay static. Moving blocks are
left out of the world; each group is a `func_brush` (`mrvn_rs_<circuit>_<m|d|t><n>`)
with its textured boxes plus `_nodraw` collision boxes, and **no origin key**:
remap writes brush models in world coordinates and the engine adds the entity
origin again, which put a test brush 2,150 units away. `RS_Init` parents each brush
to a `CreateScriptMover` (at the hinge for doors) and drives it with
`NonPhysicsMoveTo` / `NonPhysicsRotateTo`; use is read with
`AddButtonPressedPlayerInputCallback( player, IN_USE, ... )`. A test `func_brush`
in UMA rendered and moved this way in Northstar. Survival Games has 10 working
circuits (120 moving blocks): two piston doors, a lever-raised field of 24 iron
blocks, three pressure-plate TNT traps, two door circuits and smaller piston
mechanisms. In Northstar all 16 movers were found; circuits switched from the console
(`script RS_SetCircuit( 1, true )`; the function is declared global at the top of
the level script, as Squirrel requires) and a TNT trap exploded without script
errors. Most of these mechanisms are buried in hillsides or under the cornucopia,
so their movement was checked in the log, not on screen.

Squirrel pitfalls met here: a `?:` next to a vector literal (`a ? b : < 0, 0, 0 >`)
does not compile, and `global function` declarations must come before every
function in the file.

Coordinates transform to `(X,-Z,Y)` around the anchor at 48 Source units per block, allowing
a 72-unit pilot under two-block doors.

## Rendering corrections

**Visibility tree.** The first Glitch render exposed missing world geometry. The
legacy SAH tree could stop with more than 255 direct objects, then silently
truncate the serialized eight-bit reference count. `Shared::MakeVisTree` is now an
object BVH: each reference has one owner and leaves hold at most 64. The importer
checks coverage by traversing serialized nodes, not lump sizes.

**Meshes missing from view.** UMA drew neither its sky nor its menu stage with 10,323
meshes in 0.2.0. With 3,139 in 0.4.3, whole sections vanished at the reported position with a
110-degree camera or wider, and returned on turning away, while the same view at 90 degrees was
intact. A 929-mesh build was intact at every tested width up to 160 degrees. Only about 700
meshes are in view at 110 degrees, under the audited 2,048 draw batch limit, so the limit behind
this was not identified. Every traversal reference was present throughout.

- `_meshcluster` (worldspawn, units): `Shared::MakeMeshes` groups faces by material, lightmap page
  and grid cell, in material order. Unset, the existing AABB merge is unchanged. Sky stays one mesh.
- The builder compiles at 3,072-unit clusters and doubles the size until the map has at most 1,000
  meshes, failing if it cannot. That budget is measured, not an engine constant. Coarser clusters
  frustum cull less, but world indices stay near 11% of capacity.
- Per-map asset names. Northstar loaded every installed mod's Postload pak with
  Coliseum, so both ports' paks were resident on either map. They shared 24 asset
  names, including the sky, and one map could draw the other's copy. (Since
  7 November each map's pak is its `<level>_patch.rpak` instead; see
  [RESPAWN_NORTHSTAR_TEST.md](RESPAWN_NORTHSTAR_TEST.md#map-pak-lifetime).)
- BC1 textures (below).

**Blurry textures.** 16x nearest upscaling alone was not enough. UMA's 49.5 MB
uncompressed pak rendered low mips only: with its pak alone, cobblestone and the sky
were visibly low-resolution after ten seconds. BC1 keeps upscaled texels exact up to
RGB565 rounding, since each texel fills whole 4x4 blocks. UMA's pak is now 8.5 MB
and Glitch's 4.3 MB, and both render crisp. The threshold itself was not measured.

**Lighting.** Sky occlusion is on, with brightness 170 ambient. One-bounce light
stays off: at this density it left green and yellow blotches on flat block faces.

**Sky.** The dome is centred on each build. `sky_texture` is an azimuthal projection
(radius is angle from the zenith) of a flat 12-block cloud layer, so clouds shrink
toward the horizon like Minecraft's, with a square sun opposite the light direction.
It is ordinary constant-lit world geometry, not an engine sky surface, so it writes
depth and hides anything beyond it. A plain horizon-coloured floor sits under it.

**Menu.** `menu_scene_ref` is at Z 18000, above the gameplay dome, on a grass island
under its own smaller dome. At Z 8192, inside the dome, the stage and the retail
`models/menu/default_environment.mdl` were visible overhead from the arena.

The reusable prefab is the `mrvn_mp_menu` point entity, also importable from
`install/gamepacks/Titanfall2.game/Titanfall2/prefabs/mp_menu.map`. remap expands it
into the two script anchors, an isolated light environment with its volume, and a
key light. It adds no scenery. It compiled and ran in both ports; placing it through
the Radiant UI has not been exercised.

**Falling.** A server script kills pilots below the build, and at Z -192 on Glitch,
so its pit is a death hole like retail's. A `trigger_hurt` brush with `damage` keys
compiled but did not hurt in-game.

**Spots in shade.** Sky occlusion used a random ray rotation per texel. Where few
rays reach the sky, that became blotches. `_skyfixedpattern` (worldspawn) gives every
texel the same rays, with `_skysamples` 128. Unset, bakes are unchanged. Shadows deep
in Glitch's pit are still soft blobs, but pilots die above that depth.

**Ziplines.** Glitch's four iron-bar lines are removed and replaced with `move_rope`
pairs at their ends, using retail `mp_glitch`'s rope keys. A pilot pressing use while
falling past one rode it (`IsZiplining` true). The client seems to receive ropes only
near the player, so a free camera far from the player won't show them. UMA's iron bars
are windows and railings, and stay.

**Loading screens.** A retail loadscreen pak is one 1920x1080 single-mip BC1 texture and
one `material/loadscreens/LEVEL_widescreen_gen.rpak`. Pass `--loadscreen IMAGE` and
`--loadscreen-template BASE`, a `.json`/`.uber` pair taken from a decompressed retail pak.
Northstar loads a mod pak named `LEVEL_loadscreen.rpak` when the level asks for it, so
the Coliseum alias is dropped. Images are in-game captures composed after the retail
ones, taken with `impulse 200` to hide the weapon and crosshair. The retail Glitch
image's leaping pilot is not reproduced. The private match map image (`_lobby`) is not
built.

**Spawns.** Sites need a clear 5x5 of floor and air, headroom, and eight blocks' line of sight
toward the middle of the map, which they face. With `--spawn-open-sky` they also need open sky.

**Map names.** The loading screen and menus look up `#<level>`. Each mod adds
`mod/resource/<level>_english.txt` (UTF-16, listed under `Localisation` in `mod.json`) with the
name, `_ALLCAPS`, `_CLASSIC` and description tokens. Only English is written.

**Torches.** The builder floods the air reachable from the spawns, casts rays from head-height
wall spots, and places a torch every six or more blocks where under 20% of rays reach the sky, up
to 96 per map. Each is two non-solid boxes and a static `light` entity,
editable in Radiant. Static lights bake with shadows and use no realtime slots, so they light walls;
how much they light pilots was not measured. Torches sit straight rather than tilted.

**Invisible barrier.** A `_clip` material (`$compileflag nodraw`, `$contentflag playerclip`) adds a
roof 192 units above the build and four walls around its bounds, down below the kill height. It
casts no shadow. Launched pilots stopped at the UMA roof and east wall and at the Glitch roof.
Worlds' `barrier` blocks become clip too: UMA has 193, Glitch none. UMA's white glass from Y 50 up,
removed in earlier versions, is the author's containment, so it is clip again. Pilots can stand on
those invisible surfaces and on the outer walls' tops inside the barrier.

## Runtime checks

Both 0.5.1 BSPs loaded in the installed Titanfall 2 build through Northstar 1.31.13
in an isolated profile, with both mods enabled and switching maps in one session.
Checked in-game: the reported screenshot positions; eight-way camera sweeps inside
and above each build with no holes or missing sections; pilot and loadout menus on
the stage; falling kills; native start-spawn selection for both teams; floor and
32-by-32-by-72 hull traces at all eight sites per map.

These are load, render and spawn tests. Not tested: other players or real network
play, full traversal, wallrunning, competitive balance, or GPUs other than this
machine's. Camera sweeps sample views, so culling elsewhere is not ruled out.

## Scope and approximations

These are pilot-only local test ports. Auto-detection was tried on these two worlds only. No navmesh, Titans, AI, hardpoints,
CTF positions, audio layout, minimap artwork or multiplayer balancing pass.
Minecraft commands are not translated; redstone is approximated (above) only with
`--redstone`. Without `--material-templates`, glass and leaves have opaque alpha
backing and water is left out. Leaves keep their backing unless `--cutout-leaves`.
Textures use their first animation frame. Per-face model UV rotations/subrectangles use approximate world tiling.
Model-element rotations use unrotated bounds. Plants, signs/banners and
zero-thickness elements are omitted; state types are recorded in each report.
UMA's white-glass upper containment shell is invisible, so its roof looks open to the sky.

The supplied converters were inspected for workflow ideas:
[minecraft-to-vmf](https://github.com/potato1234x/minecraft-to-vmf),
[Sourcecraft](https://github.com/Garten/sourcecraft), and
[mca2vmf](https://github.com/gramx/mca2vmf). They target VMF/Source rather than
native TF2 materials and packaging. The Python converter explicitly lacks
brush optimization. No converter implementation was copied into this importer.
