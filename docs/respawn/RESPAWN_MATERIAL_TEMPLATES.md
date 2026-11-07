# Translucent and alpha-tested Titanfall 2 world materials

7 November 2026. The map converters clone a retail world material for every
texture they write. With only an opaque template, glass was either solid or
invisible, and fences, bars and other textures with holes were drawn on a solid
backing. `tools/respawn/extract_material_templates.py` adds a translucent and
an alpha-tested template, verified in Northstar (UMA's stained glass, levers and
lightning rods).

## 1. Decompress Coliseum's pak

Titanfall 2 paks are v7 RPaks, compressed with the same RTech stream as Apex's
v8 ones; only the header differs (88 bytes, decompressed size at offset 40). A
local driver around RSX 2.4.0's decoder (`decode_v7.cpp`, AGPL, not distributed)
decompresses them:

```text
decode_v7.exe C:/Games/Titanfall2/r2/paks/Win64/mp_coliseum.rpak mp_coliseum.rpak
```

Base paks decode on their own; the numbered `(01)`..`(11)` files are patches, which
`rpak.py` does not apply. RSX itself (`rsx_nogui.exe -nogui --list out.csv <pak>`)
applies patches and lists asset GUIDs with names, which is how the shader sets
below were named.

## 2. Write the templates

```text
python tools/respawn/extract_material_templates.py mp_coliseum.rpak --output material-templates
```

| Template | Retail source | Shader set |
| --- | --- | --- |
| `cutout_wld`, `cutout_colpass_wld` | `world/mcor/kodai_ind_decals_01` | `uberCutSamp2222_wld` `0x3A363050A9C4DD83` |
| `cutout_shadow_wld`, `cutout_prepass_wld` | its depth materials | `uberDepthCut_wld` `0xB652A023F2E776EE` |
| `cutout_vsm_wld` | its VSM material | `uberDepthVsmCut_wld` `0xEF72714EED5391D5` |
| `translucent_wld` | `world/decal/blood_splat_01` | `uberVcolaoVcolaTransSamp2222_wld` `0x0DA553C61F3FF3C3` |

All four shader sets live in `mp_coliseum.rpak`, which every converted map
aliases as its level pak, so nothing has to be embedded. Both materials use the
same four texture slots as the opaque template (albedo, normal, gloss, spec).

The sources are decals, so the extractor replaces their decal flags with the
values retail uses for ordinary world surfaces:

| Material | glue | depthStencil | rasterizer | Retail model |
| --- | --- | --- | --- | --- |
| cutout | `0x72000001` | `0x17` (writes depth) | `0x6` (no depth bias) | Crash Site `thaw` foliage (`0x17`) |
| cutout colpass | `0x72000001` | `0x5` | `0x6` | |
| cutout shadow / prepass / VSM | `0x10200090` | `0x17` | `0x26` / `0x6` / `0x2` | thaw foliage depth passes |
| translucent | `0x72000003` | `0x7` (no depth write) | `0x6` | `aquarium_interior_glass_01`, `ts_window01` |

Cutouts need their own depth materials (`$depthShadowMaterial` etc. as JSON paths;
RePak builds them). Each samples only texture 0, the albedo, for its alpha. With the
default `code_private` depth materials the holes fill the depth prepass and cast
solid shadows. Translucent materials have no depth or colpass materials, as retail
glass doesn't.

Other retail candidates, for reference: Crash Site has opaque and translucent
water (`world/water/water_wild_01_opaque`, `world/homestead/homestead_water_01`),
but their shader sets are `_fix` (model vertex layout) or only in single-player
paks; `uberTransSamp2222_wld` (plain translucent world) is only in single-player
paks too.

## 3. In the converters

Pass the directory as `--material-templates`:

- **Minecraft:** glass and ice blend; other textures with more than 2% of texels
  below alpha 128 (iron bars, levers, torches, flower pots) are alpha-tested;
  leaves only with `--cutout-leaves`. Water becomes a blended surface (see
  [RESPAWN_MINECRAFT_PORTS.md](RESPAWN_MINECRAFT_PORTS.md)).
- **Source:** `$translucent` materials blend (glass is no longer made invisible)
  and `$alphatest` ones are cut out, on brushes and props.
- **Source 2 (glTF):** `BLEND` materials blend and `MASK` ones are cut out.

Textures that keep alpha are written uncompressed (RGBA8): BC1 has no alpha
gradient.

## Compiler support

Shaders mark the two kinds for remap:

- `$compileflag trans` (existing): translucent. Sorted after opaque meshes.
- `$compileflag alphashadow` (new, all three games): alpha-tested. Like translucent
  brushes, these become detail, are not opaque to visibility, and hide no faces
  they touch, in either remap's coincident-face pass or the Respawn CSG pass.
  Titanfall 2 already wrote alpha-tested shadow meshes
  (SHADOW_MESH_ALPHA_VERTICES) for this flag, but no shader could set it.

Remap's Titanfall 2 world vertices carry white vertex colour with alpha 255, so the
`Vcola` (vertex-colour alpha) translucent shader takes its opacity from the
texture alone.

## Baked shadows

The Titanfall 2 lightmap bake (`titanfall2_lighting.cpp`) shadows with brushes and
mesh triangles as solid occluders and cannot sample alpha, so an alpha-tested fence
baked a solid dark band across Nuke's yard. Alpha-tested (and translucent) surfaces
are now left out of the bake's occluders; their sun shadows come from the
alpha-tested shadow meshes the engine draws at run time. The Source converter also
writes the real image (with alpha) as the shader's PNG for these textures, ready for
an alpha-aware bake.
