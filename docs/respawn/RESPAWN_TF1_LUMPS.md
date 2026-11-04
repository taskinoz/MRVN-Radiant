# Titanfall 1 lumps and testing in Titanfall Online

remap's `-game titanfallonline` writes Titanfall 1 v29 BSPs. Titanfall Online
(TFORevive) loads TF1 maps directly, so it is the test bed. Layouts below were
checked against retail Angel City (`.local/respawn/samples/tf-angel-city`) and
TFO's own `mp_lobby_02`. Compiled maps were tested in game with
`tools/respawn/tfo_harness.py`.

## Testing in Titanfall Online

```powershell
python tools/respawn/tfo_harness.py --game "D:/Games/Titanfall Online" `
    --maps BUILD_DIR --map mp_name --checks checks.json --output REPORT_DIR
```

`checks.json` lists traces (`[x, y, z, ex, ey, ez]`) and views
(`[x, y, z, pitch, yaw]`). The harness:
- installs the map as a temporary mod and hooks TFORevive's `_mapspawn.nut`;
- launches `TFO.exe --authToken mrvn-local-noauth -noauth`;
- logs each trace's fraction and end height to `tforevive.log`;
- captures the game window at each view;
- removes the mod and restores `enabledmods.json`.

Things learned getting it to run:
- **Offline spawning:** offline sessions have no player data, so TFORevive's
  loadout script passes a null pilot settings file. The hook falls back to the
  stock `pilot_male_fastest`.
- **Dev mode:** `-dev` crashes at startup in the NVIDIA driver, so it is not used.
- **Flaky starts:** some ordinary launches also crash or exit before loading; the
  harness retries them.
- **Screenshots:** the engine's `screenshot` command writes nothing, and
  `PrintWindow` returns a blank image. The harness reads the screen instead, so
  the game window must be visible; it brings the window to the front first.
  Windows Firewall prompts for `TFO.exe` cover the window until answered.

## Materials

TF1 uses VMT/VTF materials, not RPaks. Texture names are written as
`WORLD\METAL\...`; case does not matter.
- **Vertex type:** the engine shows its magenta error material when a surface's
  vertex type does not suit its shader. TF1 world materials are almost all
  bump-lit (Angel City: 49 MB of lit-bump vertices, 396 bytes lit-flat). Declare
  them `$shadertype LitBumpGeneric` in a `.shader` script. Without one, remap
  writes lit-flat vertices.
- **Sky:** declare `tools/toolsskybox` with `$compileflag sky`,
  `$surfaceflag sky` and `$surfaceflag sky2d` to get sky portals.

## Lighting

TF1 maps with light entities run the Titanfall 2 bake (see
[RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md)). The writer converts what differs:

| Lump | TF1 v29 |
| --- | --- |
| WORLD_LIGHTS (v1) | The TF2 v3 record without its last 12 bytes (100 bytes) |
| LIGHTMAP_HEADERS, LIGHTMAP_DATA_SKY | As TF2: 8 bytes per texel, SKY A then B |
| LIGHTMAP_DATA_REAL_TIME_LIGHTS | **4 bytes per texel**, no RTL pages; written as 255 (unshadowed) |
| LIGHTPROBES, LIGHTPROBE_TREE | As TF2 |
| LIGHTPROBE_REFERENCES | 16 bytes: position and probe index, no trailing word |
| STATIC_PROP_LIGHTPROBE_INDICES | One probe per static prop, as TF2 |
| SHADOW_MESH_*, CSM_AABB_NODES, CSM_OBJ_REFERENCES | As TF2; there is no SHADOW_ENVIRONMENTS lump |

TF1 has no LIGHTPROBE_PARENT_INFOS, SHADOW_ENVIRONMENTS or RTL page lumps. Static
prop object ids follow straight after the world meshes, not TF2's 64-aligned base.

The RTL texel's meaning is unresolved. Its bytes are mostly 255: 81% of sampled
Angel City texels are entirely 255, and the rest look like shadow-mask values.
Comparing used bytes with nearby realtime lights did not identify which lights
the slots belong to. Writing 255 keeps realtime lights unshadowed by the bake.

## Vertices and material sorts

- **Tangents:** TF1 bump-lit and tangent-space vertices store two normal indices,
  tangent then bitangent (cross(normal, tangent), flipped to follow +dP/dv), with
  no sign bit. In Angel City and the TFO lobby the tangent and bitangent are both
  orthogonal to the normal and to each other. TF2 instead stores the tangent with
  a sign bit and a zero second word. With TF2-style tangents, bump-lit TF1 meshes
  crashed TFO at `engine.dll+0x18c77a` while loading the world.
- **Material sort cubemaps:** sorts of envmapped materials store their cubemap
  index; others store -1 (Angel City: 533 and 301). Meshes always store 0.

## Cubemaps

TF1 uses Source 1 style cubemaps. Angel City's pakfile holds:
- **Per cubemap:** `materials/maps/<map>/c<x>_<y>_<z>.vtf` (32x32 DXT5) and
  `.hdr.vtf` (64x64, Valve's compressed HDR: RGBA8888 with
  `colour = rgb * a * 16`).
- **Defaults:** `cubemapdefault.vtf` and `.hdr.vtf`; the HDR default is
  RGBA16161616F.
- **Patch VMTs:** one per envmapped material, at
  `materials/maps/<map>/<material>_<x>_<y>_<z>.vmt`, containing
  `"patch" { "include" "materials/<original>.vmt" "replace" { "$envmap" "maps/<map>/c<x>_<y>_<z>" } }`.
  Angel City has 265.

Texture names in the BSP stay unpatched. The engine picks the patch from the
material sort's cubemap.

remap writes the same set:
- **Textures:** 64x64 HDR cubemaps as RGBA16161616F and 32x32 LDR copies as
  RGBA8888. Faces are ray traced from the bake, exactly as TF2's are; the D3D face
  layout is the same, and Angel City's faces join seamlessly under it (seam error
  0.007 against 0.063 mirrored).
- **Default:** `cubemapdefault` is a copy of the first gameplay cubemap.
- **Material lookup:** remap reads each material's VMT through its filesystem. A
  material gets a cubemap only if it has a `$envmap` or `$envmap2` value; patches
  replace both. Point remap at TF1 materials with an extra base path, for
  example TFORevive's imported content:
  `-fs_basepath "<TFO>/Mods/Titanfall1.Content.Client" -fs_game mod`.
  Materials whose VMT is not found get no cubemap.

In game, a test build whose cubemap was replaced with pure red turned the wet
concrete floor and the weapon view model red. So TFO loads and uses the
cubemaps and patch VMTs. Run `tfo_harness.py` with
`--enable Titanfall1.Content.Client --enable Titanfall1.Content.Shared` when a map
uses those materials.

## Portals

TF1 shares TF2's cell and portal layouts and generator (see
[RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md)). The generator also
writes the cell AABB tree, which the TF1 path previously wrote a second time.

Two fixes came out of TF1 testing; both also apply to TF2:
- **Null shaders:** `_viewportals` crashed remap on any real map, because
  structural brush classification read sides with no shader.
- **Vertex-edge lists:** these now hold only edges ending at the vertex. Retail
  has at most five per vertex (Angel City, Colony, Glitch, Homestead).
  T-junctions stay in the intersection tables.

A sky-portal E1M1 build loads and renders in TFO. A full `_viewportals` build of
E1M1 (5,728 cells, 14,864 portals) loads, then crashes the TFO client
(`client.dll+0x5ea574`). It stays experimental.

## Still missing

- **PHYSICS_COLLIDE:** retail holds VPhysics world collision (8.4 MB in Angel
  City). remap writes a minimal world model; player and trace collision use the
  CM grid and work without it.
- **PHYSICS_TRIANGLES (1.4 MB in Angel City):** not identified.
- **TRICOLL_BEVEL_INDICES:** as TF2.
- **LEAF_WATER_DATA:** one 12-byte record per water volume (surface Z, minimum Z,
  surface texture). Written empty, which is correct for maps without water.
