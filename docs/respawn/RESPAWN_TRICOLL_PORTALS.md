# Titanfall 1/2 triangle collision and view portals

Research and implementation: 24 October to 5 November 2026. This work targets
little-endian **BSP v29 and v37** (Titanfall/Online and Titanfall 2). Apex
compatibility is not established.

## Implemented scope

The TF1 and TF2 compilers emit triangle collision for solid-content patch grids,
including patch brush models. Each patch is split into headers of at most 300
nondegenerate triangles. The positions, winding and diagonal match the render
mesh. Headers of up to three triangles use the engine's node-free path; larger
headers carry conservative packed bounds. Triangle bevel generation remains unimplemented.
This does not add Bezier tessellation: the existing render path uses the imported
patch grid. Non-content and sky patches do not generate ordinary collision;
recovered sky collision with explicit contents stays in the world model cell.

Set worldspawn **`_viewportals "1"`** to generate a brush-derived visibility BSP,
directed cell portals, sky apertures, edge incidence/intersection tables and
per-cell object-access trees. It reuses this project's inherited NetRadiant
structural BSP and portal builder. Respawn parsing bypasses Q3 brush-content
classification, so a local copy is classified using Respawn contents first.
Object AABBs touching a split are conservatively referenced on both sides.
The full leaf BSP remains for point classification. Opaque leaves share one
cell without outgoing portals. Cells are whole BSP subtrees, so the renderer's
front-to-back walk can order them from any viewpoint (see
[In-game culling](#in-game-culling-with-_viewportals-6-november-2026)); this
replaced convex merging and clustering on 6 November 2026. Subtrees of connected
open leaves merge first; to fit the native limit of 1,022 cells, the smallest
remaining subtrees merge, then small brushes become visibility detail. Cells
never span hint, area-portal or water interfaces or regions separated by solid,
and merged cells deduplicate their object references. If protected partitions
cannot fit the budget, compilation fails instead of dropping the boundaries.

TF1/TF2 shader definitions now accept `$compileflag hint`, `$compileflag skip`
and `$compileflag areaportal`. Compiler-only partition materials also need
`$contentflag nonsolid` and `$compileflag nodraw`. A hint brush can use `hint`
on its splitting face and `skip` on its other faces. This preserves static
partitions; runtime area-portal opening/closing is not implemented.

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
| 68 TRICOLL_NODES (v1) | 16 bytes | packed acceleration bounds; writer repeats conservative header bounds |
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
Bits 24–27 of a triangle word encode its bevel count. Counts below 15 use
11-bit local triangle indices; 15 indicates a chained representation. Each
chain segment starts with two packed values forming a header index and a 7-bit
count, followed by triangle indices in that header; a segment referencing its
own header ends the chain, including a zero-count segment naming that header.
A zero count on a foreign header does not terminate native traversal. TF1 uses 10-bit values.
The validator checks ranges, targets and termination for both forms. This
packing interpretation follows [bsp_regen](https://github.com/snake-biscuits/bsp_regen)'s
TF1-to-TF2 converter and passes the sampled retail maps. The stricter termination
rule was independently verified in both installed engines after a native fixture
exposed a validator gap (see below).
The compiler now has an original bounded encoder in
`respawn/tricoll_bevels.h`, and both BSP writers emit the packed bevel-word lump.
It packs TF1's 10-bit or TF2's 11-bit values across word boundaries; uses direct
local lists for counts below 15; groups foreign references into segments of at
most 127; and puts the terminating local segment last, or writes a zero-count
terminator when there is no local segment. Direct local lists do not need to
encode their header number. The chain header field holds 13 bits in TF1 or 15
in TF2. Unrepresentable target indices, chain header numbers, more than 127
local references in one chain, and streams exceeding 65,535 values fail
explicitly; the eventual selector must repartition headers when necessary.
The source pipeline uses the encoder, but still supplies empty lists pending
complete geometric selection. This does not enable triangle bevel generation.

A local round trip decoded retail references, re-encoded them with the C++
encoder, and independently decoded and validated its output in Python. Across
seven distinct sampled map geometries (Angel City plus six TF2 maps), all
9,814,659 references in 2,412,279 triangles were preserved, including 600,777
chained lists, with zero validation errors. An eighth beta Angel City sample
has the same collision totals and also passed; it is excluded from those sums.
A first native chain probe exposed an unsafe pre-existing validator assumption:
it accepted a zero-count foreign-header segment as a terminator. TFO crashed
during hull sweeps of such a probe at engine RVA `0x2b7778`, reading a null
header pointer after overrunning a chain. Independent TFO disassembly at
`0x2b780f` and TF2 disassembly at `0x1d96bb` compare the target header pointer
with the source pointer to terminate; neither loop stops solely on zero count.
The serializer now emits current-header zero-count sentinels, and the Python
validator follows that same termination rule. Consequently a foreign-only
chain also requires the current header index to fit its 13/15-bit field.
The failed probe remains a local negative fixture. A synthetic regression
covers a foreign zero-count segment, both alone and followed by a proper
current-header sentinel.

Synthetic C++ cases cover direct/chain transitions, 127-reference segments,
foreign segment splitting, maximum header numbers, maximum triangle indices,
the exact 65,535-value limit, and explicit overflow rejection. Corrected native fixtures replace the previously tested direct plane lists with
32 cross-header chains: 16 end in a nonempty local segment and 16 use a
zero-count current-header segment. Additional passive header copies provide
the same target planes without adding collision primitives. TFO and TF2 each
completed all 312 checks; every contact agrees with its own direct-encoding
baseline within 0.002 unit and 0.000002 fraction. This verifies serialization
without claiming that the experimental plane selector is complete. The final
Release build, 49 compiler regression fixtures, C++ encoding tests and 189
Python tests pass.

Bits 28-29 select the lowest-Z vertex, and bit 30 selects which of the other
two is highest. The writer now breaks minimum ties toward the first vertex and
maximum ties toward the last; horizontal triangles therefore encode 4 in bits
28-31, rather than 0. This rule matches all 591,144 Angel City triangles and all
16,632 Coliseum triangles. A wider check of 17 maps (11 mounted TF1 maps and six
TF2 samples) matched 6,828,065 of 6,828,080 triangles. The 15 exceptions are in
Colony02/Glitch around tied or nearly tied heights; their cause is unresolved.
Bit 31 and geometric bevel selection remain only partly understood.

Native triangle collision is one-sided. A TFO flat-patch fixture originally faced
downward: downward rays missed in both world and entity forms, while reversing
only its collision winding made both world rays hit the authored z=64. Changing
height flags or reducing the header to the node-free path did not fix the
back-facing fixture. A correctly facing patch-only entity compiled with the
fixed TF1 VPhysics extrusion passed both downward rays at z=64 and three isolated
physics-object drops at z=65.2188..65.3125. A repeat passed both rays and ten
isolated drops at five positions and two heights (z=70/100), resting at
z=65.2188..65.3438. These are distinct native triangle and
IVP collision paths; one passing does not prove the other. The sweep study
below covers a limited set of front-facing world patches; backfaces, transformed
patch entities, other orientations and general swept-clearance parity remain
unproven.


## Swept patch comparison (4-5 November 2026)

`swept_patch_test.py` builds six original surfaces: flat, slope, ridge, valley,
dome, and a degenerate-grid two-triangle surface. It checks authored collision
positions against the emitted data and stages 156 traces (48 rays, 108 hulls),
including finite edges, misses, seams, two hull widths, and diagonal sweeps.
A second build replaces each roof triangle with a closed convex brush prism.
The staging tool never installs or launches a game. `tfo_harness.py` now accepts
12-value `hulls` rows (start, end, mins, maxs), and optional `hull_z` expectations.

The independent references in `swept_box.py` and `swept_capsule.py` calculate
ideal box and finite rounded-capsule contact without reading BSP flags, bevels,
or native trace code. A box reference is **not** the native script hull shape:
TF2's `TraceHull` setup enforces equal XY widths, stores the horizontal radius,
and derives vertical segment half-length as half-height minus radius. Local
server binary inspection found registration at RVA `0x2a6f55`, wrapper
`0x290d20`, script implementation `0x2aab90`, and hull constructor `0xba0d0`. The inspected server SHA256 is
`a5ca3a25c8ae56952a26141b0f6cdcb6c19086c8c39013f7cb345d5d723661af`.
On a z=64+x/4 plane, radius-8 downward sweeps contact at about
`z(x)+8*(sqrt(1+0.25^2)-1)+0.0322`, rather than the box support
`z(x)+2`. A standalone sloped brush and patch matched on all 26 native TF2
sweeps, including their conservative edge behavior.

Before convex brush merging, the native TF2 patch and brush-prism runs matched on **154/156** cases.
Two diagonal dome hulls differed: patch z84.0953 / z84.972 versus brush z85.6219
in both directions. Ideal rounded-capsule contacts were z83.9050 / z83.2919;
neither native representation is an exact finite-capsule oracle. These cases
remain unresolved; the test does not loosen its 0.12-unit comparison tolerance
to make them pass. Native ray anchors also prevent two equally missing surfaces
from satisfying the comparison. Northstar 1.31.13 executed the second run's
checks before a disconnected Origin session shut down the local server.

TFO completed all 156 patch sweeps without a map crash or script error. Its
brush-prism comparison matched **143/156**: two dome diagonal hull differences
and eleven brush rays missing shared diagonal boundaries, where the patch rays
hit. A focused repeat confirmed both flat-roof diagonal misses, while rays
0.01 units to either side hit z64.0313. The exact convex merging correction below
removes the reproduced internal seams for compatible brushes. General hull
parity and seams that cannot be merged remain unproven.

A diagnostic TF2 variant assigned every other triangle in each header as a bevel
reference. All 156 checks completed, but valley contacts dropped by up to 48
units and dome contacts also changed incorrectly. This variant remains a local
experiment; the compiler does not use that rule. Retail analysis found a
necessary support-plane constraint: all 1,848,160 Angel City references and all
31,893 Coliseum references (including chained/cross-header references) put the
source triangle behind the target's front-facing plane within 1/32 unit. Maximum
observed distances were 0.03123383 and 0.03124794, respectively. All Angel City
references also touched that plane within 1/32 unit. This is evidence for a
selection constraint, not a complete bevel selector; locality, redundancy and
additional geometric conditions still need derivation. These are collision findings, not a completeness
certificate. Geometric bevel selection remains unimplemented.

Reproduce staged native comparisons with separate new output directories:

```text
python tools/respawn/swept_patch_test.py build --remap install/Release/remap.exe --game titanfall2 --output PATCH_DIR
python tools/respawn/swept_patch_test.py build --remap install/Release/remap.exe --game titanfall2 --surface-mode brushes --output BRUSH_DIR
python tools/respawn/swept_patch_test.py compare --game titanfall2 --cases PATCH_DIR/cases.json --baseline PATCH_LOG --reference BRUSH_LOG --output REPORT.json
```

For TFO, choose `--game titanfallonline`, run each map folder with
`tfo_harness.py --checks DIR/checks.json`, and compare the saved `tforevive.log`
files. `checks.json` anchors the native rays; `box-checks.json` is a separate
ideal-box diagnostic, not a valid capsule expectation. `verify --shape box` or
`--shape capsule` explicitly chooses an ideal geometric diagnostic.


### Exact convex collision-brush merging (5 November 2026)

The shared TF1/TF2 CM emitter now merges adjacent compatible authored brushes
when their union is convex. It removes only the shared internal plane; it does
not inflate planes or fill concavities. Candidates must use one material across their sides; per-face texture mappings
and contents must agree. Recovered per-primitive contents, sky/hint/area-portal/skip
brushes, missing explicit source planes and incompatible faces are retained separately.
Merging stays inside one world/entity model. Original render and IVP brushes
are retained; their contents are classified before collision copies are made.

The test uses all boundary vertices to prove each volume lies behind every
non-interface plane of the other. Opposite interface planes must coincide in
double precision. After merging, the inherited brush-winding builder reconstructs
boundary vertices for later tests; internal tile corners are not accumulated.
The merged AABB is the union of the original bounds. Geometrically identical
planes are deduplicated only when material and texture mappings also agree.

The six-surface brush fixture reduced from 43 to 10 CM brushes in both formats.
The TFO full run recovered all eleven formerly missed shared-edge rays. A final
repeat of the seven focused seam/near-seam rays hit z64.0313 in every case.
All **156 merged-brush native results agree between TF1/TFO and TF2** within the
0.12-unit comparison tolerance, including independent authored ray anchors.
The final TF1 collision plane/grid payload was checked byte-for-byte against
the full native run after the last guard changes. The final build also passed
45 compiler fixtures, including concave/gap/material/mapping/recovered-contents
rejection, point-membership sampling, and a merged entity after a non-axial world
brush. TF1 IVP checks confirm the two original ledges remain intact.

This improves the brush reference rather than resolving triangle bevels. Against
the corrected brush reference, both formats' current triangle data match
**152/156** sweeps. Four dome hull cases remain: the two radius-16 outer-edge
sweeps and both diagonal sweeps. The corrected brush diagonal contacts are
z83.9336 / z83.3149 in both games, close to the ideal capsule z83.9050 / z83.2919;
old TF1 triangle contacts were z85.354 / z85.5108 and TF2 contacts z84.0953 /
z84.972. Those discrepancies remain open.

A separate 32-by-32 authored box tiling compiled to one collision brush in
0.274 seconds on the local machine (1,024 input brushes). This is a fixture
measurement, not a general compiler performance claim.


### CM brush bevel output (5 November 2026)

The first CM_BRUSHES count byte is the non-discard non-axial plane count; the
second includes supplemental bevel planes. Actual cutting planes come first,
then bevels whose CM_BRUSH_SIDE_PROPERTIES value carries `0x4000`. The six axial
slots precede both groups. This ordering matches all 180,364 brushes and 858,010
supplemental planes across the 17-map TF1/TF2 corpus. The record validator now
checks it, rather than treating the first byte as an unknown field.

The emitter previously discarded every non-axial `side.bevel` and wrote both
count bytes identically. It now preserves inherited edge bevels, uses the map
plane when a generated side has no explicit double plane, and writes matching
property/texture-vector entries. The inherited NetRadiant bevel builder accepts
an explicit brush so collision copies can regenerate bevels after convex
merging; generated edges inherit their source face's material/mapping data.
A bounded generation check prevents merging from turning valid inputs into a
brush with more than 255 non-axial planes. The regression keeps two valid
108-authored/216-total-plane cones separate when their merged bevel set exceeds
the native field.

An independent comparison uses 78 moving boxes against a closed authored
triangular prism: triangle SAT is compared with clipping the boxes against the
emitted half-space planes. Omitting the bevels produces three incorrect contact
fractions; the complete emitted set matches all 78 in both formats. These are
geometric box-sweep tests, not native script box traces (the script TraceHull
path constructs a capsule).

Native TFO completed the original 156 sweeps with these brush records. Sixteen
additional crease sweeps at radii 8/16/32/64 hit the new planes and match an
independent exact-capsule calculation plus the 1/32-unit plane skin within 0.002
units. An unchanged-geometry before/after run moves the contacts by
0.0585..0.4669 units, removing the former early contacts; returned normals change
to the supplemental plane normals. TF2 passes the complete 172-case set. The
current build passes 49 compiler fixtures and 188 Python tests.

This restores the inherited edge-bevel path; it is not a claim of full retail
bevel-generator parity. For example, retail TF2 axis boxes also carry four
horizontal corner-support planes that the inherited axial-only builder did
not create; the pure axial TF2 case is now implemented and tested below.
Triangle bevel selection, broader native box/entity sweeps and supplemental
plane generation for more general shapes remain open.

### Triangle-selector diagnostics (5 November 2026)

Local support-plane candidates resolve the four original dome differences.
Removing same-plane duplicates gives 50 references; additionally requiring the
source to touch the target plane within 1/32 unit gives 42. Both refinements
completed 312 combined native checks per game and agree across TF1/TF2. Two
radius-8 outer-edge contacts still differ from the brush reference, although
they are closer to the ideal finite-capsule result. No candidate rule has been
adopted as the production triangle selector.

Every one of Angel City's 1,848,160 retail references shares at least one exact
vertex and supports the source triangle within 1/32 unit. None of those selected
pairs is mutually coplanar within 1/32; the smallest measured coplanarity
deviation is 0.03126124. A supporting vertex-neighbor rule with that coplanar
exclusion contains all retail references but still over-selects before adequate
plane deduplication/pruning. Coliseum is different: 20,792/31,893 references have
no shared vertex, and many support without touching. Its normals are all acute;
TF1 also contains obtuse references, so the acute test cannot be generalized.

The completed geometric plane-equivalence audit leaves 653,652 distinct extra
candidates in Angel City, in addition to 969,342 candidates equivalent to an
already selected plane. Plane deduplication alone therefore cannot recover the
retail selector.

A source-orientation audit identifies a TF1-specific boundary: all 1,848,160
Angel City references originate on triangles with normal Z at least -0.5
(minimum measured -0.499998897). None of its 67,129 triangles below -0.5 has
references. This is not a shared TF1/TF2 rule: Coliseum has 7,770 references from
2,186 triangles below -0.5, with minimum normal Z -1.0. The physical front normal
here is `cross(v2-v0, v1-v0)`. This evidence narrows the TF1 candidate search;
it does not establish a complete selector or justify dropping TF2 references.
Applying only that source cutoff to the candidate audit preserves every Angel
City reference and reduces distinct extra planes from 653,652 to 199,824
(453,828 removed). The 969,342 duplicate-plane extras remain. The condition
cannot also be applied to targets: 176,134 valid Angel City references target
planes below -0.5, including normal Z -1.0. These counts are audit results, not
production compiler behavior.

A separate necessary-condition audit checks how far the source triangle extends
behind its target plane. Every one of 9,814,659 retail references across Angel
City and the six sampled TF2 maps has at least one source vertex more than
1/32 unit behind that plane. This rejects a source triangle lying entirely
inside the plane's +/-1/32 slab, even when the larger target triangle is not
mutually coplanar. No selected-reference exceptions were found. It is still a
necessary condition, not a complete selector. Applying it to the TF1 candidate
audit preserves all 1,848,160 Angel City references and reduces distinct extra
planes from 199,824 to 142,749 (57,075 removed); 968,074 plane-equivalent extras
remain. The earliest exact-perpendicular counterexamples remain unresolved.

### Closed-prism native diagnostics (5 November 2026)

A local diagnostic extracts one closed convex octagonal prism from Angel City
(28 triangles, 16 vertices), translates it, and tests its original size and an
8x scale. Each size has four representations: no triangle bevels, the 93 TF1
retail references, 190 shared-vertex supporting-plane candidates, and a closed
CM brush. The candidate set includes the TF1 source-normal cutoff and source
slab exclusion described above. The same TF1 reference lists are consumed by
both games; these are not asserted to be TF2's own retail-selected lists.
Triangle positions and front winding are checked against the compiled output.
Extracted game geometry and all generated test artifacts stay local.

Both TFO and TF2 completed 3,744 outside-start sweeps each, covering all 26
nonzero {-1,0,1} directions, three lateral offsets, point traces, radii 8/16/32/64
and a tall radius-8 capsule. Every requested result was present and no result
was start-solid. Relative to the copied retail lists, candidates change 19 TFO
hull contacts (16 original size, 3 scaled) and 20 TF2 hull contacts (18 original
size, 2 scaled) by more than 0.12 unit. The maximum change is 4.466176 units in
TFO and 7.600640 in TF2. Point traces remain within 0.001 unit. Changed contacts
occur later and are closer to the independent finite-capsule calculation in
this sample, but native results still have substantial approximation error.
Additional candidate planes therefore have observable effects; they cannot be
assumed redundant merely because they support the entire convex component.
This experiment does not establish a production selector. Production triangle
lists remain empty pending an adequately validated generation rule.

The first TFO launches failed before loading the map with the known graphics
driver stack overflow; the corrected diagnostic subsequently completed without
test errors. Owned crash handlers were closed. TF2's controller and game were
stopped, its temporary mod archived, and its enabled-mod configuration restored
byte for byte.

### TF2 axial-box corner supports (5 November 2026)

`AddBrushBevels` now adds four horizontal unit support planes to pure axial
boxes for BSP v37, with XY normal signs (-,+), (-,-), (+,-), (+,+), each at 45
degrees. Their distances pass through the corresponding authored box corners.
They are discarded supplemental planes after the six axial sides, with zero
non-discard cutting planes. Regeneration after exact brush merging retains
that layout. Existing side budgets are checked before adding all four. This
profile is TF2-specific; TF1 output retains its previous generation behavior.
It does not implement the full supplemental-plane profile for non-axial shapes.

Compiler regression checks the four distinct unit normals, boundary support,
native discard flags, and following brush/model plane prefixes. Native TF2
checks compare two box sizes (64x64x64 and 16x128x48), both representations,
four approach directions, six lateral offsets and radii 0/8/16/32/64: all 960
contacts match independent expanded-halfspace intersections, including native
1/32 skin, within 0.001 unit (maximum measured error 0.000853). The supplemental
planes change 192 contacts by 0.67328..36.837888 units, removing early square
corner contacts. The axial-only control keeps the same BSP storage but replaces
the four diagonal planes with duplicate supporting axial planes.

The lighting regression exposed an interaction: supplemental sides may have
only a float plane index and an empty double-precision visual plane. Passing
that empty plane to the shadow segment test made a brush cast no shadow.
The TF2 baker now uses authored faces for opaque shadow geometry. The existing
roof sun-visibility regression catches this failure and passes with the fix.
The Release build, 49 compiler fixtures, C++ encoding tests and 189 Python tests
pass. All 23 matched TF1 regression BSPs retain byte-identical collision lump
payloads. Native test processes and temporary configuration changes are cleaned
up after the run.

### General brush bisector audit (5 November 2026)

The four TF2 box supports should not be generalized to every face pair yet.
Retail examples include planes bisecting adjacent tilted faces, but a physical
hull audit still finds steep-face bisector candidates that retail omits: 479 in
the sampled Glitch brushes and 4,087 in the sampled Colony02 brushes (at most
24 stored cutting planes per brush). Other supplemental normals are neither
simple source normals, Q3 edge directions nor these bisectors. Discard status
alone does not identify which stored planes are physical faces; the diagnostic
reconstructs the clipped hull before classifying its facet and support planes.
This is evidence against an unconditional extension, not a complete account of
retail pruning. Production general-brush generation remains unchanged by this
audit; the verified pure axial TF2 profile stays enabled.

### Bevel header partitioning (5 November 2026)

`respawn/tricoll_partition.h` plans headers from stable entity-wide triangle IDs
before any geometry is emitted. Authored patches remain separate material and
contents batches; ordinary empty-list output keeps the existing cuts of at most
300 triangles. A header is split if a source list exceeds the 127-local-target
chain limit or its aggregate packed-value stream would exceed 65,535. Splitting
can increase foreign segment overhead in other headers, so all headers are
rechecked until the final layout fits. Every reference is then remapped to the
new global header and local triangle index and passed through the bounded
encoder. References outside the entity and intrinsically unencodable lists or
header indices fail explicitly. This is storage repartitioning, not a new
geometric selection rule or a claim of optimal header packing.

Patch triangle collection now precedes partitioning and emission, so a future
selector can inspect compatible edges across patch/material/header boundaries
inside one entity. Material and contents ownership remain attached to each
batch. Collision emission reads ranges of the original collected triangles;
it does not reorder, duplicate or alter them to fit a header.

Independent C++ decoding recovers the original reference multisets after a
300-triangle dense fan is repartitioned, after aggregate stream overflow, and
after a target split makes an initially fitting foreign stream overflow.
Boundary/invalid-input cases cover final native header IDs, chain address
limits, missing targets, empty batches and lists that cannot fit even in a
one-triangle header. The Release build, 49 compiler fixtures, C++ encoding tests
and 189 Python tests pass. Across all 50 emitted TF1/TF2 regression BSPs, lumps
3, 66, 68, 69, 96 and 97 are byte-identical to the pre-refactor baseline. (The
production selector and header grouping below now replace the empty lists and
per-patch batches.)

### Production triangle bevels and header grouping (6 November 2026)

remap now writes triangle bevel lists for TF1 and TF2 with a functional rule,
`respawn/tricoll_bevel_select.h`: a source triangle (physical front normal Z of
at least -0.5) references every triangle of its entity that shares a vertex and
whose plane supports it (all source vertices within 1/32 unit in front, at least
one more than 1/32 behind). It is not retail's selector. TF1 Angel City's retail
references all satisfy it; on retail TF2 Coliseum geometry it reproduces 31.9% of
retail's 18,817 references (TF2 also references triangles without a shared vertex)
and adds 48,933 others. The adoption criterion was native safety, not parity.

Native sweeps (TFO and TF2, outside starts, 26 directions, three lateral offsets,
point traces and five box hulls) compared three representations of each shape:
triangles without bevels, triangles with the rule's lists, and native CM brushes.
Sweeps within 3 degrees of parallel to a face were excluded: on identical
geometry at different positions they gave contacts up to 366 units apart.

- **Closed concave solids** (V-notch, L-step, zig-zag ridge, pyramid pit;
  watertight, outward, volumes checked analytically; 5,148 cases per game):
  without bevels, triangles caught early against the brush result on the notch
  (20 TFO / 8 TF2 non-grazing hulls) and zig-zag (12 / 3); with the rule, no
  sweep was earlier than the brushes and no new difference appeared. Point traces
  matched the exact box sweep everywhere.
- **Open terrain** against prism brushes (each triangle extruded down; downward
  non-grazing hulls): early contacts fell from 79 to 48 (TFO) and 67 to 46 (TF2),
  worst cases from 46 to 37 and 44 to 24 units; no sweep became later than the
  brushes (TF2 kept the same 3 later cases with and without bevels).
- **Purely concave neighbours** (valley, pit) select nothing, by construction.

Native hulls are not exact box sweeps: native brushes themselves stopped up to
31.6 units past the exact AABB contact on sloped ridges, and triangles without
bevels matched the exact sweep there. The criterion is therefore agreement with
native brushes, the engine's own solid behavior.

Compiled output was checked natively without injection: the same closed-solid map
built from the compiler's own lists (one grouped header, own-header chains) matched
the injected runs on all 5,148 sweeps in both games within 0.001 unit. The
regression decodes the dome patch's emitted lists and compares them with an
independent Python implementation (`tricoll.select_bevels`); a full retail-derived
Coliseum compile matched it for all 16,632 triangles (85,709 references).

**Header grouping.** Patches with the same material, contents and sky flag now
share headers, ordered by triangle-centroid Morton code and cut at 300
triangles. One header per patch gave 16,632 headers for decompiled Coliseum
(retail: 184); it now gives 63. That exceeded TFO's 8,192 virtual-mesh physics
objects and TF1's chain header field (2 * 10 - 7 bits, 8,192 headers). Bevel
references that still cannot be encoded are dropped with a warning instead of
aborting the compile; a dropped bevel leaves contact conservative.

**Cross-engine retail comparison.** Angel City and Relic ship in both games,
compiled by Respawn for each engine (`.local/respawn/cross_engine_tricoll.py`).
On triangles matched by position (358,245 in Angel City, 374,424 in Relic):

| | Angel City | Relic |
| --- | --- | --- |
| TF1 / TF2 headers | 5,806 / 9,133 | 3,775 / 5,730 |
| TF1 / TF2 bevel references | 1,160,466 / 571,701 | 1,001,229 / 552,696 |
| In both lists | 257,930 | 251,626 |
| TF1 references satisfying remap's rule | 100% | 100% |
| TF2 references satisfying remap's rule | 54% | 60% |
| TF2 references to triangles sharing no vertex | 36% | 25% |

Respawn changed the selector between engines on identical geometry: TF1 lists
are about twice as long and always fall under the shared-vertex supporting-plane
rule; TF2 selects fewer adjacent planes and more non-adjacent ones. remap's rule
is therefore a superset of TF1 retail behavior and a different selection for TF2.

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
visibility correctness. There are 26 compiler fixtures and 168 Python tests.
MSVC Release remap builds successfully.

Retail checks on Coliseum: 184 headers, 16,632 triangles, 11,084 nodes,
41 cells and 409 portals. Glitch: 3,544 headers, 902,760 triangles, 601,580 nodes,
75 cells and 1,079 portals. Both pass the dedicated range/topology inspectors.
Local reports and generated fixtures stay under ignored `.local/respawn`.

The same inspectors also passed Colony02, Homestead and LF Stacks: across all
five samples, **1,821,039 triangles, 311 cells and 3,341 portals**. The tricoll
inspector also checks TF1's 10-bit bevel indices; retail Angel City passes with
591,144 triangles, including chained entries. The same checks pass on the 11
Titanfall 1 maps mounted by the local Titanfall Online shared-content mod.

### Native visibility cell budget

The TF1/TFO and TF2 renderers both reserve two bits of fixed 1024-bit cell masks
for sentinels. Independent inspection of local binaries found equivalent mask
initialization and traversal in TFO `client.dll` at RVA `0x5e9030` and TF2
`client.dll` at `0x2eae40`. Both initialize the mask at frame offset `+0x10`, mark
`cellCount` and `cellCount+1`, and use nearby fixed traversal storage. Hashes:

- TFO client: `0c8bba1e77860765edf550a69da3d16c1f5292465e51208e022940ff7ab76384`.
- TF2 client: `002b36487fec7c98882929fbccdb506d0146bbf3270cbb964a4d21c5edf7eebc`.

The generator and inspector enforce 1,022 cells for both targets. The old E1M1
full-portal map (5,728 cells / 14,864 portals) crashed at TFO client RVA
`0x5ea574`; convex merging alone (1,832 cells) still crashed at `0x5e93a0`.
The budgeted build (1,022 cells / 11,132 portals) completed six traces and three
rendered camera views. On 4 November 2026, the 1,156-pillar/divider/hint stress
fixture also loaded in TF2 with Northstar 1.31.13: 1,022 cells and 6,970 directed
portals. Native traces hit the floor at z0.03125 and the divider at x539.969,
passed through the open chamber, and crossed the nonsolid hint with fraction 1.
Three rendered views covered both chambers and the opposite side of the hint;
they showed the floor, ceiling, walls and pillars using the stock Coliseum
`WORLD/DEV/DEV_GRAY_512` material. The local session remained connected through
the captures and did not crash. This verifies the tested graph at the native
budget, not retail culling parity or a full playthrough.

The stress fixture compiles in both formats and verifies that the cell budget
(now met by making its pillars visibility detail) preserves connectivity within each half, cannot cross its sealed divider, and
keeps the authored hint split at 34 sampled crossings. Separate small fixtures
check hint and area-portal partitions. Native merge-group tests cover protected
interfaces whose endpoints are joined through alternate paths.

TF1 portal inspection is now included in the general record validator and the
standalone CLI. All 17 sampled retail maps pass. The inspector also accepts
TF1 mp_o2's exact empty-global-root accumulation sentinel, with zero child,
direct-reference and total-reference counts; it still rejects that bound pattern
on ordinary roots or nonempty global roots.

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

### In-game culling with `_viewportals` (6 November 2026)

**Resolved.** E1M1 built for TF1 with `_viewportals` dropped whole walls at one
camera (-272 2928, yaw 0) in both R1Delta and TFO, compared with the same map
without portals. After the fix below, all 12 R1Delta views and 4 TFO views
match the portal-free build apart from HUD and team-colour pixels.

**How the renderer culls.** TFO `client.dll` (SHA-256 `0c8bba1e...`):

1. RVA `0x5e9030` finds the camera's cell(s) by descending the cell BSP, then
   walks a depth-first search over portals whose front faces the camera
   (portal byte 0 picks the plane sign), **visiting each cell once**. Cells get
   slots in post-order from the end of an order table, giving a reverse
   post-order: front to back when the graph has no cycle.
2. RVA `0x5ea2b0` processes cells in that order. A cell that has view regions
   (only the camera cell at first) tests each camera-facing portal's vertices
   against them (outcodes over up to 9 planes), clips, and hands the result to
   the destination cell. A cell's regions are consumed when its turn comes.

TF2 `client.dll` RVA `0x2eae40` (SHA-256 `002b3648...`) has the same structure. If
camera-facing portals form a cycle, the DFS order puts a cell before a
predecessor that later passes it a region, and that region is lost. This is
what hid the walls.

**Why remap's cells broke it.** The cells were merged from BSP leaves, first
into convex groups and then clustered (non-convexly) to fit 1,022. Both kinds of
merge can create cycles. Even convex groups can: a partition orders front to back
from every viewpoint when it is a BSP, not merely when its cells are convex. An
offline model of the algorithm (`.local` `portal_sim.py --engine`) dropped 18
to 135 regions per camera on those builds and none on retail Angel City.

**What remap does now** (`CollapseVisibilityCells`):

- Cells are **whole BSP subtrees**. Collapsing a subtree keeps the BSP's
  ordering, since all its external portals lie on the subtree's convex boundary.
- Exact pass: a subtree of open leaves connected through internal portals
  becomes one (convex) cell.
- Budget pass: if more than 1,022 cells remain (including the shared solid
  cell), the smallest subtree whose children are single cells and whose open
  leaves are connected is collapsed, repeatedly. Cells never span a hint, an
  area portal, a water surface, or open regions separated by solid, so sealed
  rooms stay disconnected.
- If that cannot reach the budget, brushes thinner than a threshold in two
  axes (pillars, trim; not walls or floors) become detail for visibility, and
  the threshold rises (16, 24, 32 ... 512 units) until the cells fit. remap
  warns with the value used; worldspawn `"_vis_detail"` sets a starting value.
  E1M1 settles at 96 units, 1,022 cells with 295 subtree merges.
- Water is now cell-aligned: a sloped pool's water is its own cell, separate
  from the air within its bounding box.
- `portals.py` `ordering_cycles` samples cameras in front of portals and counts
  camera-facing portals that point back to an earlier cell; the stress fixture
  must have none. Retail TF1 has some (Angel City 41, Relic 21 over ~100 cameras)
  that its frustum clipping evidently never reaches; TF2 Coliseum and Glitch have
  none.

Also from this investigation:

- **Access roots.** Every retail access node (Angel City, Relic and six TF2
  maps) encloses the bounds of its object references; remap now matches, and
  `portals.py` reports "does not enclose" otherwise.
- **Mesh ownership.** Retail meshes stay within their cells (1.35 to 1.68 cells
  per mesh; 79% of Angel City's by one cell). remap still merges each material
  into larger meshes; splitting them per cell is not needed for correctness.

Not yet run: a TF2 map with `_viewportals` in Northstar (the harness is not on
this machine); the TF2 traversal was checked statically. `_viewportals` stays
opt-in until it is.

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
