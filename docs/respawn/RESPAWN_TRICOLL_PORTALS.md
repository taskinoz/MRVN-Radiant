# Titanfall 2 triangle collision and view portals

Research and implementation: 24 October 2026. This work targets little-endian
**BSP v37**. It does not establish Titanfall/Online or Apex compatibility.

## Implemented scope

The TF2 compiler emits collision for solid-content patch grids, including patch
brush models. Each sampled quad becomes a small triangle-collision header with
at most two nondegenerate triangles. The positions and diagonal match the
existing render mesh exactly. This uses the engine's node-free small-mesh path;
it does not implement larger packed-node or bevel generation. It also does not
add Bezier tessellation: the existing render path uses the imported patch grid.
Non-content and sky patches do not generate this collision.

Set worldspawn **`_viewportals "1"`** to generate a brush-derived visibility BSP,
directed cell portals, sky apertures, edge incidence/intersection tables and
per-cell object-access trees. It reuses this project's inherited NetRadiant
structural BSP and portal builder. Respawn parsing bypasses Q3 brush-content
classification, so a local copy is classified using Respawn contents first.
Object AABBs touching a split are conservatively referenced on both sides.
Opaque leaf cells remain in the BSP with no outgoing regular portals.

This mode is **experimental and opt-in**. Default TF2 compilation keeps one
all-visible cell and derives sky polygons from authored sky faces, replacing
the legacy fixed quad. The shared legacy initializer runs before replacement
serialization, so it cannot overwrite the generated graph.

Limits are checked before narrowing indices/counts. Unrepresentable portal
vertices/edges, reference totals, incidence degree and access trees fail with an
error. Leaks, water portals, global environment-cell generation, runtime culling
parity and full texture-streaming behavior remain open. Brush portal planes
partition space; these are not render-to-texture or teleportation portals.

## Triangle collision records

| Lump | Layout | Interpretation |
| --- | --- | --- |
| 66 TRICOLL_TRIS (v2) | `uint32` | low 10 bits A; 7-bit B and C positive deltas; upper 8 bits flags |
| 68 TRICOLL_NODES (v1) | 16 bytes | packed acceleration data; reader preserves words, writer not implemented |
| 69 TRICOLL_HEADERS (v1) | `6H4i4f`, 44 bytes | flags, surface flags, texture, vertex/triangle/bevel counts; four offsets; origin and scale |
| 96 TRICOLL_BEVEL_STARTS | `uint16` per triangle | parallel to packed triangles |
| 97 TRICOLL_BEVEL_INDICES | packed `uint32` words | 11 bits per index; word count rounds up |

Collision primitive kind is **0x40**, with header index in bits 8..23 and the
contents-table index in bits 0..7. Triangle positions come directly from
`VERTICES[firstVert + A/B/C]`; origin and scale describe packed-node coordinates,
not a transform to apply to triangle positions. The original signed 5/9/9/9
bitfield has been corrected to unsigned 10/7/7/8.

The loader uses **zero nodes for 1..3 triangles**, otherwise
`4 * ((triangleCount + 3) // 6)` 16-byte nodes. Bevel words require
`(11 * bevelIndexCount + 31) // 32`. The three-triangle special case matters:
applying the general formula would incorrectly demand nodes from retail data.
Upper triangle-flag and bevel semantics remain only partly understood. The
current writer uses flags zero, no bevel indices and at most two triangles.
Swept hulls, triangle edges, backfaces and effects need native testing before
claiming complete collision support.

## Visibility records

| Lump | Layout | Meaning |
| --- | --- | --- |
| 106 | `iI` | cell BSP: plane or -1 leaf, first child pair or cell |
| 107 | `3Hh` | portal count/start, flags, water index |
| 108 | `4B2HI` | reversed, kind, polygon count, padding, reference start, destination, plane |
| 109 | `3f` | portal vertices (vertex zero reserved by writer) |
| 110 | `2H` | edge endpoints |
| 111 | `8h` | incident edges per vertex, -1 padding |
| 112 / 113 | `H` | polygon vertex / oriented-edge references |
| 114 / 115 | `8h` | parallel intersecting-edge / intersection-vertex blocks |
| 116 | `2I` | first intersection block and block count per edge |
| 119 | `3fBBH3fHH` | cell/object access nodes |
| 120 / 121 | `H` / `3fI3fI` | object references and parallel AABBs |

Child zero is the positive/front side, child one the negative/back side.
Regular portals have kind zero; sky kind one targets `len(CELLS)+1`. Retail also
has water kind two. Both directed records retain polygon winding toward the
stored plane normal; `isReversed` identifies the source side.

An edge reference is `edgeIndex * 2 + reversed`. Polygon references describe
the edge **arriving** at each vertex. Retail merges collinear edges, so polygon
vertices can lie inside an edge, rather than at an endpoint. The writer merges
overlapping collinear segments and includes these T-junctions in incidence and
intersection tables. It does not assume one intersection block per edge.

The first `len(CELLS)` access nodes are per-cell roots. Retail's final special
environment cells use flags 3 with infinite access-root bounds; validators
permit this specific pattern, while rejecting nonfinite ordinary bounds.

## Tools and verification

```text
python tools/respawn/tricoll.py path/to/map.bsp --obj collision.obj
python tools/respawn/portals.py path/to/map.bsp --point 0 0 64
python tools/respawn/validate_records.py path/to/map.bsp
python -m unittest discover -s tools/respawn -p "test_*.py"
python tools/respawn/compiler_regression.py --remap install/Release/remap.exe --work-dir NEW_DIRECTORY
python tools/respawn/build_collision_portal_test.py --remap install/Release/remap.exe --output ANOTHER_NEW_DIRECTORY
```

The read-only tools check bounded slices, packed vertex indices, triangle/node
and bevel-array ranges, parallel tables, cell BSP cycles, destinations and sky
sentinels, oriented edge indices, intersection pairs and object-access bounds.
OBJ export uses raw global positions. It never changes the input BSP.

The compiler regression includes original patch-only, two-room open-door,
sealed-divider and sky-ceiling fixtures. It compares render/collision triangles,
checks reciprocal regular portals, independently locates room points and checks
graph connectivity. These establish binary/topology behavior, not runtime
visibility correctness. There are 11 compiler fixtures and 91 Python tests.
MSVC Release remap builds successfully.

Retail checks on Coliseum: 184 headers, 16,632 triangles, 11,084 nodes,
41 cells and 409 portals. Glitch: 3,544 headers, 902,760 triangles, 601,580 nodes,
75 cells and 1,079 portals. Both pass the dedicated range/topology inspectors.
Local reports and generated fixtures stay under ignored `.local/respawn`.

The same inspectors also passed Colony02, Homestead and LF Stacks: across all
five samples, **1,821,039 triangles, 311 cells and 3,341 portals**. TF2-specific
tricoll checks are gated to v37; a TF1 packed-bevel difference is unresolved and
must not create false v29 validation failures.

### Native smoke test

An original two-room/doorway/patch mod was launched using Northstar 1.31.13 in
the separate `R2MapHarness` profile. The server completed these native traces:

| Test | Native result |
| --- | --- |
| Ray at (-96,-96), z192 to -8 | fraction 0.879832, end z16.0336 (authored triangle height 16) |
| Hull, mins (-8,-8,0), maxs (8,8,32), same sweep | fraction 0.876820, end z16.6359 |
| Ray through doorway, z96 | fraction 1 |
| Ray against divider, y96/z96 | fraction 0.468628 (wall at x=-8) |

This confirms map loading, triangle ray hits, a native hull hit, and open-door /
solid-wall behavior. **It does not establish hull clearance parity**: the hull
hit needs comparison with the exact swept-box expectation, and triangle flags /
bevel handling remain unresolved. Origin disconnected the local session after
initialization, preventing a visual culling/playthrough check. The log contains
`[MRVN.TriPortal] smoke completed` before `Lost connection to Origin`.

`build_collision_portal_test.py` makes this fixture reproducible, including MAP,
shader, level script, BSP/sidecars, validation report, source credits and GPL.
It stages a new directory and never installs or starts the game. Copy its
`MRVN.TriPortalTest` directory into a separate Northstar profile's `mods`, then
launch that profile and run:

```text
ip 127.0.0.1
sv_lan 1
setplaylist private_match
mp_gamemode tdm
map mp_mrvn_triportal
```

Inspect Northstar's log for the smoke marker and trace results. The test uses
stock Coliseum RPAK aliases and deliberately has no packaged material textures;
white surfaces are expected. No game assets are included. The level script uses
documented/installed Northstar APIs, with original test logic. It never changes
authentication settings; the local research run temporarily enabled insecure
authentication inside its loopback-only session after startup reset the launch
setting. That workaround did not resolve Origin disconnection.

## Provenance and attribution

- Inherited NetRadiant `FaceBSP`, `MakeTreePortals`,
  `FilterStructuralBrushesIntoTree` and `FreeTree` retain their existing notices.
  The Respawn record writers and Python inspectors added here are original
  GPL-2.0-or-later work; no external converter implementation was copied.
- snake-biscuits/**bsp_tool**, commit
  `655627ea8704353ac14bd753df8ca05c15838eda`, GPL-3.0: Respawn schema definitions
  informed independent layout checks. Upstream credited researchers include
  BobTheBob and DTZxPorter. No upstream implementation is incorporated.
- Gravemind conversion research: `games/respawn/maps/collision.md` revision 4,
  `binary-formats.md` revision 2 and `visibility-and-limits.md` revision 3.
  These supplied context and candidate interpretations; the conversion project's
  selective portals were themselves recorded as unvalidated.
- Installed retail Coliseum/Glitch BSPs provide record-size and graph evidence.
  `engine.dll` SHA-256
  `58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487`:
  independent loader disassembly around RVA `0x127ee4` / `0x128090` establishes
  the small-mesh node exception; triangle decoders around `0x1d522d` and
  `0x1d832b` establish the bit extraction and raw vertex addressing.
  No game binary, disassembly, map or extracted assets are distributed.

See [RESPAWN_SOURCES.md](RESPAWN_SOURCES.md) for the project's source register.
