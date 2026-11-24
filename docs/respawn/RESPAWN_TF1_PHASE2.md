# Phase 2: Titanfall 1 / Titanfall Online support

Checkpoint: 17 November 2026. **Partially verified; full support is not complete.**
Phase 1's surf release gates remain open; the user requested Phase 2 work in
parallel with them. Initial runtime testing used TFORevive because another
system was using EA/Origin. After the user confirmed EA was signed in,
R1Delta 3.0.5 also passed the six shared baseline collision checks. Subsequent
work added paired barrel support controls and sequential drops, described below.
Broader acceptance in both runtimes remains outstanding.

The [navigation export/integrity checkpoint](RESPAWN_TF1_NAVIGATION.md) adds a
bounded native exporter and offline CRC calculation. Original and changed
pillar/node fixtures route in both runtimes; live R1/TFO CRC observations agree
with the changed fixture's offline result. Broader AI and full release gates
remain open.

## 20 November: v29 sun shadow output

A prop-free sunlit fixture exposed inverted bounds in the generated v29 CSM
root. The compiler now emits a zero-size root with no references in this case,
without changing the v37 placeholder. The shared lighting pass now reads the
original compile flags for each mesh rather than looking up serialized material
names. Alpha-tested casters go only into the alpha stream; compile-only sky
stays drawable but contributes to neither shadow stream.

Native follow-up: the spawned `mp_tf1_shadow_mount` variant uses mounted TF1
materials for the floor, alpha-cutout grate and compile-only sky stand-in.
Its BSP validated with 24 opaque and 12 alpha-tested shadow triangles and no
sky triangles in either stream. R1Delta loaded it, passed both floor and roof
traces, and produced three engine captures. The cutout and sky stand-in render;
this is not a controlled image comparison of their projected shadows.

TFO reached `PROGRESS_LEVELINIT` on one launch but never reached the harness
spawn checks. Other launches, including the same geometry with point-only
lighting, ended with a stack overflow in `nvwgf2umx.dll`. The known-good
`mp_tf1_baseline` control passed after a startup retry. This leaves the TFO
lighting result inconclusive; it does not isolate a shadow-lump defect.
Reports, source fixtures and captures are under
`.local/respawn/tf1-shadow-native-20261120/`. Broader water, physics, gameplay
and clean packaging remain release gates.

### Matched TFO baseline and v29 mesh validation

Two variants of the known-good `mp_tf1_baseline` keep the same geometry, materials,
spawns, map name and six collision checks. The point-lit variant passed all six
checks. The first sunlit run reached level initialization but did not reach
the spawn checks within its 50-second launch budget. The full-budget follow-up
below shows that this short run did not establish a shadow-mesh stall.

The sunlit BSP with only its four shadow mesh streams (lumps 124–127) removed
also spawned and passed all six checks after a startup retry. The v29
compiler exposes the same opt-out as `"_remap_no_shadow_meshes" "1"` in
worldspawn. It keeps baked lighting, world lights and the CSM tree, but omits
dynamic world-geometry shadow meshes. The default keeps the meshes enabled;
the opt-out is not required to load the tested TFO baseline.
Compiler regressions confirm byte-identical lighting planes with the option
enabled. The compiler-generated opt-out also passes record validation, but its
three TFO launch attempts failed before loading the map with startup stack
overflows. The native pass applies to the binary-stripped control, not a
successful launch of the compiler-generated variant.

`validate_records.py` now checks the v29 native mesh vertex-type byte against
its vertex pool flags and recomputes the inclusive unsigned vertex span for each
used material sort. These checks pass on six TF1 and seventeen TFO BSPs, as well
as the compiler fixtures. The run artifacts are in
`.local/respawn/tfo-light-isolation-20261120/`.

### Retail v29 sun and shadow-prop metadata

Across the six TF1 and seventeen TFO reference BSPs, the `LEVEL_INFO` direction
matches a type-3 world light normal within 0.000001, and all 115,633 CSM object
references fit the static-prop range starting at the first sky mesh rounded up
to a multiple of 64. The compiler now writes the gameplay sun direction and
converts the visibility prop index to that aligned CSM range without changing
the visibility index. Regression fixtures cover both conventions.

### Full-budget TFO retest with shadow meshes enabled

The 50-second runs stopped at different points in sign-on. The bounded-root
control reached `PROGRESS_ENDLOAD` with about two seconds left, less than the
delay before the spawn checks. A single valid shadow triangle and a control
using the retail lobby's opaque shadow stream also returned no probes with
that short budget. Those tests do not distinguish a hang from slow startup.

Using the harness's normal 300-second launch budget, the **unchanged** rebuilt
sunlit baseline (`sun-native-metadata`, 20 generated opaque shadow triangles)
finished loading about 92 seconds after launch. It passed both ray traces and
all four hull checks. The same BSP with only directory entries 124–127 cleared
passed the same checks. Matched free-camera captures show the raised platform
casting a shadow on the floor with the generated streams present; the shadow
disappears in the stripped control, which leaves the baked lighting unchanged.
The reports and paired views are in `run-full-sun-native-metadata/` and
`run-full-sun-native-metadata-stripped/` under
`.local/respawn/tfo-light-isolation-20261120/`.

No BSP changes or shadow opt-out were needed. Use the normal launch budget for
native tests, and distinguish a pre-map NVIDIA stack overflow from a map that
fails after sign-on. This confirms opaque world shadow rendering in TFO on the
baseline, not full TF1/TFO release parity.

The rebuilt cutout fixture also passed both traces with 24 opaque and 12
alpha-stream triangles enabled. Removing only the alpha vertices, indices and
mesh row removed the grate's projected silhouette in the matched overhead
view. However, the silhouette looked solid with the stream enabled: these
captures verify that TFO renders the alpha stream, not that it reproduces
the grate's texture cutouts. See `run-full-cutout-alpha/` and
`run-full-cutout-alpha-stripped/` in the same artifact directory.

**Cutout shadows verified.** The solid silhouette came from that fixture, not
from the compiler or the engine. Its UVs sampled the opaque border of
`metal_grate_roundholes`: only 8% of that region is transparent, against 42%
of the whole texture. The remaining holes were about 8 units across, which the
soft shadow filter blurs away. The `cutout-visible` fixture uses a 2-unit-thick
192×192 grate with the texture offset into the hole field and scaled 2×, so
holes are about 40 units across. In TFO, with the normal launch budget, it
passed both traces. The overhead view shows round lit holes in the shadow,
and the angled view shows them matching the alpha-tested grate (`run-cutout-visible/`).
v29 alpha shadow streams therefore reproduce texture cutouts in TFO. Very
small holes still fall below the cascade's resolution, as expected for any
shadow map.

## 20 November: realtime lights now light TF1 world surfaces

The v29 realtime-light plane holds per-texel hardware light indices; the
compiler wrote all 255, so realtime point and spot lights lit nothing on TF1
world geometry. It now writes the bake's slots as hardware indices, orders
realtime lights before baked ones, and uses retail TF1 light flags. Details
and evidence are in [the TF1 lump notes](RESPAWN_TF1_LUMPS.md#lighting). Both
runtimes light a covered test room from two realtime lights; the all-255
control is black in TFO. A new `tf1-realtime-lights` compiler regression checks
flags, order and slot contents. This replaces the "RTL channel decoding" item
in follow-up task 1.

## 20 November: release packager

`build_tf1_package.py` builds a TFO mod and an R1Delta addon from a validated
compiled map, with dependency reporting, an optional shader VPK, a hashed
manifest, install notes and zips (see
[release packages](RESPAWN_TF1_LUMPS.md#release-packages)). Packaged level
folders load in both runtimes. This closes the packaging tool gap; deciding
what assets a given map may redistribute stays with its author.

## 20 November: crate physics on z=0 floors

The unresolved TFO crate-height result was a compiler defect. Negative-zero
IVP coordinates on a z=0 floor made crates bounce and wedge into it. The same
fixture now rests 8 of 8 sequential crate drops upright, as retail Angel City
does in that launch. Later repeats showed the remaining failures depend on the
launch, not on the position: in about half of all launches every crate sinks
into the floor on first contact, wherever it lands, while retail Angel City rested
every crate in 4 launches. See
[VPhysics](RESPAWN_TF1_LUMPS.md#vphysics-physics_collide) for the controls.

## Compiler parity inventory

The [per-lump checklist](RESPAWN_TF1_LUMP_CHECKLIST.md) inventories every unique
lump written by `WriteR1BSPFile`, including conditional lighting writes and the
separately serialized GAME_LUMP. It compares a fresh authored baseline against
local Angel City, Colony and the installed TFO lobby. The machine-readable
current report is `.local/respawn/phase2-geometry-final/lump-audit.json`.

- 70 unique writer lump types; 61 have schemas in `validate_records.py`, 9 do
  not. Individual tools and compiler regressions cover some of the latter;
  absence of a schema does not mean no implementation exists. The first audit
  had 44 schemas; 17 additional record layouts were added during this work.
- All four maps pass the selected static cross-reference checks and directory
  inventory without issues. Populated lump versions agree across this sample.
- `PHYSICS_TRIANGLES` occurs in the reference corpus but is not emitted. The
  engine builds its virtual-mesh hulls at load; the unresolved bytes and known
  runtime fallback are described in [TF1 notes](RESPAWN_TF1_LUMPS.md).
- VERTEX_UNLIT_TS and VERTEX_BLINN_PHONG have writer paths but no payload in
  these four maps. Add dedicated fixtures before calling them validated.
- The baseline has no lights, water or static props. Empty lumps provide no
  evidence for those features. The checklist deliberately leaves **semantic
  parity unverified** for every row; a successful parse alone cannot close it.

### Concrete follow-up tasks

1. **Lighting records:** v29 schemas and selected checks now cover WORLD_LIGHTS
   (100 bytes), LIGHTMAP_HEADERS, LIGHTPROBES, LIGHTPROBE_TREE,
   LIGHTPROBE_REFERENCES (16 bytes) and static-prop probe indices. Nonempty baked
   fixtures and six reference maps pass. CSM node/reference structure is now checked. Remaining: native shadow
   appearance, deeper lighting semantics and RTL channel decoding before replacing
   the all-255 output.
2. **Water assignment:** validate LEAF_WATER_DATA against visibility cells,
   including single-cell maps; compare paired wet/dry and retail controls for
   buoyancy and underwater rendering. A water record alone proves neither.
3. **Materials, props and packaging:** validate embedded assets, cubemap paths,
   string-table offsets, sprp placements and per-map model dependencies in a
   standalone TFO mod and R1Delta addon. Exercise the unused vertex pools.
4. **Collision:** retain the known curved-patch/dome hull cases; add transformed
   entities, backfaces and mask-specific projectile/titan tests. The baseline's
   broad hull is an explicit geometric probe, not a native titan gameplay test.
5. **Physics stability:** repeat controlled brush/patch drops and retain failures.
   Expand to curved shapes, stacking, velocities and matched retail controls;
   do not change collision generation on the evidence of one failing run.
   Validate PHYSICS_COLLIDE model/solid lengths, material tables and fluid
   keydata with nonempty brush, water and submodel fixtures. PHYSICS_TRIANGLES
   remains an optional load-time optimization until its unknown fields are decoded.
6. **Visibility:** validate water portals, large maps and opt-in portal geometry
   independently of the baseline's single-cell visibility path.
7. **Gameplay/release:** every mode's spawns/objectives, AI navigation, converter
   targets and paired-runtime packaging remain open. Require human matches in
   both runtimes for the roadmap's exit criteria. Include ENTITIES and
   ENTITY_PARTITIONS syntax, nonempty spawn/script sidecars and trigger behavior.

## Reproducible authored baseline

`prepare_tf1_baseline.py` writes original brush and flat-patch geometry, spawns,
an R1Delta intermission camera and a shared `checks.json`. It refuses to reuse
an output directory. The build manifest records the command and SHA-256 of the
compiler and BSP, so the installed binary's age is explicit rather than assumed
to match the current source checkout.

The baseline checks two downward rays, a pilot-sized and a broad titan-sized
box over each surface, then two sequential physics probes. Brush top: z=0;
patch top: z=128. The final baseline uses models/containers/crate.mdl physics probes;
they do not test fired grenades or weapon projectile masks. No screenshots are
requested, so this run cannot establish visual or lighting correctness.

Environment: Windows, TFORevive.Core 135, ARES `4fe8d69`, MRVN-Radiant source
`c8e40d2` plus the new audit/fixture tools. The existing `install/Release/remap.exe`
was built 9 November; its precise fingerprint is in `build.json`. No compiler
C++ behavior was changed for this checkpoint.

Run from MRVN-Radiant, with ARES as a sibling checkout:

```powershell
python tools/respawn/prepare_tf1_baseline.py --remap install/Release/remap.exe --output .local/respawn/phase2-20261114c
python ../ARES/tools/validate_records.py .local/respawn/phase2-20261114c/maps/mp_tf1_baseline.bsp --output .local/respawn/phase2-20261114c/static.json
python tools/respawn/audit_tf1_lumps.py .local/respawn/phase2-20261114c/maps/mp_tf1_baseline.bsp .local/respawn/samples/tf-angel-city/maps/mp_angel_city.bsp .local/respawn/samples/tf-colony/maps/mp_colony.bsp "D:/Games/Titanfall Online/Mods/TFORevive.Core/mod/maps/mp_lobby_02.bsp" --output .local/respawn/phase2-20261114c/lump-audit.json --markdown docs/respawn/RESPAWN_TF1_LUMP_CHECKLIST.md
python ../ARES/harnesses/adapters/tfo_harness.py --game "D:/Games/Titanfall Online" --maps .local/respawn/phase2-20261114c/maps --map mp_tf1_baseline --checks .local/respawn/phase2-20261114c/checks.json --output .local/respawn/phase2-20261114c/tfo-run1 --enable Titanfall1.Content.Client --enable Titanfall1.Content.Shared --timeout 300
```

The first fixture's attempt (`phase2-20261114/tfo-run1`, timeout 120 seconds)
timed out during startup; it had no target-map completion or probe events. Keep
its report as a startup failure, not a collision failure. The longer retry
(`phase2-20261114/tfo-run2`) completed after two pre-map startup crashes/retries:
both brush hulls hit z=0.03125, both patch hulls hit z=128.031, and rays hit
z=0.03125/128. Its brush-ray expectation was incorrectly tighter than the native
0.03125-unit brush contact margin. Its default rocket probe on the small patch
ended on the catch floor at x=665.5625, y=118.59375, near the edge of the patch;
this cannot distinguish falling through from rolling off.

The final fixture (`phase2-20261114c`) corrects the brush-ray tolerance, gives
both teams explicit native spawn entities away from the probes, fixes a test
material prefix and uses crates on a 1024-unit-wide flat patch. The intermediate
`phase2-20261114b` build was static-only; it was superseded before runtime testing.
The original failed report is preserved. Subsequent native results are recorded
below.

## Native result: final fixture, two fresh TFO sessions

Reports: `.local/respawn/phase2-20261114c/tfo-run1/report.json` and
`tfo-run2/report.json` (with copied `tforevive.log` in each directory).
Both sessions loaded the target map, ran every probe and reached DONE without
a script error. Run 1 passed all expectations. **Run 2 failed the brush-crate
height expectation; it is not an all-pass result.**

| Probe | Run 1 Z | Run 2 Z | Interpretation |
| --- | --- | --- | --- |
| Brush ray | 0.03125 | 0.03125 | Expected native brush margin |
| Patch ray | 128 | 128 | Expected flat-patch plane |
| Brush pilot/broad hulls | 0.03125 / 0.03125 | 0.03125 / 0.03125 | Both checks pass |
| Patch pilot/broad hulls | 128.031 / 128.031 | 128.031 / 128.031 | Both checks pass |
| Brush crate | 0.5 | 15.5625 | Repeat outside expected [0, 3] |
| Patch crate | 128.5 | 128.469 | Both within expected [128, 131] |

All four final drop samples report zero linear velocity. In run 2 the brush
crate's origin is (-6.40625, -49.90625, 15.5625), still over the broad brush.
It did not fall through the floor. The harness does not log angles, angular
velocity or contact geometry, so the elevated origin cannot yet distinguish a
tipped resting orientation from an anomalous contact. Do not loosen the
expectation to turn this into a pass. Next physics task: add those measurements
and compare supported model bounds/contact heights, then repeat with a retail
control. This result alone does not reproduce or resolve the older whole-run
fall-through instability.

Verification: **runtime verified for these 12 ray/hull checks; partially verified
for physics** (three of four height expectations pass). This does not establish
curved-patch, backface, projectile-mask, native titan gameplay, water, lighting or
R1Delta parity. Tool checks: four audit tests and 19 record-validator tests pass;
both working trees pass `git diff --check`.

## R1Delta follow-up after EA sign-in

Environment: R1Delta **3.0.5**, installed at
`C:/Users/Tristan/AppData/Local/R1Delta/app-3.0.5`, with the game at
`D:/Games/Titanfall`; ARES adapter commit `4fe8d69`. No existing Titanfall process
was running. The adapter launched and closed only its own game and removed its
temporary addon afterwards.

```powershell
python ../ARES/harnesses/adapters/r1_harness.py --maps .local/respawn/phase2-20261114c/maps --map mp_tf1_baseline --checks .local/respawn/phase2-20261114c/collision-checks.json --output .local/respawn/phase2-20261114c/r1-collision --timeout 180
```

Result: loaded, finished, no errors. All **six ray/hull event strings match
both TFO sessions exactly**, including fraction, end Z, normal and start-solid
status. This is paired-runtime verification of these two surfaces and box
sizes only. Report: `.local/respawn/phase2-20261114c/r1-collision/report.json`.

`collision-checks.json` retains the original traces, hulls and expectations but
omits drops. The generator now emits this file alongside `checks.json`.
R1Delta removes small crate props created by the harness, so the TFO crate test
cannot be reused unchanged. Paired physics testing needs a supported model
(such as the documented barrel control) and its packaged model dependencies.
The TFO crate-height discrepancy remains unresolved. No R1Delta visual,
lighting, water, gameplay or physics acceptance is claimed here.

No game assets are committed. The harness stages its own temporary mod and
restores the enabled-mod configuration. EA/Origin and other game processes are
outside this run's control.

## Development follow-up: compiler and physics controls

The user confirmed Phase 2's scope as **TF1 and TFO**, excluding Northstar and
Apex/R5. Full compatibility remains open.

**Fixed:** unbaked v29 output declared a fallback atlas but omitted its RTL
plane. The new validator catches the mismatch in the original baseline
(0 bytes, expected 262,144). `WriteR1BSPFile` now emits one four-byte, all-255
unshadowed RTL plane per fallback texel, half the two-plane SKY byte count.
This is a layout correction, not RTL channel decoding. The fresh compiler's
fingerprint is recorded in `.local/respawn/phase2-rtl-fixed/build.json`.

**Expanded validation:** eight additional v29 schemas check water, cubemaps,
world lights, lightmap headers, probes, static-prop probe indices, probe trees
and probe references. Added checks cover finite fields, material/probe indices,
tree leaf/child ranges and cycles, lightmap dimensions and SKY/RTL byte counts.
The same implementation is synced into ARES. The original baseline is now
correctly rejected for its missing RTL plane; its earlier static pass reflects
the narrower validator then in use.

**Native controls:** the rebuilt map loads in TFORevive.Core 135 and R1Delta
3.0.5. Each runtime's four-barrel simultaneous run passes all six shared
ray/hull checks, final linear-speed limits and coarse transformed-box support
checks. Those collision events match exactly. R1Delta also passes a four-barrel
sequential run after fixing its previously ignored `drop_sequential` option.
Every body is observed and destroyed before the next spawn, with original
indices preserved. ARES now logs final poses and local model bounds.

**Crate stress result:** eight crates completed in TFO without a fall-through.
Two coarse visual-box support checks failed; both bodies had rolled roughly
90 degrees onto their sides. Using the user's extracted `crate.phy` and its
16 collision vertices, all eight actual physics hull bottoms are 0.36–0.44
units above the correct brush/patch surfaces, with zero final linear velocity.
The PHY is narrower than the visual bounds, explaining this run's 1.2-unit box
overlap. Original failures are retained; no raw bounds tolerance was loosened.
The earlier uninstrumented crate sample remains unclassified, and these runs
do not resolve the older whole-run fall-through instability.

ARES's `physics_observations.py --phy FILE.phy --floor INDEX Z` now checks rigid
single-solid support from recorded poses, with a one-unit plane tolerance and
maximum linear speed 0.1. This is a sampled support check, not friction,
stacking, articulated-body or buoyancy acceptance. Model data stays local.

Evidence under `.local/respawn/phase2-rtl-fixed/`:

- `static.json`, `lump-audit.json`, `expanded-validation.json`: 33 compiled and
  reference v29 maps pass, including five retail TF1 maps and TFO lobby.
- `r1-barrels2/`, `tfo-barrels2/`, `r1-sequential/`: native reports and
  `physics-support.json` analyses pass.
- `tfo-crates8/report.json`: retains two coarse-box failures;
  `tfo-crates8/physics-support.json`: all eight actual PHY support checks pass.
- `unit-all.log`: 231 MRVN tool tests pass. ARES tool/adapter logs record
  154 and 65 passing tests on the rebased ARES branch, respectively. Registry validation passes.
- `.local/respawn/phase2-rtl-regression/results.json`: all 55 compiler
  regression cases pass after rebuilding `remap`.

The remaining gates are water rendering/cells and broader buoyancy, RTL and
character-lighting semantics, unresolved curved/transformed collision,
complete asset packaging, gameplay/navigation, converter targets and paired
release/human acceptance. ARES's `docs/tf1-tfo-compatibility.md` tracks the same
scope for users of its standalone tools.

## Startup and water-reference follow-up: 15 November

The compiler now synthesizes a missing `info_intermission` at an existing pilot
spawn. It prefers `info_spawnpoint_human_start`, then the ordinary human spawn,
then legacy player starts; authored cameras are preserved. Position and angles
are copied, with legacy yaw expanded to three angles. With no located spawn,
the warning remains and no arbitrary location is generated. This fixes the
camera requirement; it does not generate all gameplay spawns/objectives.

Four compiler integration cases cover preferred-spawn selection, preservation
of an authored camera, legacy yaw, and a map with no spawn. All **59** compiler
regression cases pass. A fresh baseline compiled with `--omit-intermission`
loads and starts in R1Delta 3.0.5 and passes its six collision expectations.
Evidence: `.local/respawn/phase2-intermission/r1-autocamera/report.json`, its
source `.map`, compile log and build manifest. The source deliberately lacks
the camera; the emitted BSP contains it.

The v29 validator also checks each cell's signed water-record index: `-1` is
dry and nonnegative indices must name LEAF_WATER_DATA. The expanded corpus
now has **37** compiled/reference maps, all passing. Unit suites pass **232**
MRVN tests and **155** ARES format-tool tests; the ARES adapter suite remains
65 passing tests. Updated logs are under `.local/respawn/phase2-intermission/`.

Water-cell splitting already exists in the opt-in portal path:
`CollapseVisibilityCells` prevents merging across wet/dry boundaries, and
`AssignWaterCells` assigns the emitted cells. The existing convex/sloped-water
compiler cases pass. This closes the status ambiguity about implementation;
underwater rendering/fog and paired buoyancy acceptance remain open.

## Underwater draw and camera follow-up: 15 November

A freshly compiled room now renders submerged world geometry and water fog in
TFO Core 135. Wet-cell world mesh references retain normal rendering and gain
`0x200000` underwater participation; sky and prop references are excluded.
The v29 material writer strips both mesh draw bits from TEXTURE_DATA. All
1,485 surveyed material records across five retail TF1 maps omit these bits.
TF1 shader profiles now emit Water (lit-flat, material flags 0x3008) and
WaterBeneath (unlit, 0x3408, underwater-only and non-solid). Authors must supply
reversed underside geometry explicitly; automatic underside generation is open.

The native TFO probe has floor z=0, water z=128, and held eye heights 252
(above), 76 (submerged), and 76 in an adjacent dry cell. All three captures
were reviewed; geometry and fog render underwater, and dry/above views render.
Two downward traces hit z=0.03125. Evidence and original source remain local:
`.local/respawn/phase2-water/tfo-typed/` and `maps/mp_tf1_water_typed.map`.
No hand edits to the BSP were needed. This is one rectangular-room sample,
not general water acceptance or a buoyancy test.

The same BSP in R1Delta 3.0.5 renders underwater floor/fog, but the upper view
is black and the surface is absent above water. Material availability and
renderer differences need isolation. Its above-water position drifted 2.606
units and correctly failed the one-unit camera check. Keep this raw failure
at `phase2-water/r1-typed/report.json`; paired visual acceptance stays open.
The map also reports missing navigation paths.

ARES now holds requested views against gravity, records origin/eye position,
fails missing captures and excessive origin drift, and requires fresh TFO
captures from the current launch. R1 view holds are token-owned and cancelled
after capture, including errors. Camera checks do not establish pixel parity.

Validation: 232 MRVN tool tests, 155 ARES format tests, 68 adapter tests and
registry validation pass. One initial adapter-suite run hit a Northstar local
connection abort; the full rerun passed. All 60 compiler regression reports
pass, including dry/wet mesh draw checks and exact water shader profiles.
Reproduce with `python tools/respawn/compiler_regression.py --remap
install/Release/remap.exe --work-dir .local/respawn/water-regression`.
Broader buoyancy, R1 water materials, underwater submodels/props, sloped and
multiple-pool rendering, lighting, collision, packaging and release gates remain.

## R1 water controls and capture follow-up (15 November)

Explicit material staging is now available in ARES R1Delta with
`--material-files DIR`: only a local materials/ tree of VMT/VTF files is admitted,
with linked paths and other file types rejected before staging. Owned-addon
cleanup removes these dependencies with the map. This is explicit staging,
not automatic dependency discovery or conversion; no game assets are committed.

A local Angel City VPK control supplied both water VMTs, the normal/flow/noise
textures and HDR cubemap. The two VMTs are byte-identical to the TFO copies.
Supplying these files did not repair the missing R1 water surface/black upper
underwater view. Separate above-only surface and translucent shader controls
also failed to repair rendering. These negative controls do not prove material
loading or general renderer parity; retain the unresolved failure.

Camera drift is now addressed: the fresh local R1 game enables cheats and
uses noclip only for capture, after normal ray/hull/drop checks. It toggles
noclip off in cleanup, including capture errors. Three native origins now
match requests exactly (eye z=252, 76, 76), without loosening the one-unit check.
The raw earlier drift failures remain. Capture success is not visual success:
reviewed water screenshots still show the surface/upper-view problem.

Local reports under MRVN `.local/respawn/phase2-water/`:
`r1-material-control`, `r1-toponly-complete`, `r1-cheat-camera`, `r1-translucent`.
The first above-only control attempts lacked the spawn sidecar; they are setup
failures, not renderer evidence. The complete control includes it.

MRVN now provides `tools/respawn/prepare_tf1_water.py` to reproduce the original
rectangular room, explicit reverse-facing underside, wet/dry cell checks,
shared rays/views and compiler/BSP hashes. It emits the spawn sidecar alongside
the BSP; both must travel together. Fresh generation/static checks and all 232
MRVN tool tests pass; all 70 ARES adapter tests and registry validation pass.
Both READMEs now list TF1/R1Delta with the shared TFO v29 compiler target while
keeping runtime acceptance separate. Full Phase 2 compatibility remains open.

The normal ARES CLI also passes on the fresh generated BSP (no wrapper or BSP
patches): `.local/respawn/phase2-water-repro/r1-native/report.json` records both
rays at z=0.03125 and all three exact camera origins with no errors. All three
screenshots were reviewed; the water surface/upper-view failure persists.

## Water shader isolation and vertex enum (15 November)

The diagnostic room now supports uniquely named runtime materials. R1Delta
3.0.5 renders a magenta top and cyan underside using supplied UnlitGeneric VMTs
and a local VTF. Both rays hit z=0.03125 and all three camera origins match
exactly. This establishes that this owned-addon material tree and these water
surfaces can load and draw; it is not a Water shader acceptance result.

On the same BSP, changing the unique materials to native Water VMTs (including
the unique bottom-material reference and full supplied dependencies) restores
the missing surface/black upper underwater failure. Forcing cheap water and
removing refraction from those VMTs also did not repair it. All three captures
in each run were reviewed. Evidence remains local under
`.local/respawn/phase2-water-shader/{r1-unlit,r1-native-water,r1-cheap-water}`.

A separate structural mismatch was identified in MESHES: all surveyed retail
TF1 lit-flat meshes use vertex-type 1, unlit meshes use 0 and lit-bump meshes
use 2, across Angel City, Colony, Fracture, Lagoon and Relic. The compiler had
lit-flat and unlit reversed. It now serializes the native v29 values while
keeping internal pool/lightmap/tangent selection separate. The water shader
regression checks the bytes. A native R1 control changing only these two bytes
still has the water failure; this correction is not presented as its solution.
The control report is `.local/respawn/phase2-water-vertextype/r1-native`.

`prepare_tf1_water.py --diagnostic-texture LOCAL.vtf` reproduces the diagnostic
with unique names and an explicit material-files tree; no retail VTF is bundled.
Its manifest distinguishes UnlitGeneric diagnostic from retail Water mode.
The generator compiles and validates in either mode. All 232 MRVN unit tests
and all 60 compiler regression reports pass after the enum fix.

The material-sort fourth 16-bit word also matches `max(firstVertex +
lastVertexOffset) - min(firstVertex)` for every referenced sort across those
five retail maps (1,439 sorts). The compiler now writes that unsigned vertex
span and expands it when a sort is reused, within the existing 65,536-vertex
limit. Other BSP versions retain their existing zero word. The integration
fixture checks this relationship. The isolated R1 span control still shows
the water failure, so this is another structural correction, not a water fix.
Evidence: `.local/respawn/phase2-material-span/r1-native/`.

After the enum correction, TFO Core 135 loads the freshly generated room and
passes both rays and all three exact camera positions. Above/dry geometry and
underwater room/fog render in reviewed captures. It needed two pre-load startup
retries. Evidence: `.local/respawn/phase2-vertex-enum-native/tfo/`.

Final rebuilt compiler evidence is under `.local/respawn/phase2-metadata-final/`:
normal and diagnostic generator modes compile and pass static checks; TFO and
R1Delta both pass the two floor rays and all three exact camera positions on
the normal BSP. All captures were reviewed: TFO renders surface and submerged
room/fog; R1 still has the surface/upper-view defect. These are sampled visual
results, not whole-map or whole-runtime acceptance. All 60 final compiler
regression reports pass (`phase2-metadata-final-regression/results.json`).

A retail R1Delta Angel City control at (-8000, 8000), above the water at eye
z=188, renders the native water surface. Thus the R1 installation can draw that
shader. The attempted submerged control is invalid: the pilot died, eye height
changed to 14 and the screenshot shows a death camera despite its logged server
origin matching. Do not count that screenshot as underwater evidence. The raw
report is retained at `.local/respawn/phase2-water-retail/r1/report.json`; the
separate `capture-audit.json` rejects the old markers without alive state.

ARES now records `alive` in both runtime view markers and requires exactly one
`alive=true` pose plus finite origin/eye coordinates. Correct server origin alone
no longer satisfies a view after death. The 70-test adapter suite covers dead,
missing-state and nonfinite-eye rejection and passes. This does not prove frame
synchronization or spectator-camera parity; visual review remains mandatory.

Final alive-state harness runs pass on this same rebuilt BSP in both runtimes:
`.local/respawn/phase2-metadata-final/{r1-alive,tfo-alive}/report.json`. Each has
two floor rays at z=0.03125, three exact camera origins and alive=true at every
pose. All six screenshots were reviewed: the TFO sample renders correctly,
while the R1 water defect persists. No render acceptance is inferred from the
zero-error harness status alone.

## Buoyancy and motion follow-up (16 November)

R1Delta controls clearing wet-cell flags, filling mesh lightmap metadata, and
rendering only a planar water top did not repair the native Water surface/upper
underwater view. Each control passed static validation, both floor rays and
three exact alive-state camera poses. All screenshots were reviewed. The
cell-flags capture includes a Discord overlay in a corner; the same central
water failure remains visible. These are experimental negative controls, not
production compiler changes. Local evidence: `phase2-cell-flags/r1`,
`phase2-mesh-luxels/r1`, and `phase2-planar-water/r1` under `.local/respawn/`.

The unmodified compiled water room now has a paired wet/dry buoyancy sample in
R1Delta 3.0.5 and TFO Core 135. A large cardboard box spawns as a real physics
prop in both runtimes. The wet endpoint is near water z=128 (origin 137.094 in
R1 and 132.875 in TFO); the dry endpoint is z=0.5 in both. Two floor rays hit
z=0.03125. Native PHY projection puts both dry collision bottoms at z=0.458,
within the one-unit support tolerance. These are single runs and qualitative
flotation evidence, not synchronized trajectories or broad buoyancy acceptance.
No views or capture noclip mode run during these physics probes.

The wet boxes keep bobbing. Tail-window translation is about 22.44 units in R1
and 21.70 in TFO while the entity-reported velocity remains zero. Dry sampled
translation is zero. Earlier barrel controls also show positional motion with
zero velocity; the metal barrel sinks and is not a reliable floating probe.
Thus `drop_speed` retains its entity-velocity meaning but cannot alone establish
VPhysics rest. Historical raw reports remain unchanged. Motion failures are
retained alongside separate dry-only support/motion analyses.

ARES now honors `drop_samples` for sequential TFO drops and adds sampled-motion
diagnostics independent of entity velocity. `physics_observations.py --motion
INDEX --motion-window 2 --max-translation 0.25` requires a full tail window and
checks maximum pairwise translation. Missing/invalid/nonfinite or duplicate/
out-of-order samples fail requested checks. Position ranges and interval-average
speeds remain diagnostic. This does not measure angular rest, between-sample
events or instantaneous body velocity; the adapters use different time clocks.

Evidence: `.local/respawn/phase2-buoyancy-paired/` has shared barrel/cardboard
checks and native `r1`, `tfo`, `r1-cardboard`, `tfo-cardboard` reports. Both
cardboard `translation.json` analyses fail the wet motionless criterion;
`dry-support-motion.json` passes only dry support and sampled positional rest.
No raw report or tolerance was altered to hide those failures. Supplied models,
PHYs and account-bearing logs remain local.

`prepare_tf1_water.py` now emits separate `buoyancy-checks.json` with the
cardboard model, sequential samples and coarse wet/dry height expectations.
Fresh generation compiles and validates. The shared checks' height ranges pass
against both recorded runs; this is one reproducible sample, not a release gate
closure. Root READMEs and harness guides reflect this limitation. Validation:
232 MRVN tests, 73 ARES adapter tests and registry validation pass. Compiler
code was unchanged in this follow-up; the existing checkpoint has 60 passing
compiler regression reports. Full Phase 2 compatibility remains open.

The regenerated fixture has identical referenced lump payloads to the BSP used in the paired runs. Its whole-file hash differs in unreferenced padding bytes; byte-for-byte reproducibility is not claimed. `paired-summary.json` records both comparisons.


## 16 November: transformed collision, masks and water resource isolation

`prepare_tf1_transforms.py` builds five translated/rotated brush or flat-patch
submodels with analytic plane normals. It checks five front rays and fifteen
world-axis hull sweeps (small cube, pilot and broad box); patches add five
backface rays that must miss. The final brush generator passes all 20 checks
in R1Delta 3.0.5 and TFORevive.Core 135 (`phase2-transform-repro-brush`). The final flat-patch fixture passes 25 collision checks in TFO
(`phase2-transform-repro-patch/tfo-collision`); earlier equivalent fixtures
passed 25 checks in both runtimes. This is sampled
geometry coverage, not actual titan movement or fired-projectile acceptance.

ARES accepts optional per-row `trace_masks` and `hull_masks`: `playersolid`
(default), `solid`, `shot`, `water`. Unknown names, non-string entries and row
count mismatches fail before staging. `prepare_tf1_masks.py` builds four columns
with explicit solid/playerclip/bulletclip/water contents. Its corrected TFO run
passes 16 rays and 16 small hulls, including excluded-column and complete-miss
controls (`phase2-mask-matrix-corrected/tfo`). The first failed run is retained:
its oracle used the wrong bulletclip bit and its water shader failed to clear
solid contents. No compiler change was needed. R1 mask-specific native testing,
patch masks, actual projectiles and gameplay titans remain open.

Cold R1 custom-water loading with the full native Angel City map VPK set aliased
to the custom map name renders the surface and underside. Loading retail Angel
City water before the same custom BSP also renders them. Both retain a black
underwater band. These are diagnostic controls, not redistributable packages or
water acceptance. A water-only filtered native directory VPK does not reproduce
the full set's visible result, but its captures are obscured by an EA offline
popup and remain inconclusive. Resources, account-bearing logs and captures stay
local (`phase2-water-map-vpk`, `phase2-water-retail-warm`,
`phase2-water-minimal-vpk`). Task-owned VPK aliases were cleaned up.

The user requested internal game screenshots to avoid desktop popup contamination.
Both engine JPEG and standard screenshot attempts crashed TFO at capture time;
retain those reports separately from successful collision events. Experimental
`engine_screenshots: true` is opt-in, with fresh uniquely named image collection
and an explicit `capture_methods` report. Default window captures remain
labeled fallbacks; R1 internal capture is unverified. A successful capture alone
is not visual acceptance.

Validation at this checkpoint: 234 MRVN tests, 76 ARES adapter tests and registry
validation pass. No game assets are committed. Full Phase 2 remains open for
water, broader collision/physics and lighting, dependency packaging,
mode/objective/navigation behavior and the documented human match gates.


Water dependency follow-up: retaining the native Water material/texture assets
and adding only `shaders/fxc/water_ps40.vcs` and `water_vs40.vcs` to the filtered
map VPK restores the top and underside on a cold R1Delta 3.0.5 launch
(`phase2-water-shader-vpk`). All three fresh captures came from the engine's
`screenshot` command (`capture_methods: engine`), with valid alive camera poses
and no desktop popup. The underwater black band remains. R1 now prefers engine
captures by default; TFO's crashing engine path remains opt-in. No retail shader
bytes are committed or redistributed. Water parity and standalone packaging
are still open; the missing compiled shader dependency is now isolated.


The shader dependency is reproducible without copying a retail map archive.
An uncompressed shader-only map VPK made by `pack_vpk.pack_files`, containing
just the supplied Water vertex/pixel caches, restores the same cold R1 surfaces
with loose materials (`phase2-water-authored-vpk`). Loose shader copies alone
fail (`phase2-water-loose-shaders`); both sets have three reviewed engine
captures and valid poses. This isolates the VPK shader-loading requirement.
`pack_tf1_shaders.py --source EXPLICIT_TREE --map mp_name --output NEW_DIR`
packages only `shaders/fxc/*.vcs`, rejects linked/unrelated files and records
member/archive hashes. Its final output is byte-identical to the native-tested
pair of VPKs. This packages supplied caches; it neither compiles shaders nor
includes retail bytes. Material/model dependency discovery, the underwater band
and complete authored/converted-map release packages remain open.


The final mask generator also passes all 32 checks in a fresh R1Delta run
(`phase2-mask-repro-final/r1`), paired with the final TFO generator run.
Both engine constants and solid/playerclip/bulletclip/water inclusion and
exclusion are now sampled in both runtimes. Actual projectile/gameplay-titan
acceptance is still separate. Current MRVN suite: 236 tests pass.


Final transformed flat-patch R1 run also passes all 25 collision checks
(`phase2-transform-repro-patch/r1`). The final brush, flat-patch and mask
fixtures therefore pass 77 probes per runtime (20 + 25 + 32). This closes only
these sampled collision cases, not curved-patch, gameplay or release gates.


## CSM structure, entity-sidecar preflight and water controls (16 November)

The v29 CSM_AABB_NODES (32-byte) and CSM_OBJ_REFERENCES (2-byte) schemas
raise writer-schema coverage to 54 of 70 types. Validation checks finite ordered
node bounds, child/reference ranges, local-versus-total reference counts and
tree cycles. Object IDs remain opaque: no claim is made about their shadow-mesh
namespace, cascade semantics or lighting appearance. Six local TF1 references
(Angel City, beta Angel City, Colony, Fracture, Lagoon, Relic), the installed TFO
lobby and the authored water fixture pass. The four-map lump inventory was
regenerated. Two old lighting fixtures still fail the pre-existing missing RTL
plane check; their reports are retained rather than treated as passes. Fresh
compiler regression produces 60 passing reports, including nonempty lit cases.
Evidence: `.local/respawn/phase2-csm-validation` and `phase2-csm-regression`.

The Water shader package and internal R1 captures were retained for three
negative controls: top-only Water faces (`phase2-water-planar-shader`), solid
banks (`phase2-water-basin/r1`) and underwater draw flags on every above-water
world mesh (`phase2-water-all-draw/r1-with-sidecar`). All finish with valid alive
poses, two expected floor rays and three reviewed engine screenshots. The black
band remains in every underwater view. No broad compiler flag change is made.
`prepare_tf1_water.py --basin` reproduces the contained-pool control while
preserving the original exposed-edge fixture as the default. TFO basin runtime
has not been tested.

The first draw-flag control omitted the generated spawn `.ent` sidecar and
remained on the loading screen. A second incomplete control was stopped by
matching its task-owned parent process. These are setup failures, not draw-flag
results. The complete rerun passes startup and retains the band. Both adapters
now check embedded v29 `01*` ENTITY_PARTITIONS declarations before staging and
reject missing, empty or linked named sidecars. Malformed paths/payload ranges
fail; other BSP versions and external partition-table overrides are outside
this narrow check. This does not validate entity syntax, objectives or modes.

Validation: 238 MRVN tool tests, 157 ARES format-tool tests, 81 adapter tests,
60 fresh compiler regression reports and registry validation pass. No retail
assets or account-bearing logs are committed. Water parity, lighting semantics,
complete dependency packages, gameplay/navigation and human release gates keep
Phase 2 open.


## Flooded-room comparison and bounded Water dependency audit (17 November)

`prepare_tf1_water.py --flooded` extends the water brush and reverse-facing
underside to all four room walls, with water at z=0..128. It validates both wet
floor regions and the dry air above them, moves spawns above water and omits the
wet/dry buoyancy checks because no dry floor remains. `--basin` and `--flooded`
are mutually exclusive, including the Python entry point. Default, basin and
flooded outputs compile and pass record/cell validation. The regenerated basin
source matches the previous native control. Compiler code is unchanged.

The same flooded BSP and checks finish in R1Delta 3.0.5 and TFORevive.Core 135:
two floor rays end at z=0.03125; all three exact camera origins have finite eye
coordinates and alive=true. The underwater eye is (-256,-320,76). All nine
images from these three runs were reviewed:

| Control | Captures | Underwater observation |
| --- | --- | --- |
| Flooded room, R1Delta | Three internal engine captures | Black band remains |
| Same BSP, TFO | Three window-fallback captures, unobscured | No black band in sampled view |
| Same BSP, R1Delta; supplied underside VMT `$refractamount` .2 to 0 | Three internal engine captures | Black band remains |

R1 runs retain the native-tested shader-only VPK and loose material tree. The
last control changes only the supplied underside VMT; no claim is made that this
parameter alone explains all renderer refraction behavior. TFO uses its installed
TF1 content mods and needed one normal startup retry. Its engine capture remains
disabled following prior crashes. Runtime/shader/resource differences remain
possible causes; the comparison does not justify a speculative compiler change.
The navigation warning remains visible: navigation acceptance is still open.
Evidence stays local in `phase2-water-flooded/{r1,tfo}`, its `layout-validation.json`,
and `phase2-water-zero-refract/{control.json,r1}`.

`audit_tf1_water.py` now checks the known direct Water VMT dependency path before
packaging: bottom materials, known textures, HDR-only cubemaps, runtime targets
and the two required compiled Water caches. It fingerprints supplied files,
checks VTF magic and nonempty resources, and rejects unsafe paths, links and
unsupported dependency syntax. Eight original synthetic tests cover missing
files, malformed syntax, unknown dependency parameters/proxies and bounded cycles.
The local native-tested set passes with two VMTs, four VTFs and two VCS caches
(`phase2-water-flooded/dependencies.json`). Patch/include materials, conditional
blocks and other shaders/proxies are unsupported; texture/cache decoding,
mounted archives, other asset classes and complete map dependency closure remain
open. Loose cache presence alone is not the required native VPK load path.

Validation: 246 MRVN tool tests pass; all three generator layouts compile and
pass static checks; the two R1 and one TFO runs above finish without probe or
capture errors. Prior paired collision and 60-report compiler results remain
the earlier checkpoint, not fresh runs for this change. Task-owned addons/VPK
aliases are cleaned up. Retail files, account-bearing logs and screenshots
remain local. Full Phase 2 is still open for R1 underwater rendering, broader
lighting/physics, complete dependency packages, gameplay/navigation and human
release gates.


## Retail underwater reference and geometry/raw-lump checks (17 November)

A fresh retail Angel City run now has three exact, alive poses and three
internal engine screenshots. Camera-only `god`/`SetInvulnerable` protection
prevents the retail damage volume from turning this into a death-camera test;
this is not gameplay acceptance. Cell traversal confirms two eyes at z=-80
are in native water cells (surface z=26); the first eye is in a dry cell and is
retained as a control. At (-8000,8000,-80), the native retail view also shows a
dark horizontal horizon strip. The other wet view has a broad pale horizontal
region. All images were reviewed. This establishes that horizon artifacts are
not unique to remap-authored BSPs, without asserting equal severity or a fixed
renderer cause. No speculative compiler/material workaround is applied.
Evidence: `phase2-water-retail-alive/{report.json,camera-protection.json,cell-audit.json}`.

Six more v29 geometry schemas cover occlusion vertices/indices, opaque and
alpha shadow vertices, shadow indices and 12-byte shadow meshes. Checks reject
nonfinite positions/UVs, incomplete occlusion triangles, invalid opaque selectors,
material references and out-of-pool mesh-local shadow indices. Cumulative shadow
triangle ranges must consume the index stream. The later v29 CSM range check
bounds prop IDs against `LEVEL_INFO`; these checks do not prove cascade or
shadow appearance semantics.

A seventh schema covers texture string-table offsets. Validation rejects
out-of-range/interior/empty/unterminated names and texture-data name indices
outside the table. Raw PHYSICS_COLLIDE framing now bounds every model payload,
solid length/count and keydata string, checks model indices/duplicates and VPHY
signatures, and requires the exact terminal header without trailing bytes.
It does not decode IVP trees, fluid keydata semantics or PHYSICS_TRIANGLES.
Raw payload readers prefer the default sidecar and reject oversized, encoded or
unknown-version payloads. Writer schema coverage is now 61/70, not a parity score.

All six TF1 references, the installed TFO lobby and the authored audit baseline
pass the expanded validator. The four-map checklist is regenerated. The tool
suite passes 255 tests. The fresh shadow-check compiler run has 60 passing
regression reports; its generated v29/v37 maps are also checked with the final
raw-lump validator. Apex records are explicitly outside this validator. ARES
receives the same implementation and tests: 166 format tests, 81 adapter tests
and registry validation pass. These structural checks leave native lighting,
physics stress, complete dependencies, modes/objectives/navigation and human
match gates open.


## Entity partitions and native touch outputs (17 November)

A shared original entity reader now validates embedded KeyValues and every
required `ENTITIES01` partition, preserving duplicate output keys and literal
path separators. It rejects malformed blocks/headers, data after a NUL
terminator, unsafe or duplicate (including Windows case aliases) partition
names, and missing/empty/linked/oversized files. Both runtime preflights honor
the default external `.0018.bsp_lump` partition declaration. A client variant
is not silently substituted for the default declaration.

All six TF1 references pass with their five declared partitions. Expanded
validation also passes 61 generated v29/v37 maps, the TFO lobby and the original
trigger fixture; the Apex fixture is outside the v29/v37 validator and excluded.
The unchanged mask fixture passes a fresh native run in each runtime: 16 rays
and 16 hulls apiece, loaded and finished without errors. Local evidence:
`phase2-entity-reference-validation.json`, `phase2-entity-generated-validation.json`
and `phase2-entity-native/{r1,tfo}/report.json`.

ARES now accepts bounded `triggers` checks in both adapters. Each check names
an authored trigger and provides player positions and exact cumulative start/end
touch counts. Every sampled result must be unique, alive, finite and near its
requested position. Missing outputs, targets or samples fail the check. R1's
MCP setup is guarded against duplicate execution after a control-call timeout.
The original axis-aligned `trigger_multiple` fires exactly one `OnStartTouch`
and one `OnEndTouch` in both runtimes. This uses controlled repositioning;
it does not establish walking, networking or objective behavior. Evidence:
`phase2-trigger/reusable-{r1,tfo}/report.json`.

The MRVN tool suite passes 261 tests; ARES passes 172 format tests and 95
adapter tests plus registry validation. Entity syntax and sampled touch output
checks leave full Phase 2 open: broader rendering/lighting, collision/physics
stress, complete asset packages, modes/objectives, AI navigation and human-match
release acceptance still require native evidence.


The model-local rotated fixture also passes in both runtimes: a narrow brush
translated to (400,200,0) and yawed 45 degrees receives one enter and one exit;
a point across its narrow axis remains outside. The initial diagnostic fixture
incorrectly combined world-space brush coordinates with an explicit entity
origin and correctly failed its expected touch counts. Correcting the fixture
to model-local coordinates resolved it without a compiler change. Both local
reports are retained (`phase2-triggers-transformed` for the failed setup,
`phase2-triggers-local/{r1,tfo}` for the corrected control).


A final fresh run uses the public `spawn_probe` option before any harness
repositioning and checks both original triggers. Both R1Delta 3.0.5 and TFORevive
Core135 spawn a living team-2 player at (-400,0,0.03125), within two units of
the authored origin. All six trigger samples then match exact touch counts and
poses. Both reports load, finish and contain zero errors. This validates one
initial spawn, not team-3 selection, respawns or every mode's spawn logic.
Evidence: `phase2-spawn-triggers/{manifest.json,static.json,checks.json,r1/report.json,tfo/report.json}`.
Commands: `python tools/respawn/prepare_tf1_triggers.py --remap install/Release/remap.exe --output .local/respawn/phase2-spawn-triggers`,
then each ARES adapter with `--maps` set to that directory's `maps`,
`--map mp_tf1_triggers --checks` set to its `checks.json`; TFO additionally uses
`--game D:/Games/Titanfall Online --enable Titanfall1.Content.Client --enable Titanfall1.Content.Shared`.
No view captures were requested for these output/pose checks. Game files,
screenshots and account-bearing logs remain local; owned runtime staging is
removed after each run.


## Native atlas NPC support (17 November)

The authored floor now also supports a real native atlas NPC in both runtimes,
not just a broad trace hull. Each local control creates an alive `npc_titan` at
(0,500,256); at all five one-second samples its origin is (0,500,0.03125),
velocity is zero and native bounds are (-60,-60,0)..(60,60,235). Sampled
translation is zero and the bounds bottom remains at the native floor margin.
This is one flat-floor support test, not piloting, combat, navigation, curved
surface acceptance or a proof of rest between samples.

There is a material runtime API difference: R1Delta 3.0.5 uses the player setting
`titan_atlas`, whereas the TFORevive Core135 native helper uses
`titan_atlas_tier0`. Passing the TFO setting to R1Delta produced a null-model
script error at `SpawnNPCTitan`/`SetModel`. Both failed R1 attempts are retained;
the corrected R1 atlas control and TFO control pass without a compiler change.
Evidence: `phase2-titan-native/{r1,r1-template,r1-atlas,tfo}/report.json`.

ARES now exposes bounded `titans` checks with per-runtime settings, exact sample
counts, alive/native state, finite bounds, expected XY and floor support, and
independent sampled-translation checks. It destroys each NPC after sampling or
a caught script failure; R1 thread startup is guarded against control retries.
`prepare_tf1_triggers.py --titans` adds the original support probe. ARES's
adapter suite passes 102 tests; MRVN's 261 tests and ARES's 172 format tests
remain passing. Full Phase 2 acceptance is still open.


The public adapters also pass a final paired combined run of this source fixture:
initial spawn, five native atlas support samples and all six trigger samples,
with zero report errors. TFO required one normal pre-map graphics retry; the
second launch loaded and finished. Evidence:
`phase2-titan-public/{manifest.json,static.json,checks.json,r1/report.json,tfo/report.json}`.
Command: prepare with `--titans`, then the same public adapter arguments used
for `phase2-spawn-triggers`, pointing to `phase2-titan-public` instead. No visual
or navigation acceptance is inferred from these pose/output results.


## Standing traversal through an authored trigger (17 November)

An additional local diagnostic uses actual forward input after one initial
placement at (-300,0,1), with no per-sample teleporting or velocity injection.
R1 sends `+forward` through its owned MCP console and releases it in Python's
`finally`; TFO sends the same input through `ClientCommand` and releases it
after its guarded sampling loop. Both runtimes sample an alive, standing
(`IsCrouched=false`) pilot 16 times. All samples remain on y=0, z=0.03125;
reported forward velocity is about 172. Each sequence begins outside, fires
one `OnStartTouch`, then one `OnEndTouch` and ends outside the trigger.

The final sampled X positions are 280.982635 (R1) and 231.608826 (TFO). These
are not an equal-duration speed comparison: R1's host polling includes MCP
round trips, whereas TFO waits 0.2 engine seconds between samples. The bounded
local audit requires finite, ordered samples, a living standing player, the
floor/axis/speed constraints, positive progress and exactly one enter/exit.
It passes both final runs and records source-script and report SHA-256 hashes.
Evidence: `phase2-trigger-walk/{r1-long,tfo-long}/report.json` and `walk-audit.json`.
The short TFO run ended inside the contact volume (no exit), so it is not counted
as a full crossing. An initial TFO script used invalid `wait .2` syntax; that
failed control is retained and was corrected to `wait 0.2`. Only the owned failed
game process was stopped; harness staging cleanup completed before the retry.

This is an ad-hoc native diagnostic, not a new public ARES walking option. The
public `triggers` option still uses controlled repositioning. One straight,
flat-floor crossing does not validate ramps, jumps, obstacles, surf-stage crouch
resets, every movement mode, networking or AI navigation. These and the wider
Phase 2 gates remain open.


## Explicit Hardpoint initialization and TFO compatibility (17 November)

`prepare_tf1_objectives.py` now builds an original three-point Hardpoint room,
with four assault points per terminal, linked brush triggers, pilot and droppod
spawns, a floor trace and shared mode/spawn checks. The final source passes in
R1Delta 3.0.5 and TFORevive Core135: both report `cp` in GameRules and GAMETYPE,
three initialized native hardpoints with unique IDs 0..2, valid terminals, a
living pilot at the authored spawn and the expected floor margin. Evidence:
`phase2-cp-final/{manifest.json,static.json,checks.json,r1/report.json,tfo/report.json}`.
This is initialization, not capture, scoring, AI navigation or match acceptance.

TFO requires explicit temporary compatibility interventions. Unpatched authored
and retail Colony launch controls both fail duplicate Hardpoint conversation
registration. The bounded `tfo_cp_dialogue_compat` transform adds CP to the legacy
dialogue switch and limits five MFDP-only voice registrations to their own mode.
Those conversations are referenced by the MFDP mode, not CP. The helper does
not disable dialogue assertions. Reports identify the intervention and hash both
the installed source and staged result. Unsupported/already-fixed routing fails
closed. Installed Core files remain unchanged.

The supplied Hardpoint sound definitions also contain a commented closing brace
inside `diag_hp_mcor_bish_generalpurpose_02`, leaving later aliases nested in an
unfinished block. A strict bounded KeyValues reader detects it. The optional
`--sound-file LOCAL_AUDIO/mp_hardpoints.txt --repair-hardpoint-sound` path repairs
only that known brace in the owned temporary mod. Unknown faults fail validation;
the source file is never edited. The repaired file has 592 aliases, 627 wave
references and 513 unique wave paths. These are definition counts, not playback
or complete audio-package verification. No sound definitions or wave assets are
bundled in the repository.

A client alias diagnostic checks 162 literal names in the supplied TFO CP
script: 156 exist in R1Delta and 42 in unmodified TFO; all 42 overlap. Six names
absent in both are VDU whitelist references, so the literal list is not itself
a complete set of required radio aliases. The repaired TFO definitions restore
the sampled previously missing Hardpoint aliases. Adding an MFDP definition file
does not resolve its unrelated missing alias; mode-specific registration avoids
making CP depend on that other mode. MFDP acceptance remains open. Evidence:
`phase2-cp-aliases/alias-audit.json`, `phase2-cp-sound-alias-check/tfo/report.json`
and the retained failed controls under `phase2-cp-*`.

The final TFO report labels both the dialogue transform and supplied/repaired
sound definitions. Core's source hash remains unchanged after cleanup. Its
passing result is a compatibility-assisted run, not unmodified-Core acceptance.
TFO script errors now stop promptly and do not trigger graphics-startup retries.
R1 caches mode observations before printing to prevent delayed MCP retries from
producing duplicate sets; the failed duplicate-output control is retained.

Validation: 261 MRVN tool tests, 172 ARES format tests and 127 adapter tests pass,
plus registry validation. Run the public R1 adapter with the generated checks.
For TFO, add `tfo_cp_dialogue_compat:true` to a separate checks copy and the sound
source/repair options above, plus the usual Client/Shared content modules.
The native R1 mode observations establish server initialization; no complete
client-console-error, dialogue playback or visual acceptance is inferred.


## Natural Hardpoint capture and scoring (17 November)

The public `cp_capture` sampler now passes the same final fixture in R1Delta
and compatibility-assisted TFO. Both matches naturally reach Playing (state 4).
The target begins neutral with zero progress and team score. After one initial
player placement, ownership changes to the player's team at about ten seconds;
all ten samples show a living player in native trigger contact. The last sample
has team-2 ownership, progress -1 and five earned team points in both runs. A
preceding TFO control also verifies team-3 ownership/progress +1 and five points.
No match-state, ownership, progress or score setter is used. Native player origin
settles at (-600,-90,0.575566), near the terminal, within the declared tolerance.

The shared verifier rejects missing/duplicate/dead/outside samples, wrong capture
direction, non-neutral starts, lost ownership during the hold, decreasing scores
and insufficient final score gain. It waits for natural Playing rather than
forcing the lobby/intro state. R1's server-thread sampler is token-guarded; TFO
reports its explicit temporary dialogue and sound-definition interventions.
Evidence: `phase2-cp-capture-public/{manifest.json,static.json,checks.json,r1/report.json,tfo/report.json}`.
The earlier direct controls remain under `phase2-cp-capture/{r1,tfo}`.

Prepare with `prepare_tf1_objectives.py --capture`, then use the public adapters
and the same TFO compatibility/sound options described above. The adapter suite
passes 136 tests; this change does not alter the 261 MRVN or 172 ARES format-test
baseline. Registry validation passes. This closes one neutral-point capture/hold
sample, not every objective/mode: contested points, recapture, respawns, AI,
networking, full audio/visual verification and human-match release gates remain
open. Full Phase 2 parity is still not complete.


### 17 November: original AI graph build and route controls (open)

`tools/respawn/prepare_tf1_navigation.py` now compiles an asset-free geometry/node
fixture with an original floor, central pillar, eight `info_node` entities,
team pilot spawns, and separate NPC start/goal positions on opposite sides of
the pillar. It writes compile/static reports, source/compiler/BSP hashes and
layout metadata. It generates no AIN and does not claim navigation acceptance.
Reproduction from the repository root:

```powershell
python tools/respawn/prepare_tf1_navigation.py --remap install/Release/remap.exe --output .local/respawn/navigation-new
```

The public generator compiled `mp_ares_nav_9bf00b39` with no structural issues.
All 261 MRVN tool tests pass. Earlier native controls use the equivalent original
`mp_ares_nav_b19c8107` fixture under `.local/respawn/phase2-navigation`.
R1Delta 3.0.5 consumes the eight node entities into its native network; TFO
Core135 does too. Initial neighbor queries return only the starting node and
neither raw assault goals nor `SendAIToAssaultPoint` move the grunt in the
recorded 20 one-second samples. `ai_rebuild_graph` does not resolve that gate.
The native neighbor-query maximum is 32; an earlier request for 500 is retained
as a diagnostic API error rather than a routing failure.

The installed R1Delta binary exposes `updateain`. The non-legacy command was
invoked on the owned fixture with an explicit, new local output filename.
Unlike the older rebuild command, it makes all eight nodes reachable through
`GetNeighborNodes(0,32,HULL_HUMAN)`, but then prints:

```text
buildain: failed to create unknown-node-tail record for node 0.
```

No graph is exported. This is a partially mutated in-memory graph, not a
successful native build. The grunt remains alive at `(-400,0,0.03125)` for all
20 samples. A repeat captures the builder error immediately, avoiding the
MCP console's last-50-lines limit. A further 12-sample control explicitly enables
NPCs and disables movement-start animations; it also remains stationary.
Evidence: `r1-native-updateain`, `r1-native-updateain-diagnostic` and
`r1-native-enabled` beneath the private fixture directory. Their generic harness
`finished=true`/empty error lists indicate only script completion: these scratch
probes do not contain navigation assertions, and their observations fail the
intended route gate. No navigation success is inferred from those fields.

Installed graphs and original source scripts were not replaced. The failed
full builder is not added to the public adapter. The matching TFO `tfo-enabled` control also stays alive and stationary for all
12 samples with NPCs enabled and movement starts disabled; its neighbor query
still returns only node zero. No graph or routing acceptance is inferred.

Native export, valid graph
header/CRC loading in both runtimes, actual obstacle routing, broader hulls and
release acceptance remain open. No AIN sidecar packaging is advertised yet.


### 17 November: initialized AIN export and paired grunt route

The earlier `updateain` failure has a concrete launch prerequisite. Local source
inspection at R1Delta commit `c48f0003cddc5ba3af99baa415cb5b885764f84f`
shows the delayed-init hook is installed only with one of the AIN launch flags.
That hook initializes the globals used by the builder. No upstream implementation
was copied or installed binary patched. The private control launches with
`-r1delta_build_ain_no_existing`, then calls non-legacy `updateain` with a fresh
absolute output path on the owned map. It exports a 949-byte v54 AIN with eight
nodes, 14 links, three unknown-node-tail records, three unknown-link-tail records,
map revision 6 and script version 19. The original exporter CRC is zero.

The in-memory post-build grunt still does not move; loading the exported graph
on a fresh launch does. Both runtimes route a living native grunt from
`(-400,0,1)` around the pillar to `(400,0,0.03125)` by the fifth one-second sample,
then hold that position through sample 11. Neighbor queries return all eight
nodes. These are native assault goals, with no per-sample NPC repositioning.
The explicit controls enable NPCs and disable movement-start animations and
squad following. Those controls do not certify default AI/animation behavior.

A read-only diagnostic of the owned R1 process's native validation state finds
expected CRC `4285011719` against exporter CRC zero. A private copy receives that
expected CRC, with all other bytes unchanged; another fresh R1 load confirms
file CRC equals computed CRC and repeats the route. No validation check is
disabled. TFO routes using the same corrected file, although its internal CRC
comparison was not separately instrumented. A general offline entity-CRC
algorithm/export workflow is still unresolved. Do not turn this map-specific
native diagnostic into a general CRC acceptance claim.

Original graph SHA256:
`c2acf9a71746213c019365a9ceeb0ac0805ae323a91d38fb9abd11a059288cfe`.
CRC-matched private graph SHA256:
`a5dad15cd8668ac422eeff301e962eed6b2176ad192f4a3dcccfd0d4581b396c`.
Evidence is beneath `.local/respawn/phase2-navigation`: `r1-native-initialized`,
`r1-graph-zero-crc`, `r1-graph-matched-crc`, `tfo-graph-zero-crc`,
`tfo-graph-matched-crc`, and `r1-public-graph-staging`. The TFO matched-file run
retains one startup crash/retry; the successful attempt is the route observation.

ARES now stages the exact optional `maps/graphs/<map>.ain` into the owned R1
addon and preflights matching graph framing in both runtimes. Limits cover file
size, v54 header/map revision, node counts and finite geometry, link counts and
valid unique endpoints. This is deliberately not full tail/script/CRC semantic
validation. Original malformed/truncated graph tests reject before addon mutation.

The new shared `navigation_probe` API and generated fixture `checks.json` make
the route repeatable with supplied graph data. It requires an alive initial pose,
expected node count and connected neighbors, exactly one valid living sample
per index, floor height within two units, optional sampled forbidden-volume
exclusion and final two samples within the goal radius. It rejects stationary,
dead, malformed, missing/duplicate, wrong-floor and obstacle-intersecting samples.
The R1 asynchronous setup is token-guarded against delayed MCP retries.
The fixture generator still generates no graph and labels compilation structural.

This closes one sampled human-hull obstacle route only. Continuous swept
collision, other NPC hulls, dynamic/repeated routes, combat, animations and
complete navigation/export acceptance remain open alongside the broader Phase 2
gates. Private graphs, screenshots, logs and diagnostic scripts stay ignored.


Final public API runs both pass with `loaded=true`, `finished=true`, and no
navigation errors: `r1-public-api/report.json` and `tfo-public-api/report.json`.
Commands (run sequentially from MRVN-Radiant):

```powershell
python ../ARES/harnesses/adapters/r1_harness.py --maps .local/respawn/phase2-navigation/maps --map mp_ares_nav_b19c8107 --checks .local/respawn/phase2-navigation/checks-public.json --output .local/respawn/phase2-navigation/r1-public-api
python ../ARES/harnesses/adapters/tfo_harness.py --game "D:/Games/Titanfall Online" --maps .local/respawn/phase2-navigation/maps --map mp_ares_nav_b19c8107 --checks .local/respawn/phase2-navigation/checks-public.json --output .local/respawn/phase2-navigation/tfo-public-api --enable Titanfall1.Content.Client --enable Titanfall1.Content.Shared
```

At this checkpoint, 261 MRVN tool tests, 172 ARES format tests, 151 ARES adapter
tests, registry validation and skill-mirror validation pass. The fixture generator
also compiles again with emitted navigation checks and no structural issues.


### 17 November: repeatable native export and offline CRC packaging

The earlier map-specific CRC preparation limit now has a bounded implementation:
`tf1_navigation_crc.py` reproduces physical-lump-order map CRC and selected-
entity updates. `build_tf1_navigation.py` exports through an owned R1 session
with explicit initialization, then creates a new CRC-adjusted package. Actual
runtime hashes are pinned before staging. Source graphs and installed binaries
are not overwritten; unsupported layouts/text and existing outputs fail.

The original offline base/entity CRCs 2011031715/4285011719 match a fresh R1
process. Changed fixture `mp_ares_nav_64d4ee22` widens the pillar to
(-80,-160)..(80,160) and moves three southern nodes to y=-288. The public exporter
builds its 949-byte v54 graph with eight nodes and 14 links. Offline base/entity
CRCs are 2027006736/1916430116. Independent owned R1 and TFO observations confirm
file CRC equals expected CRC 1916430116 and computed flag 1. Integrity checks
were not disabled.

Original and variant packages each pass both runtimes' shared route probe:
12 living samples, valid floor/forbidden-volume checks and final hold at
(400,0,0.03125). Export and route acceptance remain separate steps. An additional
fresh TFO route records its native header state.

[The navigation guide](RESPAWN_TF1_NAVIGATION.md) records commands, hashes,
algorithm RVAs and evidence under `.local/respawn/phase2-navigation-crc`.
This closes a scoped export/CRC workflow, not general navigation: other hulls,
default AI, dynamic/repeated routes, combat, titan piloting, tail/script
semantics and the full Phase 2 release gates remain open. Prior entries retain
their chronological failures and narrower evidence.

### 18 November: repeated native goal/return routing

The completed late-17-November reports now establish two round trips on the
changed-pillar fixture in both R1Delta and TFO. Each uses one grunt, four legs,
48 movement samples and four leg-start poses. Every leg's living floor/obstacle
poses and final two samples must pass independently; returns remain within
24 units of the requested start. No post-spawn repositioning is used.

Shared `round_trips` validation and indexed per-leg events reject missing,
duplicate, dead, stationary and incomplete later-leg results. Total sampled time
is bounded to 180 seconds; legacy one-way checks retain their format. The public
fixture generator accepts `--round-trips 2`. Native evidence is in
`.local/respawn/phase2-navigation-repeat` and described in the
[navigation checkpoint](RESPAWN_TF1_NAVIGATION.md).

All 278 MRVN tests pass; ARES runs 170 adapter tests with one skip. This is
repeated human-hull routing, not dynamic obstacles, default AI, other hulls or
combat. Atlas routing is being investigated separately from the earlier
flat-floor support result; no atlas navigation acceptance is inferred here.


### 18 November: actual atlas NPC navigation in both runtimes

The new shared `navigation_probe.actor="atlas"` uses native per-runtime atlas
settings, `HULL_TITAN` connectivity and a required native titan/type/bounds
event. Both runtimes report bounds (-60,-60,0)..(60,60,235). On the changed-pillar
fixture, final public runs pass outbound and return legs on one atlas NPC:
40 movement samples per runtime, expanded sampled clearance, living floor poses
and two final hold samples per leg. There is no post-spawn repositioning.

An initial TFO fixed-facing return control fails its hold despite reaching the
return area. That report remains intact. The supplied goal helper makes facing
optional, while the probe's assertions only require positional routing. The final
atlas probe leaves arrival facing unspecified (`angles=null`); both runtimes
then pass without relaxing radius/floor/clearance/hold assertions. The fixed-facing
TFO behavior remains open and is not classified as a compiler defect.

[The navigation guide](RESPAWN_TF1_NAVIGATION.md) identifies all controls and
artifacts under `.local/respawn/phase2-atlas-navigation`. A fresh original
generator fixture also compiles with `--actor atlas --round-trips 1`.
Current checks: 278 MRVN tests pass; ARES runs 173 adapter tests with one skip,
including 15 passing focused navigation tests. Piloting, combat, other titan
types, dynamic obstacles, default AI, broader visuals/assets and release
acceptance remain open. Full Phase 2 is not complete.
