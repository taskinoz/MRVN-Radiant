# Titanfall 2 scene recovery and rebuilding

25 October 2026. `tools/respawn/decompile_bsp.py` provides a bounded v37
exporter and two deliberately different build paths. This does not recover the
original editor CSG or establish full BSP-format compatibility.

## Commands

Run from the repository root with Python 3.11 or newer. Each destination must be
new; source BSPs and game installations are never overwritten by these commands.

```powershell
python tools/respawn/decompile_bsp.py export C:/maps/mp_coliseum.bsp .local/recovered/coliseum
python tools/respawn/decompile_bsp.py rebuild .local/recovered/coliseum .local/rebuilt/preserved
python tools/respawn/decompile_bsp.py compile .local/recovered/coliseum .local/rebuilt/compiled --remap install/Release/remap.exe
```

Keep adjacent default/client `.bsp_lump` files and entity partitions with the
input. Export resolves default overrides for scene recovery and retains both
variants as opaque files. Big-endian and non-v37 inputs are rejected.

`rebuild` verifies the manifest hashes and copies the preserved BSP/sidecars.
With no edits the result is byte-identical. Edit `entities.json` to change entity
keyvalues in this path; ordered key/value pairs retain duplicate outputs. This
path does not rebake lighting or compile geometry. Edited client-only entity
override parity has not been established.

`compile` runs the native compiler on the recovered scene and rebakes lighting.
By default it requires render triangle positions/materials/texture UVs, active
collision triangle geometry/contents, brush bounds/contents and known static
prop fields to match the source. It writes separate comparison reports and
`validation.json`. For intentional geometry, collision or prop edits, pass
`--allow-edits` to retain reports without requiring equality. Structural
validation still applies. These comparisons do not certify engine compatibility.

## Editable project

| File | Role |
| --- | --- |
| `<level>.map` | Radiant collision brushes/triangle patches, entities and static props; authoritative for native compilation |
| `scene.json` | Recovered render vertices and triangle indices, grouped by model/material chart; authoritative render source for native compilation |
| `entities.json` | Partitioned entity keyvalues; authoritative only for preservation rebuilds |
| `props.json` | Decoded static prop reference data used for comparison; edit MAP prop entities for compilation |
| `assets/models/recovered/*.rsm` | Generated RSM1 binary interchange read by remap; regenerated from `scene.json` at compile time |
| `assets/models/recovered/*.obj` | Radiant preview meshes with importer coordinate conversion; excluded from runtime entities |
| `model_*.obj` | Diagnostic engine-coordinate meshes; no OBJ-edit import command is implemented |
| `assets/shaders/recovered.shader` | Material names and basic shader kinds; no original texture images or RPAK materials |
| `preserved/`, `lumps/`, `project.json` | Original bytes, resolved payloads, hashes and provenance; keep unchanged |

Vertex arrays in `scene.json` are `[x,y,z,nx,ny,nz,u,v,r,g,b,a,luxelU,luxelV]`.
RSM1 retains normals, UVs and colours; lighting is regenerated. Collision is
separate from rendering: brushes are not used to recreate the detailed render
surface. Per-primitive `_remap_contents_N` retains masks, including non-solid
trigger/clip contents. Do not renumber MAP primitives without updating these keys.
Recovered opaque world triangles participate in baked shadow tracing through
thin closed triangle prisms. Preview geometry does not become a second render
or collision model.

## Three-map evidence

Local samples: BobTheBob's repaired Titanfall Online `mp_box` port, retail
Titanfall 2 `mp_coliseum`, and retail `mp_lobby` extracted from `mp_common`.
Default sidecars and entity partitions were included.

| Map | Render triangles | Collision triangles | Active brushes | Static props |
| --- | ---: | ---: | ---: | ---: |
| mp_box | 1,282 | 198 | 130 | 77 |
| mp_coliseum | 10,992 | 16,632 | 2 | 3 |
| mp_lobby | 22 | 96 | 2 | 0 |

All three pass byte-identical preservation rebuilds and strict native scene
comparison. Coliseum has ten unreferenced source brush records and lobby one;
the preservation path retains these, while the scene path rebuilds active
collision only. Python coverage includes malformed entity syntax, duplicate
outputs, partition preservation, path traversal, changed raw bytes, ownership,
contents masks and RSM attributes. The native compiler regression includes an
original decompile/recompile fixture without game assets.

Runtime tests use Northstar 1.31.13 and the isolated `R2MapHarness` profile.
A diagnostic entity marker confirms the rebuilt map rather than the stock map
was loaded. Rebuilt Coliseum reached live client/server play with a healthy
spawned pilot and retained pilot/titan spawn entities. Rebuilt lobby reached
client/server initialization; it has no gameplay spawn entities and is not a
playable TDM level. Initial rebuilt mp_box crashed at `engine.dll + 0x17fdc0`.
Disabling static prop rendering avoided the crash; restoring the original sprp
blob did not. Correcting the visibility object namespace then allowed normal
prop rendering and a live healthy client for over a minute, with successful
team 2 and team 3 start selection. This is a smoke test, not full gameplay or
visual certification.

### Static prop visibility namespace

TF2 object references are not `world.meshCount + propIndex`. Their prop base is
`(LEVEL_INFO.firstSkyMeshIndex + 63) & ~63`. Non-sky world objects occupy the
preceding block; sky and submodel meshes are not inserted as ordinary objects.
The native compiler now uses this base, excludes sky objects, bounds-checks the
16-bit references and provides finite access bounds for sky-only scenes.
Recovered submodel bounds now use only that model's mesh range.

| Retail map | First sky mesh | Prop base inferred from references |
| --- | ---: | ---: |
| Coliseum | 43 | 64 |
| Colony | 4,156 | 4,160 |
| Glitch | 2,903 | 2,944 |
| Homestead | 2,877 | 2,880 |
| Live Fire Stacks | 1,763 | 1,792 |

Independent native evidence: engine SHA-256
`58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487`,
RVA `0xcb2c4` reads the level-info value at offset 8; `0xcb2db` adds 63 and
`0xcb2e6` masks with `0xffffffc0`. The result is stored at runtime offset
`0x18` / `0xcc`. The following instructions also align the prop block's end.
The initial mp_box compiler output used prop refs 65..141 instead of 64..140.
Selected-record validation now rejects the out-of-range final reference before
runtime. Five retail maps pass the updated validator. This original finding and
the runtime isolation do not identify every internal engine structure.

## Remaining limits

Original portal topology, lightmap atlas layout, opaque unknown records,
tricoll acceleration/bevel semantics and every brush plane/material field are
not reconstructed identically by scene compilation. Default visibility uses
the compiler's single visible cell; preservation retains original portal data.
Collision triangle equality does not prove swept-hull edge behaviour. Native
static prop export retains known placement fields, not every unknown header
value. Game mode scripts, model/material assets, VPK/RPAK dependencies, navigation
and streamed terrain are not decompiled or packaged by this tool. Existing map
assets must remain mounted for runtime tests. Visual lighting/material quality,
grapple impacts and grenade/particle stability need further in-game testing.

## Attribution

The recovery/parser/RSM1 code and tests are original MRVN-Radiant work under
GPL-2.0-or-later. Native compilation retains inherited NetRadiant/MRVN-Radiant
notices and uses its existing Assimp preview-import path. Record schemas were
cross-checked against snake-biscuits/bsp_tool commit
`655627ea8704353ac14bd753df8ca05c15838eda` (GPL-3.0; layout credits include
BobTheBob and DTZxPorter); no upstream parser implementation was copied.
pg9182/tf2vpk commit `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff` (MIT) extracted
local retail samples. Respawn/Nexon retain map/asset credit; BobTheBob retains
the manual mp_box port credit. Game assets and generated projects remain local
and ignored. See [RESPAWN_SOURCES.md](RESPAWN_SOURCES.md).
