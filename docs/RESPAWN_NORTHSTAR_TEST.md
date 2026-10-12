# Experimental Northstar E1M1 test

This is a geometry/compiler test, **not a complete playable Quake port**. The BSP
has selected format validation and independently verified VPK bytes. Engine
Version 0.1.1 loaded and rendered on the user's Northstar installation, with white
developer surfaces, incorrect shadows and blocked passages. Version 0.2.0 also
loaded but crashed when grappling a surface. Version 0.2.1 corrects the mesh
surface vertex fields described below and still requires an engine retest. The compiler still
emits placeholder lighting and other incomplete structures; loading can fail or
crash. No navigation mesh or Quake gameplay is included.

## Installation and testing

Version 0.2.1 fixes two compiler errors in surface ranges: `first_vertex` must be
relative to the material-sort base, and `num_vertices` is the last local index,
read inclusively by the engine. Triangle rendering used a separate, correct index
path, so the previous build could render while impact/decal queries read outside
the vertex buffer. The October 7 grapple dump faults at `engine.dll + 0xae74e`;
its surface record matches mesh 42, whose sort starts at vertex 4,984. The previous
offset added that base twice. See `RESPAWN_SURFACE_CRASH.md` for the evidence.
This fixes the demonstrated invalid range; the earlier explosion/particle crashes
have not yet been matched to a dump. Retest grapples, bullet impacts, grenade
explosions and surface particles after restarting Northstar.

Copy the entire `MRVN.QuakeE1M1Test` folder into `Titanfall2/R2Northstar/mods`, then
restart Northstar. Enable `MRVN.QuakeE1M1Test` in the Mods menu if necessary.
This adds `mp_quake_e1m1`; it does not replace the retail Coliseum BSP. Use a local
test session. Other clients would need the same mod to join this map.

Version 0.1.1 includes identical loose BSP/entity files under `mod/maps` alongside
the VPK. Northstar's map-command discovery enumerates loose mod BSPs, but does not
enumerate maps inside mod VPKs. Version 0.1.0 lacked the loose files and was rejected
as `not found or invalid` before any engine BSP loading. Restart Northstar after
updating, then `maps quake` should list `(MOD) mp_quake_e1m1`.

Open the developer console (launch Northstar with `-console` if needed), then run:

```text
exec mrvn_quake_e1m1
```

The configuration enables cheats for the test session, selects Pilot vs Pilot
(`tdm`) and issues `map mp_quake_e1m1`. Custom-map startup through this command
is experimental and needs an engine test. If the loading screen completes, use
`noclip` to inspect geometry; Quake doorways are much smaller than Titanfall's
pilot hull. `mat_fullbright 1` may help inspect the placeholder lighting if the
engine exposes that debug setting. Unsupported commands can simply be omitted.

Version 0.2.0 retains world/static wall geometry, discards solid trigger volumes,
removes doors to leave openings accessible, and omits liquid volumes, buttons and
moving platforms. No Quake game logic is implemented; elevators remain absent.
Twenty-four pilot spawn entities use the six source spawn locations for both
teams and both initial/respawn classes. Geometry now uses installed Coliseum
concrete and Boomtown wall materials instead of the plain developer material;
these are replacement materials, not original Quake textures.
An RPAK alias requests the installed Coliseum assets; no Respawn assets are
redistributed. The custom level script disables the dropship intro (the first
test produced an empty-dropship-array error) and evac epilogue. Two client menu
scene/camera anchors sit away from gameplay at approximately `(8192,8192,0)`;
Northstar creates its existing menu environment/model around those anchors.

The builder removes the compiler's unrelated hard-coded world-light and CSM
shadow-tree references for this test. This does **not** implement lighting:
lightmap headers/data remain placeholders, and correct dynamic lighting, probes,
CSM generation and static baking remain unfinished. Textured surfaces may still
look dark or incorrect. Do not treat this revision as a lighting compatibility
result. Real lightmaps require the compiler's lighting pipeline to be implemented.

If loading fails, preserve the newest `R2Northstar/logs` log and any crash report.
Check for `MRVN.QuakeE1M1Test`, `mp_quake_e1m1`, VPK mount errors, RPAK errors,
script compile errors and the message `MRVN E1M1 experimental geometry test loaded`.
Note whether the failure happens before map loading, while loading, or after
spawning. This distinguishes packaging issues from remaining BSP format defects.

To remove the test, disable the mod and restart Northstar, or move its folder out
of `R2Northstar/mods` while the game is closed.

## Sources and licenses

- Quake E1M1 / The Slipgate Complex: id Software, map by John Romero; source
  released by John Romero in October 2006. Retrieved from
  [fzwoch/quake_map_source](https://github.com/fzwoch/quake_map_source/tree/27abebaa3886bb0e3156cce3a604673d22b243f8),
  commit `27abebaa3886bb0e3156cce3a604673d22b243f8`. GPL-2.0; `COPYING`, original
  source and adapted MAP source are included. No Quake WAD images are included.
- Compiler: MRVN-Radiant / remap, including its NetRadiant lineage and Respawn
  format research attribution in `docs/RESPAWN_SOURCES.md` in the project.
- VPK layout and independent verification:
  [pg9182/tf2vpk](https://github.com/pg9182/tf2vpk/tree/b73c54d8e4245075ea207c7e51a2a86fdb94e4ff),
  commit `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff` (MIT). The package writer is
  original MRVN-Radiant GPL-2.0-or-later code; tf2vpk is not bundled.
- Mod structure, VPK mounting and RPAK alias behavior:
  [Northstar documentation](https://docs.northstar.tf/Modding/guides/gettingstarted/),
  [RPAK documentation](https://docs.northstar.tf/Modding/guides/tools/rpakmodding/),
  [NorthstarLauncher mod manager](https://github.com/R2Northstar/NorthstarLauncher/blob/42c635aef4929a8c8eaf4ee790efb6fa34ac56cc/primedev/mods/modmanager.cpp)
  and [map discovery](https://github.com/R2Northstar/NorthstarLauncher/blob/42c635aef4929a8c8eaf4ee790efb6fa34ac56cc/primedev/util/printmaps.cpp),
  source commit `42c635aef4929a8c8eaf4ee790efb6fa34ac56cc` (MIT), inspected locally
  to diagnose the 0.1.0 map-command rejection. No source or binary is bundled.
  No Northstar code is copied into the test script. Checked against the local
  Northstar 1.31.13 installation; no script VM or engine validation was performed.

## Rebuilding in MRVN-Radiant

Run from the repository root, choosing a new output directory each time:

```powershell
python tools/respawn/build_northstar_test_mod.py --map .local/respawn/map-trials/e1m1-tf2/e1m1.map --copying .local/respawn/map-trials/e1m1-tf2/COPYING --remap install/Release/remap.exe --tf2vpk .local/respawn/tf2vpk.exe --output .local/respawn/northstar-e1m1
```

### Textures, lights and sun (0.3.0)

With `--materials`, each Quake texture keeps its own material instead of the
two Coliseum stand-ins. Build the materials first:

```powershell
python tools/respawn/build_quake_materials.py --map .local/respawn/map-trials/e1m1-tf2/e1m1.map --textures <LibreQuake>/texture-wads --template-pak <decompressed mp_coliseum.rpak> --repak <RePak build> --license <LibreQuake>/docs/COPYING --output .local/respawn/quake-materials
python tools/respawn/build_northstar_test_mod.py ... --materials .local/respawn/quake-materials --sun --output .local/respawn/northstar-e1m1-0.3.0
```

- **Texture source:** LibreQuake (BSD-3-Clause), since id's textures are not used.
  Each name is resolved as an exact match, LibreQuake's renamed form
  (`+` becomes `plus_`, `*` becomes `star_`, optional `_fbr`), or a recorded
  same-family substitute. For E1M1 that is 21 exact, 5 renamed and 38
  substitutes; `materials.json` lists every choice and its source file.
- **Materials:** each clones Coliseum's `world/concrete/concrete_plates_plain_wet_bm`
  (shader set, uber buffer, depth passes, colpass), with a mipped sRGB albedo and
  flat normal/gloss/spec maps.
- **Build:** RePak is built from r-ex/RePak `adc52f7`, the same commit the
  apex-to-titanfall-2 converter uses. The September 2022 `RePak.exe` release
  does not support this material JSON. The template pak is a copy of the game's
  `mp_coliseum.rpak`, decompressed with `rpak_ddecomp`.
- **Packaging:** the RPak is loaded through `Postload` after the aliased
  Coliseum pak. A v8.0 STBSP lists every drawn material.
- **Tools and sky:** `CLIP`, `TRIGGER` and `SKY*` become tool shaders.
- **Lights:** light entities are now kept (they were previously dropped), so
  remap bakes them. `--sun` adds a `light_environment`.
- **Baked maps:** placeholder-lighting removal is skipped for maps remap baked.

The output includes the mod, ZIP, adapted source, compiler log, BSP validation,
member SHA-256 hashes and independent VPK CRC/readback verification. Dependencies
and game assets stay outside the distributable mod. The included adapted MAP and
the compiler/package scripts in the MRVN-Radiant repository provide its source.
