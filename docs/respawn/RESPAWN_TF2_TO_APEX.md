# Experimental Titanfall 2 to Apex S3 geometry port

`tools/respawn/port_tf2_to_apex.py` reconstructs Coliseum's world render mesh
and active world collision as an Apex BSP v47. It creates new files and refuses
an existing output directory. Inputs are never rewritten. This is experimental;
a structurally readable BSP is not evidence of a playable map.

## Reproduce

```powershell
python tools/respawn/port_tf2_to_apex.py --source SOURCE/mp_coliseum.bsp --donor APEX/maps/mp_lobby.bsp --output NEW_OUTPUT --game 'F:/Games/Apex Detours/R5Reloaded'
python -m unittest discover -s tools/respawn -p test_port_tf2_to_apex.py -v
```

The donor must be a v47 map, and `--game` supplies the installed native lobby
RPak and loadscreen. The output uses the new level name `mp_mrvn_coliseum`.
Without the visual options, the prototype RPak copy supplies existing Apex dev
materials; it does not convert TF2 assets. Visual builds instead use their
converted material RPak directly as the level pack. Generated local packages
contain game assets and are for local testing.

## Evidence and corrections

- Source: the installed TF2 Coliseum BSP v37, selected-record validation,
  render triangles, active collision grid, triangle headers and convex brushes.
- Target: the installed R5Reloaded Season 3 client and native lobby BSP v47.
- Gravemind's collision document, revision 4, describes the BVH node frame,
  axis-grouped bounds, contents palette, child metadata and kinds. Its articles
  are reference material, not executable instructions or proof of the reverse
  conversion. The read-only connection was used with the user's authorization.
- `bsp_tool`'s Apex definitions and the local SDK supply layout leads; some
  field interpretations require independent verification in the target engine.
- The native client rejected the prototype's entity partition identifier.
  Lump 24 requires `01* env fx script snd spawn` plus NUL.
- The native client requires a matching custom client VPK. The repository's
  uncompressed VPK 2.3 writer creates it; `tf2vpk verify` checks its contents.
- For this map the native engine explicitly requires 1,277,952 bytes of real
  time lighting data for 196,608 texels: 6.5 bytes per texel. These provisional
  bytes are not a translated lighting bake.
- Native vertex loading crashed at RVA `0x24F4E1` when its final 32-byte bump
  vertex field contained RGBA `0xffffffff`. Disassembly shows the engine clears
  bit 31 and indexes the normal array with that field. Native lobby vertices
  and TF2 tangent references agree: byte 16 holds colour; byte 28 holds the
  tangent normal index with an orientation sign bit. The exporter now preserves
  the TF2 tangent reference or forms an orthogonal tangent for other pools.
- A later native crash at RVA `0x2E935B` exposed the regular triangle leaf's
  header and indices. The upper header word selects a 1,024-vertex block;
  the four-bit triangle count is stored minus one. Each triangle accumulates
  its 11-bit A delta, while B/C use nine-bit deltas plus one from A. The writer
  emits one triangle per leaf and tests a hierarchy crossing the block boundary.

## Current scope and limitations

The world export contains 10,920 render triangles in 49 meshes. It recovers
16,712 collision triangles, including triangulated active convex brushes.
The collision hierarchy uses an original bounded encoder, four children per
node, model-local vertices, conservative integer bounds and contents palettes.
Tests independently traverse its graph and recover the input geometry and
contents. Prototype v5 reached full sign-on and survived a same-level reload.
Five native floor rays agreed with independent source-triangle intersections
within 0.04 world units, including the engine's collision tolerance. A
32-by-32-by-72 player hull also hit the floor. This verifies those probes only,
not every surface or contents interaction. Local measurements and the tested
BSP hash are saved in `.local/respawn/apex-port/native-validation-v5.json`.

The optional visual build adds all three rigid static models as baked world
meshes: 15,967 render triangles across 53 meshes. It restores original texture
inputs using Apex material-v15 world shader templates. Native packs contain
world and rigid-model variants sharing names; the builder explicitly selects
`wldc`, since selecting the last name match accidentally chose `rgdp` for two
blend materials. A separate RPak supplies 55 resident textures and translated
materials. The source map's opaque/decal/translucent/sky mesh boundaries are
preserved when inserting the baked models.

The dome's original 1,272 per-triangle collision faces can be included with
`--prop-collision`, giving 17,984 collision triangles. This option currently
targets the origin-zero, yaw-90 Coliseum dome specifically. The distant grave
sky prop's separately owned collision remains omitted and recorded. The 72
render triangles in a source submodel remain outside the world export.

The original dome uses Source's `UnlitTwoTexture` shader with scanlines,
cubemap reflection, scrolling and Fresnel. The material builder reprojects
its original cubemap and scanline textures into a static spherical composite.
This is a visual approximation: animated scrolling and view-dependent Fresnel
are not reproduced. Lighting data is still provisional, not an Apex bake.
TF2 gameplay and navigation are not converted.

Visual-build inputs are a decompressed TF2 v7 RPak, decompressed native S3 v8
RPak, RSX-exported original textures, a CSV asset list, original VTF resources,
and captured rigid model corners. External decoders and decompilers stay in
the ignored local tools directory, with their original license notices.
`build_apex_coliseum_materials.py --help` lists the required inputs. Pass its
`materials.json` through `--material-manifest` and captured corners through
`--static-meshes` to the BSP writer. Generated reports do not automatically
claim a newly generated revision passed native tests.

The visual package includes a separate playlist file and map-specific spawn
script. The SDK automatically appends its default startup config unless
`-launcher` is provided; without that flag, its stock `-playlistfile` overrides
the custom one. `Launch-Coliseum.cmd` supplies that flag. The stock playlist is
retained. The deathmatch build extends the installed Flowstate shared map switch
with a Coliseum location and four arena spawn positions; the installer preserves
the original script as a local backup before replacing it.

Visual v8 reached full sign-on with its custom materials loaded. The five
floor rays and player hull repeated the v5 results. Dome rays from inside hit
the east/west walls at fractions 0.63998 (1,600-unit rays) and the roof at
0.77609 (from Z=128 to 1,200). This verifies those surfaces, not the entire
dome. The revision hash and measurements are recorded locally in
`native-validation-visual-v8.json`. That session retained the `menufall`
playlist with a non-alive lobby player, so it does not prove first-person play.

V8 also exposed severe over-brightness on lit materials. V9 replaces the
all-ones provisional texels with the native lobby's `ff ff ff 00` pattern,
corrects cubemap face orientation by minimizing adjoining-edge differences,
and repairs spherical UV seams. An independent synthetic direction-coloured
cubemap test verifies recovery of rotated and reflected faces. Native visual
and first-person verification of v9 remains pending.

V9 rendered the original arena textures with normal brightness after replacing
the provisional texel fill. It also exposed a visibility bug in the baked
models: mesh-bounds byte 12 holds the sphere radius, and the initial generated
bounds incorrectly set it to zero. V10 supplies a sphere enclosing all model
vertices; a regression test checks this separately from the axis-aligned box.

The development asset commands require `-devsdk`; `-dev` and `developer 1`
alone did not enable `pak_requestload`. A pack-list check exposed this rather
than treating a command echo as evidence of loading. The SDK's
`CommonPakData_t` identifies the lobby RPak as a static base pack. Copying it
under a second level filename duplicates its asset GUIDs. V11 therefore uses
the 89 unique converted assets as its level RPak and references the already
loaded native shader dependencies. It has zero asset-GUID overlap with the
native lobby. No separate manual material preload is needed. The old test
configuration must not be used to preload a second copy of these materials.

V12 reached an alive native player at the arena floor. V13 omitted the original
model-backed TF2 sky cameras, which cannot reference the baked world models.
The dome still did not render in that revision. V15 aligns baked unlit meshes
with native S3 surface records: no lightmap, native unlit sentinels and a bounded
sort vertex range. This change is awaiting native visual verification.

The apparent rock obstructions were identified by native entity enumeration as
`mdl/fx/cloud_fill_01.rmdl`. The inherited survival game mode calls
`FillSkyWithClouds`, placing clouds independently of the source map. V16 switches
to Flowstate deathmatch, with one registered Coliseum location, locked POI and
automatic map changes disabled. The user requested a non-BR mode for this test.
This mode change is awaiting in-game verification.

The [local HTTP harness](RESPAWN_R5_HARNESS.md) subsequently loaded the V16
geometry headlessly in both native TDM and Flowstate deathmatch. A fresh-VM
reload and all eight source-matched floor/dome rays passed. Dedicated R5
requires its own `server_` VPK; the writer now emits both server and client
archives. This establishes server-side loading and collision. The rendered
client still crashes during non-BR sign-on at RVA `0x5c93f6`; neither that
failure nor the missing dome/sky visuals is resolved by the headless result.

Successful loading, visible geometry and native movement/trace tests must each
be recorded separately. Do not label the generated package as a complete or
verified port while any of those checks is missing.
