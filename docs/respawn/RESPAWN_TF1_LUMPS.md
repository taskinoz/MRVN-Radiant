# Titanfall 1 lumps and testing in Titanfall Online

remap's `-game titanfallonline` writes Titanfall 1 v29 BSPs. Titanfall Online
(TFORevive) loads TF1 maps directly, so it is the test bed. Layouts below were
checked against retail Angel City (`.local/respawn/samples/tf-angel-city`) and
TFO's own `mp_lobby_02`. Compiled maps were tested in game with
`tools/respawn/tfo_harness.py`.

TFORevive can also mount retail Titanfall 1 maps. For example, the installed
`Titanfall1.Content.Shared` mod includes Colony (`mp_colony.bsp` and its
external lump files), providing a useful retail reference for compiler output.
Colony loaded and completed an empty harness run with both Titanfall1 content
mods enabled; that run did not check collision or visual appearance.

## Testing in Titanfall Online

```powershell
python tools/respawn/tfo_harness.py --game "D:/Games/Titanfall Online" `
    --maps BUILD_DIR --map mp_name --checks checks.json --output REPORT_DIR
```

`checks.json` lists traces (`[x, y, z, ex, ey, ez]`), views
(`[x, y, z, pitch, yaw]`) and drops (`[x, y, z]`). The harness:
- installs the map as a temporary mod and hooks TFORevive's `_mapspawn.nut`;
- launches `TFO.exe --authToken mrvn-local-noauth -noauth`;
- logs each trace's fraction and end height to `tforevive.log`;
- spawns a physics object at each drop and logs its sampled height (`DROP i z=...`);
- captures the game window at each view;
- removes the mod and restores `enabledmods.json`.

Optional `drop_models` selects a model for every entry in `drops`, for example
`"drop_models": ["models/containers/barrel.mdl"]`. It must have the same length
as `drops`; each selected model is precached during level initialization and
uses its own physics and appearance. Without this option, the existing probe
uses rocket physics with grenade appearance. `drop_wait` is a positive number
of seconds (default 4) before the height sample. For simultaneous drops it is
one shared wait; with `drop_sequential: true` it applies to each object before
that object is destroyed. A sampled height alone does not establish that a
body has settled or that water provides buoyancy; compare matching dry, wet,
and native-reference controls.

Things learned getting it to run:
- **Offline spawning:** offline sessions have no player data, so TFORevive's
  loadout script passes a null pilot settings file. The hook falls back to the
  stock `pilot_male_fastest`.
- **Dev mode:** `-dev` crashes at startup in the NVIDIA driver, so it is not used.
- **Flaky starts:** some ordinary launches also crash or exit before loading; the
  harness retries them. On a captured crash it closes the launch's
  `crashpad_handler.exe` and `messagebox-win.exe` error dialog, including a dialog
  launched by the tracked handler. Ownership and install paths are checked;
  handlers from other installs are left alone.
- **Screenshots:** the engine's `screenshot` command writes nothing, and
  `PrintWindow` returns a blank image. The harness reads the screen instead, so
  the game window must be visible; it brings the window to the front first.
  Windows Firewall prompts for `TFO.exe` cover the window until answered.

## Testing in R1Delta (Titanfall 1)

`tools/respawn/r1_harness.py` tests maps in R1Delta unattended, with the TFO
harness's checks schema, event lines and report, so both TF1 runtimes compare
line for line:

    python tools/respawn/r1_harness.py --maps BUILD_DIR --map mp_name         --checks checks.json --output REPORT_DIR

Omit `--maps` for a retail map. The game and R1Delta paths default to R1Delta's
registry `InstallPath` and its newest `%LOCALAPPDATA%/R1Delta/app-*`.

- **Control:** R1Delta ships a JSON-RPC (MCP) server, registered only with
  `-usemcp` and started by `+mcp_start_http PORT` on 127.0.0.1. Its tools run
  server Squirrel synchronously and return printed output, run console commands,
  and report game state. The harness launches `app-*/Titanfall.exe` as R1Delta's
  own launcher does (`FROM_DELTA_LAUNCHER`, `ContentId`, R1Delta and game DLL
  directories on `PATH`, game directory as working directory, no `-game`), loads
  the map with `map`, waits for the local player, then runs traces and hulls in
  batches, spawns drops, samples or waits, and reads them back. The old launch
  passed `-game r1`; the old console-dump flow is gone. No R1Delta fork is needed;
  the source checked was tag v3.0.4 (`engine/mcp_server.cpp`).
- **Script calls:** R1Delta gives a script 2 s to reach the engine thread; the
  first call after a map load always misses that but still runs later. The
  harness retries on that timeout, so every script is idempotent; drop spawning
  is guarded by a run token.
- **Staging:** a compiled map becomes an owned addon in `r1/addons` with only its
  `.bsp`, `.bsp_lump` and `.ent` files, listed in `addonlist.txt`; cleanup
  removes exactly that addon and entry (R1Delta rewrites the list with tabs).
  Drop models are precached by an addon `scripts/vscripts/test/myscript.nut`,
  which `_mapspawn.nut` includes at level init when `developer` is above 0; the
  harness refuses to shadow an existing one. Runtime `PrecacheModel` has no
  effect, and per-map addon level scripts were not loaded.
- **Drops:** `models/containers/barrel.mdl` is the default: barrels spawn as
  physics props, while `crate.mdl` and `projectile_rocket.mdl` never do. On a
  compiled map pass `--model-files` (see below). Unspawned drops fail the run with the model named.
- **Results:** retail Angel City (16 traces, 16 barrels) passed with every barrel
  on its traced floor. On the compiled closed-solid bevel map, all 5,148 traces
  and hull sweeps matched TFO within 0.001 unit (5,130 exactly).
- **Coordinate limit:** R1Delta refuses maps past +/-16384 units ("Map coordinate
  extents are too large!!") where TFO loads them; remap now warns for TF1.

**Physics props on compiled maps (resolved 6 November 2026).** `prop_physics`
was removed on spawn on every compiled map. The map was not at fault; there were
two separate causes:

1. **Model content.** R1Delta runs TFO's `server.dll` and `vphysics.dll`
   (`r1delta/bin`, `bin_nexon`) on TF1's engine, and mounts `mp_common` plus the
   map's own VPK. TF1 keeps most model files in per-map VPKs: `barrel.mdl` is in
   Angel City's and 17 others but not `mp_common`, and `mp_common` holds only
   some models' `.mdl`/`.phy` without their render files. On a custom map those
   models load with empty keyvalues, so `CBaseProp::Spawn` finds no `prop_data`
   and deletes the prop ("uses model ..., which has no propdata which means it
   must be used on a prop_static. DELETED", `server.dll` RVA 0x1c3c54, printed
   only as a developer warning). A breakpoint on `UTIL_Remove` (0x25b7d0) found
   the caller; the model's keyvalues had no subkeys on the compiled map and a
   `prop_data` key on Angel City. Copying the model's loose files (here from
   TFO's `assets_dump`) into an addon fixes it: `--model-files DIR`. A
   distributed TF1 map must likewise ship the models it uses.
2. **Paused server.** On a map without a match intro, the pilot loadout menu
   runs `setpause nomsg`, so server time stops about 1.2 s after load and
   physics never steps (drops hung at their spawn height). The harness sends
   `unpause nomsg` once the player exists.

A third requirement surfaced on the way: R1Delta's gametype script puts each
connecting player at an `info_intermission`; with none, the connect callback
errors (`viewPoint` is null in `SetPlayerToDefaultViewPoint`) and the match
never starts. Retail maps place them in the BSP entity lump, as remap does;
remap now warns when a TF1 map has none. TFO tolerates their absence.

With all three, 16 barrels on the compiled `vstats` map (8 over a patch, i.e.
virtual-mesh collision, 8 over a brush) fell and came to rest at z 15.56..15.69,
lying on their sides. Small props spawned outside a script call are also made
client-side and removed on the server in TFO's code
(`sv_pushaway_clientside_size` 30, volume test at 0x1cfb7e), which is why
`crate.mdl` and other small models never spawn from the harness.

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


## CM brush bevel planes

CM_BRUSHES stores a non-discard plane count followed by a total non-axial plane
count. Inherited edge bevels now follow authored cuts and carry side-property
flag `0x4000`; generated plane fallbacks and parallel texture/property arrays
are emitted for both TF1 and TF2. Convex merging respects the total 8-bit plane
budget. Native crease contacts and independent box sweeps verify this restored
path; complete retail bevel-generation parity remains open. See the
[brush-bevel study](RESPAWN_TRICOLL_PORTALS.md#cm-brush-bevel-output-5-november-2026).

## VPhysics (PHYSICS_COLLIDE)

TF1 physics objects (grenades, gibs, ragdolls) collide with the world through
VPhysics, separately from the CM grid that players and traces use. Without it,
dropped grenades fell through every floor of a test build of E1M1 (resting near
z -4000). The layout is Source's IVP compact surface, read from retail Angel City.

- **Lump:** per model `{int modelIndex, dataSize, keydataSize, solidCount}`, then
  `solidCount` solids of `{int size; data}`, then the NUL-terminated keydata.
  The lump ends with `{-1, -1, 0, 0}`.
- **Solid:** a 28-byte header (`VPHY`, version 0x100, model type 0, surface size,
  drag 1,1,1, axis map size 0), then an `IVP_Compact_Surface` (48 bytes): mass
  centre, rotation inertia, upper radius, `max_deviation | byte_size << 8`
  (retail deviation 227), ledge tree root offset, and `IVPS` in the last word.
- **Ledges:** 16-byte header (point offset, client data 0,
  `is_compact << 2 | size / 16 << 8`, triangle count), 16-byte triangles
  (`index:12 | pierce:12 | material:7 | virtual:1`, then three edges of
  `start point:16 | opposite:15 | virtual:1`, where opposite is a signed count of
  4-byte edges to the reverse edge) and 16-byte points. Coordinates are IVP
  metres: `(x, -z, y) / 39.3701`. Triangles wind counter-clockwise seen from
  outside. Retail ledges share one point pool per surface; remap puts each
  ledge's points after its triangles, which IVP also accepts.
- **Ledge tree:** 28-byte nodes: right child offset (0 for a leaf), ledge
  offset (leaves only), centre, radius and three box sizes; the left child
  follows its parent. Retail centres and radii are the box centre and half
  diagonal of the subtree's points, and each box size is `250 * half extent /
  radius`, rounded up (all retail leaves match to within 1%).
- **Keydata:** the world has one `staticsolid { "index" "contents" }` per solid,
  then `virtualterrain {}`, `virtualtrimeshes {}`, any `vtric { "index"
  "contents" }` entries and a `materialtable`. See
  [virtual triangle meshes](#virtual-triangle-meshes-and-vtric-5-november-2026).
  Triangle material indices refer to that table. Brush entities have one
  `solid { "index" "mass" "surfaceprop" "volume" }`.

remap turns solid brushes into convex ledges, groups the world's ledges into
static solids by contents, and gives each brush entity one movable solid. It
also writes fluid solids for world water and slime brushes, and a leaf water
record for each group of brushes with the same surface height, contents and
surface material. The compiler regression checks distinct contents, materials
and nearby heights. Triangle material indices come from the shader's
`$surfaceprop`, or from its VMT, falling back to `default`. The world
material table uses indices 1..127 in the ledge's 7-bit material field. Reusing
an existing property remains valid when the table is full; adding a 128th
property now fails explicitly. Previously it silently used property 1, changing
the authored friction/sound assignment. Regression fixtures cover all 127
properties, a repeated property at capacity, and rejected overflow. VMT parsing accepts
quoted and unquoted keys and values, skips comments, and resolves patch includes
and their insert/replace surface properties. Include cycles, invalid paths and
missing included files fall back to `default` with a warning. This is a targeted
surface-property reader, not a complete KeyValues implementation; conditional
keys and engine-specific patch behavior remain unverified in TFO. remap writes
retail's `vtric` entries for clip-only triangle collision.

World patches no longer have VPhysics ledges: like retail, they collide through
the engine's TRICOLL virtual meshes (below). Brush-entity patches, and world
patches in a world without any brush solid, are still approximated with convex
triangular prisms 32 units deep behind the patch's native front face. Respawn triangle fronts face
opposite to the ordinary cross product of their vertex edges. The compiler now
uses that direction when extruding, then orients IVP faces outward. Previously it
extruded into the space in front of correctly facing patches. The regression
rejects that old output: for a flat upward-facing patch at z=0, collision must
span z=-32..0; the old mixed brush/patch model instead spanned z=-16..32.
Patches that fold across their average extrusion direction, other physics shapes
and speeds, curved patches and seams still need runtime coverage.

Patch-only brush entities get render models, triangle collision and VPhysics
solids; mixed brush/patch entities include both kinds of VPhysics geometry. The
cross-game regression checks entity/model links, model-cell triangle references,
height-order flags and closed outward-facing IVP ledges, including their bounds.
The original flat test patch faced downward, which explains its player-solid ray
misses in both world and entity form. Reversing only the world patch's collision
winding made both rays hit z=64; changing its height flags, model bounds or node
count did not resolve the wrong-facing fixture. A correctly facing patch-only
`func_brush`, recompiled with the extrusion fix, passed both player-solid rays
at exactly z=64 and all three isolated drops at z=65.2188..65.3125. A repeat
passed both rays and all ten isolated drops across five positions and two drop
heights (z=70 and z=100), resting at z=65.2188..65.3438. The matching brush
control had hit z=64.0313. This verifies entity triangle traces for this
flat fixture, not general player/weapon hull parity.

Earlier isolated drops used the downward-facing fixture and therefore do not
validate correctly facing patch extrusion. One subsequent trial also produced
inconsistent drops; broader native tests remain necessary. The probe creates a
rocket-model physics object and changes its visible model to a grenade, so it
does not test actual grenade physics. Surface-specific effects, buoyancy and
underwater behavior remain unverified. Water-cell assignment now measures the
union of authored convex brush volumes inside each cell's bounds, including
sloped cuts, gaps and overlap. Axis-only pools retain the fast box-union path.
The 50% coverage threshold and use of the cell bounds remain a classification
heuristic; this does not implement water-aligned visibility partitioning. A two-material
pool compiled to two fluid records and loaded in TFO; that smoke test does not
establish buoyancy or underwater rendering. Single-cell visibility did not
assign the test pool to a water cell.

The TFO harness accepts optional `expect.trace_z` and `expect.drop_z` arrays of
`[check index, minimum Z, maximum Z]`. Missing results, removed objects, nonfinite
positions and out-of-range endpoints fail the run even if the script finishes.
These ranges reject the old wrong-facing patch ray results and pass the brush
control and the corrected patch entity.

In TFO, grenades dropped on five E1M1 floors came to rest 1.3 units above them
(floors at -80, 0, -192, -176 and -280). One dropped onto a ledge at 64 rolled
off and came to rest at 49. `compiler_regression.py` checks that every brush
becomes a closed ledge with outward triangles and twinned edges.

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

The original full `_viewportals` E1M1 build had 5,728 cells and 14,864 directed
portals, and crashed the TFO renderer at `client.dll+0x5ea574`. The native renderer
uses 1024-bit cell masks with two sentinel bits. Convex merging alone reduced the
map to 1,832 cells but still crashed during cell traversal. The generator then
clustered regions to the native budget of 1,022 cells; since 6 November 2026 its
cells are whole BSP subtrees instead (see the portal notes).

The resulting E1M1 map has 1,022 cells and 11,132 directed portals. TFO completed
all six harness traces and three camera views without a crash. The three saved
screenshots show the requested rooms, floors, walls and doorway geometry. This
resolves that map's load/traversal crash. Culling itself was wrong until 6
November 2026: cells are now whole BSP subtrees, and E1M1's portal build renders
the same as the portal-free build in R1Delta and TFO (see
[RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md#in-game-culling-with-_viewportals-6-november-2026)).
The two-game regression includes a dense 1,156-pillar fixture split by a sealed
wall: both outputs fit the cell budget, connect points within one side, and keep
the two sides disconnected.

Portal validation now runs on TF1 as well as TF2, including the standalone
`portals.py` CLI. All 11 mounted TF1 maps and six TF2 samples pass it. TF1 `mp_o2`
has an empty global access root with float32 accumulation sentinels (minimum
`FLT_MAX`, maximum `-FLT_MAX`); that exact zero-count global form is accepted,
while nonempty or nonglobal inverted roots are rejected.

## Native fluid buoyancy controls (5 November 2026)

A local probe compares three BSPs whose only different lump is
`PHYSICS_COLLIDE` (29). The compiled variant uses remap's fluid solid; the
retail control substitutes Angel City's fluid solid 11 and its fluid keydata
(with the index adjusted); the third removes that fluid solid and keydata.
Collision cells, water contents, geometry, floor solids and external entities
remain identical. The retail geometry stays in local research files.

Each variant drops three stock physics models at matching dry and submerged
positions, separated to avoid prop contact. The water surface is Z=26 and the
floors are Z=-336. After eight seconds, successful native runs measured:

| Model | Compiled dry / wet Z | Retail control dry / wet Z | No fluid dry / wet Z |
| --- | --- | --- | --- |
| `models/containers/crate.mdl` | -326.969 / 19.2813 | -326.969 / 19.2813 | -326.969 / -326.625 |
| `models/containers/crate_orange_plastic.mdl` | -335.531 / -330.594 | -335.531 / -330.594 | -335.531 / -335.531 |
| `models/containers/barrel.mdl` | -320.281 / -320.563 | -320.281 / -320.531 | -320.281 / -320.281 |

The crate rises from its submerged spawn at Z=-128 with both emitted and
retail fluids, but falls to the floor when the VPhysics fluid is removed.
This directly demonstrates buoyancy from the emitted fluid in this scene.
The barrel and orange crate do not float in the retail control either; they
cannot serve as assumed floating-body expectations. Position and velocity
logging in the compiled, retail and no-fluid repeats showed all six bodies
stationary at sampling. All three selected runs pass two floor ray and six
prop height expectations. The maximum compiled/retail height difference is
0.032 units; removing the fluid lowers the submerged crate by 345.9063 units.
This does not establish arbitrary-volume buoyancy, currents, slime behavior,
underwater rendering or complete fluid parity.

The first model probe failed because custom drop models had not been
precached. The harness now precaches them during level initialization. One
retail run completed with floor failures (including dry objects), then the
repeat passed and matched the compiled result. That failed run is retained,
and its cause is unresolved. Startup-only stack-overflow failures are recorded
separately and are not counted as completed physics tests. The harness closes
its owned crash handlers on those failures.

Local evidence is under `.local/respawn/buoyancy-control/`: `source.json`,
`lump-identity.json`, `comparison.json`, the three `validation.json` files,
and native `compiled-position-repeat2-run/report.json`,
`retail-position-run/report.json`, and `none-position-repeat2-run/report.json`.
The failed retail run remains in
`retail-precache-run/report.json`.

## Convex water coverage and patch normals (5 November 2026)

The coverage helper subtracts each bounded convex fluid brush from a set of
disjoint dry fragments, clipping polygon faces and closing the cut caps. This
measures union volume without double-counting overlapping pools. Calculations
use double precision in coordinates relative to the cell. Authored non-axial
planes are retained until water-cell assignment; supplemental collision planes
do not define the water volume. Bounds-only coverage remains a cheap upper
bound and an exact fast path for axis-only groups.

Analytic C++ cases cover triangular prisms, a tetrahedron, opposed ramps,
nested/duplicate volumes, mixed axial and sloped pools, partial cell clipping
and translated non-unit planes. Two compiler fixtures distinguish actual water
coverage from its enclosing box: one triangular pool's bounds cover over half
the chamber while its true volume covers about a quarter, so the chamber stays
dry; a larger triangle still assigns water. The native TFO map loaded and
completed both floor rays and both rounded hull checks at z=0.03125 without
errors. Identical props dropped in the dry and flooded chambers both returned
positions. This is a load/collision smoke test, not proof of buoyancy or
underwater rendering.

The native probe also exposed harness self-collision: sweeps previously used a
null ignore entity and could hit the test player. Geometry rays and hulls now
ignore that player. The initial player hit failed the expected floor anchor;
the corrected rerun passed all four anchors. Enabled-mod configuration is now
backed up and restored as exact bytes, including BOM and newline style, even
when launching fails.

Output comparison exposed a separate render bug: map patch control points have
positions/UVs, but their normals were copied from uninitialized storage. The
Respawn mesh path now calls the existing Q3 mesh-normal calculation. Collapsed
control points borrow the closest usable grid normal, with a live face normal
as fallback when no grid normal is usable. Render validation rejects nonfinite
or non-unit normal vectors; retail's unreferenced zero-vector sentinel remains
allowed. Patch regressions check upward orientation, the analytic normal at a
symmetric dome center, and a collapsed grid with one live triangle. Both TF1
and TF2 patch/patch-entity/collapsed fixtures repeat twice with byte-identical
lump payloads (12 repeated builds). The saved failing patch output is rejected
by the new normal validator.

The Release build, 53 compiler fixtures, C++ encoding/geometry tests and 192
Python tests pass. All 53 matched pre-normal-fix BSPs retain identical collision
lump payloads. These results do not close the remaining physics, lighting,
streaming and visibility parity gaps below.

## Virtual triangle meshes and vtric (5 November 2026)

TFO gives every TRICOLL header VPhysics collision without any keydata:

- `engine.dll` RVA 0x245f60 parses PHYSICS_TRIANGLES as `u16 count`,
  `u16 size[count]`, then concatenated blobs; sizes 0 and 0xfffe..0xffff are
  null. Its count equals the TRICOLL header count (Angel City: 5,806 headers,
  1,403,258 blob bytes). RVA 0x246090 then calls `IPhysicsCollision` vtable
  slot 0x1a0 (Source's `CreateVirtualMesh`) once per TRICOLL header
  (`size / 44`, computed at 0x242b20), with the header index as user data and
  `buildOuterHull = (lump size <= 0)`. An empty lump, as remap writes, makes
  the engine build the hulls itself.
- `server_local.dll` RVA 0x7bc000 makes one static physics object per virtual
  mesh index 0..8191. Each `vtric { "index" "contents" }` entry (collected by
  the keydata parser at 0x7bc600) only sets the contents of the object with that
  index; `virtualtrimeshes {}` enables the pass. The world physics object reads
  `staticsolid 0` (0x7bc2b0); a model with no solids crashed there with a null
  read, which is why an earlier "virtual-only" probe crashed.
- In Angel City, Colony, Lagoon and Fracture (15,524 headers, 2,590 `vtric`),
  a header has a `vtric` entry exactly when its collision-grid contents have a
  player, NPC or Titan clip bit and none of SOLID, WINDOW or GRATE. The entry's
  contents equal the grid contents. Solid (0x1), window (0x2), grate (0x8) and
  bullet-clip/LOS (0x480000) headers have none.

remap therefore writes no world patch prisms and emits `vtric` by that rule
(`physics-virtual-mesh` regression fixture). Native TFO evidence, crates dropped
from z=96 onto a flat 1024-unit world patch at z=0 over a catch floor at z=-512:

- Without prisms, four crates rested at z=0.44..0.47, including the patch
  centre vertex, where one earlier prism probe fell through. Traces and hulls hit
  z=0 and z=0.03125.
- With the old prisms on the same map (one run), crates rested at z=8.8..17.6
  and moved up to 326 units sideways, consistent with prisms and virtual mesh
  overlapping; the instability below means this needs repeating.
- A player-clip patch with its `vtric` entry let its crate fall through to the
  catch floor, while the same BSP without the entry held it at z=64.47.

Repeated runs exposed an unresolved VPhysics instability that is **not**
specific to virtual meshes. In 16-crate maps, whole runs failed: 6 of 12 runs
with 8 crates on a patch and 8 on a brush slab, 3 of 4 when dropped from z=400,
and 3 of 4 on a brush-only map with no patches at all. Within a run, trajectories
are bit-identical to passing runs until first contact (x/y jitter shows the
contact), after which the crate falls at full gravitational acceleration through
the surface; it then bounces irregularly around z=-480..-499 on the catch floor
instead of resting at -511.6. Failures did not correlate with startup retries,
the Playing game-state transition (a 2-second wait after it did not help) or
contact time after spawn. Earlier retail-fluid floor failures may be the same
effect. A retail control dropped 16 crates 64 units above separate Angel City
spawn points in four runs: 62 of 64 settled on the traced floor, but in one run
two fell straight through floors at z=128 and 144 (to -16 and -40). TFO itself
therefore loses props through retail floors, consistent with grenades reported
falling through floors in normal play. Compiled maps failed more often (often all
16 crates of a run), so a remap contribution is not ruled out. Until resolved,
native drop results need repeats, and one failing run does not show a
collision defect. The harness's `drop_samples` option logs drop positions every
0.2 seconds.

## Still missing

- **PHYSICS_TRIANGLES (1.4 MB in Angel City):** precomputed virtual-mesh hulls,
  one per TRICOLL header. remap leaves it empty, so the engine builds them at
  load; the blob layout is not decoded. Maps with more than 8,192 world TRICOLL
  headers would lose VPhysics on the rest.
- **Patch collision coverage:** correctly facing flat-entity rays and isolated
  VPhysics drops pass in TFO. The new six-surface sweep fixture covers 156
  front-facing world ray/hull cases. Exact convex merging fixes the reproduced
  compatible-brush shared-edge misses, and all 156 merged-brush results agree
  across TF1/TF2. Four dome triangle hull comparisons remain unresolved;
  backfaces, transformed patch entities and other orientations still need coverage.
  See [the sweep study](RESPAWN_TRICOLL_PORTALS.md#swept-patch-comparison-4-5-november-2026).
- **VPhysics validation:** isolated flat-patch drops passed, but curved surfaces,
  other physics shapes and speeds, broader buoyancy cases, underwater cells and
  surface-specific effects need in-game tests. The controlled crate comparison
  above verifies emitted-fluid buoyancy for one scene.
- **TRICOLL_BEVEL_INDICES:** written with the functional rule, as TF2. It is a
  superset of Angel City's retail lists; exact retail selection remains open.
- **LEAF_WATER_DATA:** records are generated for water, but the cell assignment
  heuristic remains unverified, particularly for single-cell maps.
