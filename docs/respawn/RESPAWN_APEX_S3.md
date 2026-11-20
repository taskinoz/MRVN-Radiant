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

Retail samples: S0, S1 and S2 Canyonlands and S3 Aqueduct (see
[RESPAWN_SAMPLES.md](RESPAWN_SAMPLES.md)). All four use rBSP 47, header
revision 30, and version 0 for every lump. Static props are 64-byte records
in every season (derived from the stored prop count: game lump version 47,
same parented-prop tail). Meshes and mesh bounds give the same record count
at 28 and 32 bytes. World-light and light-probe lump lengths are whole
multiples of the 112- and 48-byte records the compiler writes in every
season; that is consistent, not proof.

The one structural difference found is lightmaps:

| | S0–S2 | S3 |
| --- | --- | --- |
| Lightmap header (lump 0x53) | `01 00 00 00`, 1024 × h | `01 08 00 00`, 1024 × h |
| Lump 0x61 | absent | 2 bytes per lightmap texel |
| Lump 0x69 (real-time light data) | 6.5 bytes per texel | 6.5 bytes per texel |

S3 accepts the S0–S2 form: our output uses header type 1 without the S3 flag
and loads and renders. So one output should suit all four seasons. That is
an inference from matching layouts. S0–S2 have no harness here and are
**not** natively tested.

## Open work, in order

1. **Real-time light data (0x69, 0x7A).** Every retail season has it; we
   write none. S3 loads without it, but real-time lights probably will not
   shade lightmapped surfaces correctly.
2. **Lights in game.** Check point/spot light baking visually and compare
   with retail intensities.
3. **Brush entities.** `func_brush`, doors and other movers through the
   `*coll` entity collision path.
4. **Visibility.** Measure culling with the fork's cells and portals on a
   large map; the vis tree must stay within its 8-bit reference counts.
5. **S3 lightmap extension (0x61).** Optional; identify it before emitting.
6. **S0–S2.** Find a way to run custom maps in those builds, or document
   that the shared layout is the only evidence.
7. **Navigation.** R5 maps use separate navmesh files; none are generated.
8. **GPU baking.** The fork's HIPRT path is built only when its SDK is in
   `windeps/hiprt`; the CPU path is used otherwise.
