# Titanfall 2 lumps added in November 2026

remap now writes every Titanfall 2 lump that retail maps fill, except triangle
collision bevel indices. Layouts were read from the six retail samples in
`.local/respawn/samples/tf2-*` (Coliseum, Colony, Glitch, Homestead, Live Fire
Stacks, Lobby). Compiled maps were checked with `validate_records.py`, the 14
compiler regressions, and in game on Jump Academy 2 (TF2) and Trainstation (HL2).
The in-game checks covered loading, spawns, displacement collision and rendering.

| Lump | Status |
| --- | --- |
| 0x1D PHYSICS_COLLIDE | The 16-byte terminator (`-1, -1, 0, 0`) every retail map has |
| 0x2A CUBEMAPS, 0x28 PAKFILE | Generated; see below |
| 0x66 STATIC_PROP_LIGHTPROBE_INDICES | One probe per static prop |
| 0x06, 0x07 LIGHTPROBE_BSP_NODES / REF_IDS | Axis-aligned probe lookup BSP |
| 0x64 CSM_OBJ_REFERENCES | Light-space tree of static props |
| 0x7D SHADOW_MESH_ALPHA_VERTICES | `surfaceparm alphashadow` casters |
| 0x59, 0x5A CM_PRIMITIVES / BOUNDS | Grouped collision primitives |
| 0x44 TRICOLL_NODES | Noded triangle collision for patches |
| 0x61 TRICOLL_BEVEL_INDICES | **Written empty**; see open questions |

LEAF_WATER_DATA, WORLD_LIGHT_PARENT_INFOS, PHYSICS_LEVEL, PHYSICS_TRIANGLES and
VERTEX_RESERVED_5-7 are empty in every surveyed map and stay empty, with the
retail lump versions.

## Cubemaps

- **CUBEMAPS:** 16 bytes per cubemap: int32 origin, then a zero. `env_cubemap`
  entities are compiled in and removed from the entity files, as retail has none.
  Without any, remap places one 64 units above the first `menu_` anchor and one 64
  units above the average human spawn.
- **Meshes:** byte 11 of each mesh is its cubemap. Lit meshes (flags `0x200`,
  `0x000`, `0x600`) take the nearest gameplay cubemap; unlit (`0x400`) and sky
  meshes take -1. Nearest-centre matches retail on 30-100% of meshes, so retail
  probably also tests visibility. Material sorts always store cubemap 0.
- **Texture:** `materials/maps/<map>/cubemaps.hdr.vtf` in a stored ZIP whose
  comment is `XZP1 0` padded to 32 bytes; offsets are relative to the lump. The
  VTF is version 7.5, 256x256 faces, flags `0x420C`, format 66 (BC6H unsigned),
  9 mips, one frame per cubemap, reflectivity 0.2, bump scale 1. Data is mips
  smallest first, then frames, then the six faces. Three resources: `0` (image
  offset), `CMA` and `CRC`.
- **Faces:** the standard D3D cube order and orientation (+X, -X, +Y, -Y, +Z, -Z),
  sampled with Source world vectors directly. Face seams of decoded retail
  cubemaps join under this mapping (error 0.008 against 0.14 mirrored).
- **Contents:** each face is ray traced at 64x64 against the bake's occluding
  brushes and upsampled. Hits take the bake's radiance grid (albedo times direct
  light) plus 15% of the sky colour; misses take the first light_environment's
  ambient, plus the sun disc. `respawn/bc6h.h` encodes mode-11 BC6H blocks; a
  GPU round trip through D3D11's BC6H decoder confirmed the bit layout.
- **CMA:** one float per cubemap, inline (`CMA\x02`) for a single cubemap. Its
  meaning is unresolved: it does not track the cubemap's mean, max or median, or
  the nearest probe's ambient. Retail menu cubemaps store about 5.0, so remap
  writes 5.0 for cubemaps within 2048 units of a menu anchor and 1.0 elsewhere.
  `CRC` is written as 0; it matches no CRC32 of the file.
- **Path fix:** builds before 4 November 2026 named the texture
  `materials/maps//cubemaps.hdr.vtf`: remap's `mapName` is empty when no map
  shader file exists. The engine could not find it, so those cubemaps were
  never used. The level name now comes from the compiled map's path.

## Light probes

- **Static props:** the probe lump starts with one probe per static prop, at its
  lighting origin (or 32 units above its origin), then the environment's own
  probes. The parent record's range covers only the latter (Glitch:
  `firstProbe 16183` = prop count), but tree references are absolute and include
  the prop probes. 0x66 is one uint32 per prop, a permutation of `0..n-1`.
- **Probe BSP (0x06):** 24-byte nodes, plane normal, distance, then two children.
  Traversal takes the second child when `n.p - d >= 0`, otherwise the first; every
  sampled retail reference lands in its own leaf this way. A child with bit 31 set
  is a leaf: `0x80000000 | count << 25 | index`. Count 0 means one
  LIGHTPROBE_REFERENCES index; otherwise `count` (2-12) entries of 0x07 starting at
  `index`, each a reference index. Retail splits along world planes; remap uses
  axis-aligned median splits with leaves of at most 8 references.

## Cascaded shadow objects

The CSM tree (0x63) uses the cell AABB node layout. Its references (0x64) are
object ids, the same namespace as OBJ_REFERENCES: meshes, then static props
starting at the first sky mesh rounded up to 64. Retail trees hold about one
object in fifteen, so remap includes static props only; world geometry casts
through the shadow meshes. Node bounds are in light space. Fitting retail
object centres to their leaves gives an exact rotation: z = -sun,
x = normalize(sun.y, -sun.x, 0), y = z x x.

## Alpha shadows

Alpha shadow meshes have `opaque` 0 and a material sort, and index 20-byte
vertices (position, texture UV) in 0x7D. Their indices follow the opaque meshes'
in SHADOW_MESH_INDICES. remap writes one per material sort for surfaces whose
shader has `surfaceparm alphashadow`.

## Collision

- **Primitive groups:** a geo set with more than one primitive stores
  `first << 8 | contents`; every primitive in the set shares that contents.
  Primitive bounds parallel the primitives. remap groups a grid's primitives
  once, by contents and home cell, at most eight per group, and gives each cell
  every group it overlaps. Jump Academy 2 went from 55,845 geo sets to 45,709.
- **Triangle collision:** each patch becomes headers of up to 300 triangles. Every
  triangle has its own three vertices, so the 10-bit base and 7-bit deltas stay in
  range. Headers over three triangles carry `4 * ((n + 3) / 6)` nodes, each the
  header's packed bounds. Triangle bits 28-29 hold the lowest-Z vertex, and bit 30
  which of the other two is highest. This follows apex-to-titanfall-2's
  `native_triangle_collision.py`, which verified the flags on all 662,080
  Homestead triangles. Jump Academy 2 went from 19,104 headers to 1,194, and all
  13 sampled displacement floors collided at their surface height in game. TF1
  uses the same layouts and now gets patch collision too.

## Open questions

- **Bevel indices (0x61):** per triangle, a range of 11-bit ids starting at its
  bevel start. Ids are below the header's triangle count. They are mostly (91%)
  among the triangles sharing a vertex, but are neither the edge neighbours nor
  the vertex neighbours exactly, and some exceed the vertex count. remap writes no
  bevels, as retail does for headers without them; collision works without them.
- **CMA:** see above.
- **Cubemap choice:** retail mesh assignment is not purely nearest.
