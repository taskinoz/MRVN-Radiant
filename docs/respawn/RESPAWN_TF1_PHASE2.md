# Phase 2: Titanfall 1 / Titanfall Online support

Checkpoint: 14 November 2026. **Partially verified; full support is not complete.**
Phase 1's surf release gates remain open; the user requested Phase 2 work in
parallel with them. Initial runtime testing used TFORevive because another
system was using EA/Origin. After the user confirmed EA was signed in,
R1Delta 3.0.5 also passed the six shared baseline collision checks. Subsequent
work added paired barrel support controls and sequential drops, described below.
Broader acceptance in both runtimes remains outstanding.

## Compiler parity inventory

The [per-lump checklist](RESPAWN_TF1_LUMP_CHECKLIST.md) inventories every unique
lump written by `WriteR1BSPFile`, including conditional lighting writes and the
separately serialized GAME_LUMP. It compares a fresh authored baseline against
local Angel City, Colony and the installed TFO lobby. The machine-readable
current report is `.local/respawn/phase2-rtl-fixed/lump-audit.json`.

- 70 unique writer lump types; 52 have schemas in `validate_records.py`, 18 do
  not. Individual tools and compiler regressions cover some of the latter;
  absence of a schema does not mean no implementation exists. The first audit
  had 44 schemas; eight v29-specific layouts were added during this work.
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
   fixtures and six reference maps pass. Remaining: CSM nodes/references, shadow
   meshes, deeper lighting semantics and RTL channel decoding before replacing
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
16 collision vertices, all eight actual physics hull bottoms are 0.36â€“0.44
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
