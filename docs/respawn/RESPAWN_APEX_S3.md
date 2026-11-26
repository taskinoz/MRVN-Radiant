# Apex Legends S0–S3 compiler: S3 first

Started 20 November 2026. Goal: `remap -game apexlegends` produces maps that
load and play in Apex Legends seasons 0–3, verified first in Season 3 through
R5Reloaded, the playable build with a local harness. Written with AI; see
[AI.md](../../AI.md).

## Where the backend comes from

The Apex backend in `tools/remap/source/apex_legends/` is now the one from
[r5valkyrie/MRVN-Radiant](https://github.com/r5valkyrie/MRVN-Radiant), branch
`feat_lightmap_tweaks`, commit `2c5564d` (8 April 2026), which builds on that
fork's `main` (`5f7caa5`). It is GPL-2.0-or-later, like the files it replaces.
It replaced this fork's stub backend, which loaded in S3 but had **no
collision**: the player fell through the floor.

Before porting, the fork's own compiler was built unchanged and its output
tested natively. A dev-textured box rendered with lightmaps in the S3 client,
and ten line and hull traces matched the geometry. That made the fork the
right base. The other forks of MRVN-Radiant were checked on 20 November 2026
with GitHub's compare API: none except r5valkyrie (125 commits ahead of
upstream) carries Apex compiler work.

Changes made while porting (commits on branch `apex-s3-compiler`):

| Change | Why |
| --- | --- |
| Shared hooks: `_nocollision` func_groups, `-nolightmaps`, `-nolightprobes`, `-singlelightprobe`, `g_compileHandledEndBSP`, R5 lump names, phase/progress output | The backend needs them; Titanfall output is unchanged |
| Sky faces are not meshes for v47 only | Apex draws sky from portals and the sky lightmap; TF1/TF2 keep their sky meshes |
| Prop editor copies: `mdl/x.rmdl` finds `models/mdl/x.obj` | The compiler needs readable geometry to bound a prop and place its collision leaf; the game lump keeps the `.rmdl` name |
| Lightmap charts per face | The fork projected each merged mesh onto its first triangle's plane, so every wall of a one-material room shared degenerate UVs |
| 1024-wide lightmap pages trimmed to used rows | Matches retail headers (e.g. 1024×968); a test box went from 134 MB to 3 MB |
| Chart origins on the chart plane | Fixes texel positions on sloped faces |

## Tools

| Tool | Use |
| --- | --- |
| `tools/respawn/stage_r5_map.py` | Package a compiled BSP for R5Reloaded (client and server VPKs, all five `.ent` partitions, level `.rson`/`.kv`, a bounds script) and install/uninstall it. Only `mp_mrvn_*` levels; refuses to overwrite files it did not install |
| `tools/respawn/cast_to_obj.py` | Convert RSX Cast model exports into OBJ editor copies for props |
| `tools/respawn/apex_native_regression.py` | Compile a fixture room, install it, load it on a dedicated R5 server through `r5_harness.py` and check traces against the fixture geometry |
| `tools/respawn/r5_harness.py` | The existing headless R5 controller ([RESPAWN_R5_HARNESS.md](RESPAWN_R5_HARNESS.md)) |

```powershell
# editor copies for props (RSX 2.4 CLI)
rsx_nogui.exe -nogui -export -exportfullpaths --exporttypes mdl_ --exportdir EXPORT R5R/paks/Win64/common_mp.rpak
python tools/respawn/cast_to_obj.py --tree EXPORT ASSETS        # writes ASSETS/models/mdl/...obj

# compile, stage and test
remap.exe -game apexlegends -fs_basepath BASE -bsp BASE/mp_mrvn_x.map   # BASE/assets holds shaders/ and models/
python tools/respawn/stage_r5_map.py --bsp BASE/mp_mrvn_x.bsp --level mp_mrvn_x --output PKG --game R5R --install
python tools/respawn/r5_harness.py --game R5R --state-dir .local/h      # leave running
python tools/respawn/apex_native_regression.py --remap install/Release/remap.exe --game R5R `
    --connection .local/h/connection.json --work-dir NEW_FOLDER --assets ASSETS
```

Tool textures (`tools/toolstrigger` and so on) come from the MRVN resource pack;
the r5valkyrie gamepack's `tools.shader` works. Map materials must already be
in a pak the level loads; `world/dev/dev_gray_512` is always available.

## Verified in Season 3

R5Reloaded SDK v2.3 (Flowstate scripts 4.1), dedicated server and rendered
client, 20–21 November 2026:

- **Fixture room** (`apex_native_regression.py`): 14 of 14 checks pass.
  Floor, ceiling, walls, block top and side, ramp at two heights, hulls
  against ceiling, block and wall, barrel side and top, trigger non-solid and
  trigger entity bounds. Traces stop about 1/32 unit short of a surface,
  which the tolerance allows.
- **Rendered client**: dev textures, per-face lightmaps with corner
  darkening and prop contact shadows, three `mdl/containers/barrel.rmdl`
  props, the sloped ramp.
- **Trigger**: a `trigger_multiple` spawns with its brush bounds, is
  non-solid and `IsTouching` reports the player only while inside.
- **Scale**: the recovered TF2 `mp_box` (274 entities, recovered render
  meshes, collision brushes) compiles in under 4 s to a 35 MB BSP, loads on
  the client and its floor traces match the spawn heights. Its TF2 materials
  render as the missing-material checkerboard, as expected.

Not yet verified in game: point and spot lights in the lightmap (the baker
follows VRAD, so a `light` without `_quadratic_attn` has constant falloff),
moving brush entities other than triggers, visibility culling with the
fork's portals and cells, and multiplayer.

## Seasons 0–3 compared

**Use maps that shipped with Season 3 as the S3 reference.** R5Reloaded
also carries maps backported from later seasons. The `Apex s3` install is
build `R5pc_r5launch_N1094_CL456479` (30 October 2019); its Aqueduct and
Ash's Redemption VPKs are later additions, and Aqueduct (an Arenas map) is
a backport. The S3-native references used from 21 November 2026 are
World's Edge (`mp_rr_desertlands_64k_x_64k`, new in S3) and the Firing
Range (`mp_rr_canyonlands_staging`), extracted from that install.
Kings Canyon `mu1`/`mu1_night` also shipped with it.

Retail samples: S0, S1 and S2 Canyonlands, S3 World's Edge and Firing
Range (see [RESPAWN_SAMPLES.md](RESPAWN_SAMPLES.md)). All use rBSP 47,
header revision 30 and version 0 for every lump. Static props are 64-byte
records in every season (game lump version 47, same parented-prop tail).
Meshes and mesh bounds give the same record count at 28 and 32 bytes.

What the backported Aqueduct has that S0–S3 maps do not:

| | S0–S3 (shipped) | Aqueduct (backport) |
| --- | --- | --- |
| Lightmap header (0x53) | `01 00 00 00`; page sizes vary (1088×1032, 960×952, 384×328, 1024×968), multiples of 8 | `01 08 00 00` |
| Lump 0x61 | absent | BC7 copy of both lightmap planes, 2 bytes per texel |
| Lump 0x2B | empty | 28 bytes |
| PAKFILE (0x28) | `materials/maps/<map>/cubemaps.hdr.vtf` (stored zip) | empty zip |
| Real-time light data (0x69) | 6.5 bytes per texel (6.0 in external sidecars) | 6.5 |

So the earlier reading of 0x61 and the `0x08` header flag as "S3 features"
was wrong: they come from the later-season backport. The compiler writes
neither, which is correct for S3. Our output loads and renders in S3; one
output should suit all four seasons, an inference from matching layouts
(S0–S2 have no harness here and are not natively tested).

## Lighting, shadows and visibility (21 November 2026)

First measured on `mp_rr_aqueduct`, then re-checked on S3-native World's
Edge and Firing Range (see above), cross-checked against the R5 SDK's
`dlightprobe_t`, and tested in R5Reloaded. Everything in the table holds on
the S3-native maps, with the corrections in the next section.
The fork had each of these wrong in ways the engine tolerated without
crashing; what was fixed is listed with its in-game evidence.

| Data | Retail encoding | Fork | In game now |
| --- | --- | --- | --- |
| World lights (0x36) | Linear `_light` × brightness/255 (×100000 for `_pbr_falloff 1`); attenuation 1 + b·d + c·d² through (0,1), (d50,0.5), (d0,0), radius d0; flags 0x04 non-PBR, 0x20 PBR, 0x08 realtime, 0x10 no realtime shadows, 0x40 `realtime_shadows 2`, 0x80 `script_tweakable` (also sets 0x08); order ambient, sun, tweakable, realtime shadowed, realtime, static spots, static points. All 359 retail records match. | VRAD attenuation, 0x04 read as "PBR", 0x18 on every light | Matches retail |
| Mesh records (0x50) | After `triCount`: first vertex, last local vertex, vertex pool \| cubemap << 8, 0, 0, lightmap texel origin x, y, 0 (TF2's layout) | u32 offset, u32 count, type in the wrong field | A vertex count of 0 had made static lights wash the room white |
| Lightmaps (0x62) | Plane A RGBM `rgb·(a/255·3.984375+0.015625)`, baked static light + ambient fill, no sun; plane B bent sky direction × cbrt(sky visibility), alpha = sun visibility | RGBE in both planes | Coloured static lights with falloff; sun patch and pillar shadow through a sky opening |
| RTL (0x69, 0x7A), all seasons | Per page: u32 slot plane (four 6-bit slots, page byte), two BC5 visibility textures (slots 0/1, 2/3), one BC4 plane (zero); external sidecars omit the BC4 plane. Pages: 63 u16 hardware indices (world − ambients); 99.96% of retail slot lights lie within range under this reading | Not written | A realtime spot lights the floor with a realtime pillar shadow |
| Probes (0x65) | 12 SH values, sky vector, sun visibility, 4 weights at +0x20, 4 hardware indices at +0x24 | Indices at +0x18, `0x96` as first index | Format matches; character lighting not yet checked in third person |
| Visibility (0x77–0x79, 0x25, 0x27) | One root per cell; internal nodes before leaves; unmixed child blocks; depth-first references; 0x25 subtree totals per internal node; 0x27 u16 per node | One ±50000 root, 8-bit count of every reference | 320 barrels all draw (the fork dropped objects past 255) |
| CSM (0x63, 0x64) | u32 refs: every shadow mesh plus shadow-casting props by object id; light-space node bounds | Shadow meshes only | Barrels cast sun shadows |

Static lights are baked into plane A and probe SH; RTL slots and probe light
references are used for realtime lights only, as in Titanfall 2. Retail also
lists static lights in RTL pages and probe references; giving static lights
only RTL slots did not light surfaces with their colour or falloff, so that
part of retail behaviour is not reproduced.

Lump 0x61 (later seasons, header flag `0x08`) is a BC7 copy of the two
lightmap planes, two textures per page; S3 maps do not have it.

Lightmap shadow rays use `Respawn::Bake::Occluders` built from opaque world
brushes (sky brushes let rays out), replacing a scan of every triangle per
ray. Props and patches do not yet occlude baked light.

## Corrections from S3-native maps (21 November 2026)

Re-checking against World's Edge and the Firing Range confirmed the
world-light encoding (flag rule, falloff fit, cones, shadow fields), mesh
records, both lightmap planes (plane B alpha is 0 on every surface facing
away from the sun; its direction points mostly up), RTL planes and BC5
visibility, and the CSM reference split. It changed these:

- **Tree indices are 22 bits.** World's Edge has 135,338 visibility nodes,
  539,490 references and 211,364 CSM nodes. Node words are `count |
  index << 8 (22 bits) | bit 30`; small maps show bit 30 as a `0x40` top
  byte. Both trees now use 32-bit reference indices, lifting the old
  65,535-object limit. One root per cell (265 on World's Edge) and one per
  shadow environment (2 on the Firing Range).
- **Node order and totals.** Retail interleaves internal nodes and leaves;
  0x25 and 0x26 hold each node's subtree total up to the last internal
  node. Writing internal nodes first remains valid.
- **RTL pages** hold world index minus every ambient before it: the Firing
  Range has two light environments, so values are world − 2 (98.3% of slot
  lights within range); `HardwareLightIndex` already counts this way.
- **Probes reference static lights too** (World's Edge: 805k static and
  637k realtime references). The compiler still references realtime
  lights only, because static lights are baked into the probe SH; whether
  retail's SH excludes them is not known.
- **Cubemaps** are one VTF 7.5 in the PAKFILE: 256×256, one frame per
  cubemap, format 66 (Respawn-specific, about one byte per texel, probably
  BC6H), 9 mips, flags `0x420c`, and a `CMA` resource. The compiler does
  not write it yet.

## Character lighting (26 November 2026)

Without a HIPRT SDK the fork's probe pass skipped every ray test: probes
got the full sky indoors (the same blue-grey ambient everywhere) and were
placed at the lowest mesh height, on the floor. `hiprt_trace.cpp` now takes
a CPU closest-hit function and uses it whenever no GPU scene exists; the
Apex lighting pass registers its brush occluders. Probes now sit above the
floor and their SH follows the scene (beside an orange static light
0.19/0.13/0.15, in an unlit corner 0.05/0.07/0.14). In R5Reloaded, third
person (`player.SetThirdPersonShoulderModeOn()`), the character is tinted
orange by the static light, lit from above under a realtime spot through
its probe light reference, and dark in the unlit corner.

This commit reached `main` only on 28 November 2026. `main` had re-fixed
the same bug separately (APEX-16 in `GOALS.md`): probe batch helpers, void
probes dropped, spot cones that rank light links instead of gating them, and
96-unit spacing. Both are kept. The floor grid now walks every floor down
each column, not only the top one.

## Open work, in order

1. **Lightmap quality.** Patch and prop occlusion, bounce light, and filtering
   of the 32-ray sky term (jagged bands show on some walls).
2. **Brush entities.** `func_brush`, doors and other movers through the
   `*coll` entity collision path.
3. **Cells and portals.** The object tree is retail-shaped with one cell;
   measure culling with several cells on a large map. Trees allow 22-bit
   (4,194,303) node and reference indices.
4. **Cubemaps.** Bake cubemaps and write `cubemaps.hdr.vtf` into the
   PAKFILE in the S3 format above.
5. **S0–S2.** Find a way to run custom maps in those builds, or document
   that the shared layout is the only evidence.
6. **Navigation.** R5 maps use separate navmesh files; none are generated.
7. **GPU baking.** The fork's HIPRT path is built only when its SDK is in
   `windeps/hiprt`; the CPU path is used otherwise.
