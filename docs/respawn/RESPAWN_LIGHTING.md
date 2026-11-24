# Respawn lighting research and tools

For Titanfall 2, `remap` now bakes lightmaps whenever a map places light
entities (see [Compiler bake](#compiler-bake-titanfall-2)). The output matches the
retail layout and passes structural checks. It also writes character light
probes, one diffuse bounce into SKY A, and CSM shadow meshes, and baked maps
play in Northstar. Titanfall 1 shares the bake (see
[RESPAWN_TF1_LUMPS.md](RESPAWN_TF1_LUMPS.md)). Maps without lights, and the Apex
writer, still emit placeholder records with atlas index `-1`.

On 24 November 2026 a freshly rebuilt compiler (`remap.exe` SHA-256
`6daec3b2309802af6ecfd17d2635a8a7e693b07d59325094c2dd1fcebf81ff94`) produced a
roof/sun/realtime-light fixture and a separate one-light-class-per-room fixture
with an unlit control. Both loaded, rendered, traced and shut down cleanly in the
isolated Northstar harness profile; every supported local-light class rendered
above the zero-ambient control. The captured evidence and its limits are recorded
in [SOW_TF2.md](SOW_TF2.md); these are native load/render checks, not shader-level
channel validation or brightness parity.

The later one-hash integration build
(`b0a8064905996b3b2790cee1df12fcf59aae212c9fc6b66301d6ca2370098110`) passed the
full compiler suite and replayed those three TF2 fixtures with identical lump
payload hashes; only BSP header timestamps differ. That is compiler-output
evidence, not a new native session. The native captures above remain bound to
`6daec3b2…`.

## Attribution

Binary schema facts were checked against **snake-biscuits/bsp_tool** commit
`655627ea8704353ac14bd753df8ca05c15838eda`:

- `bsp_tool/branches/respawn/titanfall.py`: lightmap headers, lit vertices,
  material-sort linkage and original Titanfall world lights.
- `bsp_tool/branches/respawn/titanfall2.py`: v2/v3 world lights and RTL pages;
  the original research credits RoyalBlue and other contributors in that source.
- `bsp_tool/lightmaps/titanfall.py` and `titanfall2.py`: stored atlas-plane layouts.

The upstream repository is GPL-3.0. It is an ignored local research checkout,
not imported or distributed by these tools. The implementation here is original
GPL-2.0-or-later code using documented binary facts; no upstream implementation
was copied. The existing NetRadiant lighting infrastructure remains credited by
its original source notices. Local map archives were read through the pinned
`pg9182/tf2vpk` tool already credited in [RESPAWN_SOURCES.md](RESPAWN_SOURCES.md).
No retail map assets are added to the repository or distributed in the tools.

The SKY A/B encoding and the light-probe layout follow the
[apex-to-titanfall-2](https://github.com/taskinoz/apex-to-titanfall-2) converter
(commit `89fbcaa`): its `LIGHTING.md`, `CHARACTER_LIGHTING.md`,
`bake_phase_lighting.cpp`, `apply_baked_lighting.py` and
`build_character_lighting.py`. That project reverse-engineered the shipped world
pixel shader and the engine's probe loader, and checked its Phase Runner bake in
the game client. MRVN-Radiant reimplements the documented encodings; no
converter code is copied, and no retail probe data is reused.

## Findings checked against local maps

Additional conversion-project observations from Gravemind are recorded with
document revisions and verification scope in [RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md).
They provide candidate SKY encoding, RTL hardware-light remapping and character
probe/menu-stage behavior. These shader semantics have not yet been independently
validated by the MRVN-Radiant lighting tools; raw atlas previews remain raw.

`LIGHTMAP_HEADERS` is lump 83, record version 1, with 8-byte `uint32 type,
uint16 width, uint16 height` records. The tested R2 headers all have type 1.
Material sorts store a signed lightmap-header index, with `-1` meaning no atlas.
Lit flat/bump vertices contain a two-float lightmap UV and another two-float
step field. Channel names below describe byte planes, not shader semantics.

| Map / representation | Pages | SKY bytes | RTL bytes | Observed layout |
| --- | ---: | ---: | ---: | --- |
| TF2 Coliseum, effective external | 2 | 1,572,864 | 1,572,864 | SKY 8, RTL 8 bytes/header texel |
| TF2 Coliseum, embedded | 2 | 1,572,864 | 1,769,472 | SKY 8, RTL 9 bytes/header texel |
| TF2 Glitch, effective external | 3 | 25,165,824 | 25,165,824 | SKY 8, RTL 8 bytes/header texel |
| TF2 Glitch, embedded | 3 | 25,165,824 | 28,311,552 | SKY 8, RTL 9 bytes/header texel |
| TF1 Angel City, effective | 6 | 38,797,312 | 19,398,656 | SKY 8, RTL 4 bytes/header texel |
| E1M1 0.2.0 compiler output | 1 | 524,288 | 0 | Missing RTL data, no atlas-bound material sorts |

The observed R2 SKY layout is A/B, each `width*height*4` bytes. Embedded RTL
is A/B at full dimensions followed by C at half width and half height. Effective
default RTL sidecars have only A/B. Byte totals and dimensions match independently
in both retail R2 maps. These observations do not establish whether planes store
irradiance, direction, masks, RGB exponents, or other shader-specific information.
Alpha must not be assumed to mean transparency. The PNG exports make RGB opaque
and provide a separate alpha visualization, retaining exact raw `.rgba` bytes.

Coliseum has 12 v3 world lights; Glitch has 459. R2 v3 records are 112 bytes,
v2 records 108 bytes, and the original v1 format is 100 bytes. The inspector
decodes origin, intensity, direction, shadow offset, type/style, spotlight
parameters, radius, attenuation, flags and references without discarding the
unknown tail. The writer presently supports explicit **v3 point lights only**.
Brightness calibration and runtime flags remain experimental.

The compiler's E1M1 bump UV range was `[-192,192]`, while Coliseum and Angel City
UV ranges are inside `(0,1)`. The old inactive packing helper also had integer
division setting its scale to zero, edited a mesh copy, and appended row-vector
elements while retaining references into that vector. It has been replaced with
a bounded, tested shelf packer that rejects oversized/nonfinite rectangles,
reserves gutters and updates mesh references. **The native packing call stays
disabled until atlas emission and material-sort references are integrated**;
this change alone does not activate native lighting.

## Inspection and exact plane export

Python 3.10+, standard library only. Paths below are examples from this checkout.
Outputs must be new paths; retail inputs are read-only.

```powershell
python tools/respawn/lighting.py inspect .local/respawn/samples/tf2-coliseum/maps/mp_coliseum.bsp --export .local/respawn/lighting-research/coliseum --json .local/respawn/lighting-research/coliseum.json
python tools/respawn/lighting.py inspect .local/respawn/samples/tf2-coliseum/maps/mp_coliseum.bsp --embedded --json .local/respawn/lighting-research/coliseum-embedded.json
```

The default uses default external-lump overrides, matching the existing reader.
`--embedded` inspects internal payloads for comparison. Client-specific variants
are not selected. Typed support is gated to little-endian BSP v29/v37 and known
record versions. Apex formats are deliberately rejected until season-specific
lighting layouts are established. Reports expose missing planes, partial records,
invalid atlas references, sizes, hashes, UV ranges and raw channel ranges.

## Offline reference bake

```powershell
python tools/respawn/bake_direct.py .local/respawn/northstar-e1m1-0.2.0/compile/mp_quake_e1m1.bsp --quake-map .local/respawn/map-trials/e1m1-tf2/e1m1.map --output .local/respawn/lighting-research/e1m1-direct
```

Alternatively use `--lights authored-lights.json`. Each light supplies `origin`,
linear RGB `intensity`, positive `radius`, and optional nonnegative attenuation
`[constant, linear, quadratic]` (not all zero). The evaluator uses Lambert cosine
and `1/(constant+linear*d+quadratic*d*d)`, with a 0.25-unit normal offset for rays.
Occlusion uses a bounds hierarchy and exact convex-brush clipping, including
non-axial planes. All collision brushes are opaque occluders; glass and liquid
behavior are not modeled. Only a single static world model is accepted.

The E1M1 run converted 198 Quake point lights and baked 22,291 unique position /
normal samples over 13,738 triangles, with 31,419 visible and 147,960 blocked
rays. Runtime was approximately 30 seconds on this workstation. Outputs:

- `samples.csv`: linear RGB reference samples and visible/blocked ray counts.
- `direct.gltf` / `direct.bin`: geometry with diagnostic vertex colours, using
  `KHR_materials_unlit` so viewer illumination does not alter the reference.
- `lights.json`: explicit experimental Quake-to-tool conversion.
- `bake.json`: parameters, counts and limitations.

This is a vertex-sampled direct-light reference, **not a lightmap atlas bake**.
Large triangles interpolate coarsely. There is no GI, sky transport, material
albedo, spot/area lighting, dynamic-object shadowing, probes, or runtime CSM.
Quake brightness normalization and the diagnostic Reinhard display curve are
explicit experimental choices, not engine-calibrated conversions.

## Authored world-light records

```powershell
python tools/respawn/lighting.py write-lights .local/respawn/northstar-e1m1-0.2.0/compile/mp_quake_e1m1.bsp .local/respawn/lighting-research/e1m1-direct/lights.json .local/respawn/lighting-research/e1m1-authored-lights.bsp
```

The append-only writer preserves offsets and every unrelated lump, including
absolute GAME_LUMP offsets. It refuses external-sidecar inputs, existing outputs,
wrong BSP versions and invalid light parameters. It replaces WORLD_LIGHTS with
v3 point records and clears obsolete world-light parent information. This does
not build the page/light, probe, shadow or realtime-mask relationships needed by
a complete runtime lighting pipeline. The resulting file is an engine experiment.

## Controlled shader-plane probes

```powershell
python tools/respawn/lighting.py write-atlas-probe .local/respawn/northstar-e1m1-0.2.0/compile/mp_quake_e1m1.bsp .local/respawn/lighting-research/e1m1-probe-sky-a.bsp --plane sky-a --rgba 128 128 128 255
```

Planes are `sky-a`, `sky-b`, `rtl-a`, `rtl-b`, `rtl-c`. The writer fills one plane
with the chosen raw bytes, zeros the others, emits a type-1 header and full R2
internal plane sizes, binds lit material sorts to header 0, and makes all lit
vertices sample its centre. It emits an all-`-1` RTL light-index page. It refuses
already atlas-bound inputs and mixed lit/unlit sorts. This is a uniform calibration
probe, **not UV unwrapping or spatial lighting**. Geometry and collision stay intact.
Engine behavior has not been tested; the same size alone does not prove encoding.

For an engine experiment, rebuild a complete Northstar test package with the
chosen candidate BSP and matching entity partitions, keeping its loose and VPK
members identical. Restart between tests; record byte values, plane, screenshot,
console debug settings, Northstar log, BSP hash and frame conditions. First
compare zero planes against single RGB/alpha changes. Do not interpret a white
or dark screen as a successful bake. No installed mod is changed by these tools.

## Compiler bake (Titanfall 2)

Implemented in `tools/remap/source/respawn/lightbake.h` (tested by
`tools/respawn/lightbake_tests.cpp`) and `titanfall2/titanfall2_lighting.cpp`.

### Plane semantics measured from retail Coliseum and Glitch

- **RTL A:** four 6-bit slots, then the RTL page number in the top byte. Slot 63
  is unused. Texels without realtime lights are `0xffffffff`. Coliseum uses only
  `0x00ffffc0` and `0x00ffffc1`.
- **RTL B:** channel *N* is the shadow visibility for slot *N*. The average
  visibility of used slots is 207–235.
- **RTL pages (0x7A):** 63 int16 hardware-light indices, with unused entries
  zero-filled. Hardware indices count world lights excluding type 5 (ambient).
  Coliseum's slot 0 is hardware light 0, its gameplay sun.
- **Which lights get slots:** retail flags are key bit fields
  (`analyze_rtl.py`, 2,297/2,298 records across six maps): 4 legacy falloff or
  32 `_pbr_falloff 1`, +8 realtime, +16 when `realtime_shadows` is 0 or absent,
  +64 when it is 2. Suns are 24. Every realtime local light can take an RTL
  slot; baked lights (no +8) never do. `"shadow" "0"` no longer removes slots
  or changes flags.
- **RTL C:** nearly all zero in retail and written as zero here.
- **SKY B:** alpha is 255 on every charted TF2 retail texel; TF1 instead stores
  baked sun occlusion there (0 sunlit, 255 blocked or facing away). The converter's shader
  analysis identifies RGB as a world-space bent sky vector. The shader applies
  the ambient world light through it, so the vector's length carries sky
  visibility. Retail's mean length of about 0.78 is consistent with this.
- **SKY A:** small values, with a decoded p95 of about 0.03–0.07, warm-tinted
  under a cool sky ambient. Retail probably includes bounce lighting here. The
  converter's client-checked bake writes only a small fill.
- **Tangents:** bump-lit (0x49) and tangent-space unlit (0x4A) vertices store
  the vertex-normal index of a unit tangent along +dP/du, with the normal
  removed. Bit 31 is set when cross(normal, tangent) points against +dP/dv. The
  second word is 0. Coliseum agrees on 100% of checked triangles and Glitch on
  99.3%.
- **Light probes:** the layout is given in `lightbake.h`. Retail values are
  directional ambient with W around 0.004–0.035 (p95 0.13), sun visibility as a
  0–1 fraction, weights that are 255 on 99.4% of references, and small hardware
  light indices. About 70% of references are baked local lights. The
  parent record (0x04) is (first probe, probe count, first reference, reference
  count, tree nodes); Glitch's 16,183 + 32,085 probes match its probe lump size.

### World lights from `*_env.ent` keys

- **Intensity:** `(channel/255)^2.2 * brightness/255`, from `_light` /
  `_ambient` "R G B brightness". This matches every Coliseum record checked.
- **Attenuation:** the quadratic through (0, 1),
  (`_fifty_percent_distance`, 0.5) and (`_zero_percent_distance`, 0). For
  example, 300/90 gives `[1, -0.006508, 1.06e-5]`, as stored. Radius is the zero
  distance.
- **Direction:** pitch from `pitch` (or `-angles[0]`) and yaw from `angles[1]`,
  giving `(cos p cos y, cos p sin y, sin p)`. Spot `stopdot`/`stopdot2` are the
  cosines of `_inner_cone`/`_cone`.
- **Order:** ambient (5), suns (3), spots (2), points (1).
- **LEVEL_INFO:** the writer copies the last sun record's normal into
  `unk2`, matching the sampled retail maps; a map with no sun keeps the
  placeholder.
- **Brightness in practice:** Glitch's short-range realtime points use
  `_light "255 175 94 5100"`, which gives intensity 20 over 150 units. Even so,
  E1M1's 199 closely spaced Quake lights at a ×10 scale overexposed the whole map
  in-game. Quake-style `"light"` values are therefore used unscaled (about 0.8
  for 200), which gives Quake-like pools of light (harness captures, 12
  October). A worldspawn `_lightscale` key multiplies every point and spot
  light. The earlier "flat" report came from the old 0.2.1 build, which had no
  baked lights.
- **`_pbr_falloff 1`:** these lights store intensity ×100000. The writer emits
  that scale and flag 32 (baked), 40, 56 or 104 as appropriate, after applying
  `_lightscale` to the underlying intensity.

### What the compiler does

1. Brush faces and patches are unwrapped at 16 units per texel. Patches use
   their row and column arc length. Islands are packed tallest first into
   1024² shelf pages with a 2-texel gutter. Islands larger than a page are
   cut on a page-sized grid in lightmap space, each tile its own mesh at full
   resolution (cuts add vertices where grid lines cross the island's edges);
   they used to be shrunk as a whole. Page sizes are rounded up to powers of two, as retail pages are.
2. Lit material sorts point at their page, and vertex UVs are normalised to it.
3. For each texel, the four realtime lights with the highest contribution ×
   visibility get slots. Suns keep their slot even when fully shadowed, as
   retail does. Lights behind walls give up their slot. Each chart gets one RTL
   page holding at most 63 lights.
4. Shadow masks, and static (`realtime 0`) lights, average four sub-texel
   rays against opaque, non-sky world brushes. Sky brushes let sun and sky
   rays through. A texel whose ray origin is inside a brush is first moved
   within its footprint; if it stays buried it copies a visible texel of its
   chart (see [Bake quality](#bake-quality-18-november-2026)).
5. SKY B is the bent sky direction × ∛(sky visibility), using 16
   cosine-weighted rays (`_skysamples`), smoothed within the chart. SKY A is a
   fill of ambient × 0.04 (`_ambientscale`) × (0.4 + 0.6 × visibility), plus
   static lights. That is about 0.03 for a typical ambient, matching Coliseum
   and the converter; see the retail comparison below.
6. Character probes sit where characters stand, plus a coarse grid for open
   air. Retail probe sets are adaptive (neighbours a median 56–58 units apart in
   Glitch and Angel City, 128 in Coliseum; a quarter within about 60 units of the
   floor; almost none share an xy column; Glitch has 73,760). Over every
   upward-facing lit triangle, a world-aligned 64-unit lattice plus the
   triangle's centre get probes 24 and 72 units above the surface, unless inside
   a brush or under a lower ceiling. The coarse 256 × 256 × 128 grid fills open
   air. Each set's spacing grows past 65,536 probes. E1M1 went from 1,180 to
   6,824 probes (25% within 24 units of the floor, median 56; neighbours a
   median 48 apart) and still loads in Northstar. In third person
   (`thirdperson`, with cheats), the TF1 E1M1 build in TFO showed the character
   nearly black at two of four positions with grid probes and lit like its
   surroundings with walkable probes; TF2 in Northstar looked alike with both.
   `tfo_harness.py` takes `"view_commands": ["thirdperson"]` for this. Each
   probe gets directional ambient, a bent sky vector, sun visibility from four
   jittered rays, and up to four visible local lights (realtime or baked, at
    weight 255 as in retail). A KD tree with leaves
   of at most 8 indexes them; the optional probe BSP accelerator (0x06/0x07) is
   left empty, since the converter found the engine falls back to the KD tree.
7. Quake/Valve 220 brush faces (the editor's `quake3` brush type) now get their
   texture UVs from st vectors. Previously every brush face had zero UVs. Bump
   and TS-unlit vertices get tangents.

**Light environments and the menu stage.** Surfaces bake against environment 0.
How the menu stage is lit:
- **Environment index:** `light_environment` entities carry
  `"lightEnvironmentIndex" "*N"`.
- **Stage probes:** a `light_environment_volume` (convex
  `*trigger_brush_B_plane_P` planes relative to its origin) that contains
  `info_target_clientside` menu anchors gets a probe grid around them
  (±128 × ±128, 0–192, 64-unit spacing). Those probes use that environment's sun
  and ambient plus nearby realtime lights.
- **Coliseum's rig:** this mirrors retail Coliseum. Its stage probes see the menu
  sun and link several menu spotlights at weight 255.
- **Spotlight flags:** flags come from entity keys, not `"shadow"`: 4 legacy
  falloff or 32 PBR, +8 realtime, +16 when `realtime_shadows` is 0 or absent,
  +64 when it is 2. All realtime lights can take RTL slots and be linked from
  probes; baked lights are probe-only.
- **PBR lights:** `_pbr_falloff 1` records store intensity ×100000 after
  `_lightscale`.
- **Entity routing:** Titanfall 2 entities now go through `Titanfall2::EmitEntity`,
  which writes lights and environments to `_env.ent`, as retail does. Previously
  they all went into the BSP entity lump through the Titanfall 1 router.

### Verification so far

- **Lit regression fixture** (`compiler_regression.py`): world-light
  order/flags, plane sizes and page binding are correct. The roof's sun shadow
  falls on the correct side and reaches past the roof edge. Realtime point and
  spot lights get slots, the static light lands in SKY A, and the roof reduces
  sky ambient. Probe lumps are consistent, probes link to the nearby realtime
  light (never the static one), and probe sun visibility follows the roof.
  Compiled tangents follow the retail direction and handedness convention.
- **TF2 alpha-shadow and environment-volume regressions**
  (`compiler_regression.py`): an opaque caster and an alpha-tested caster emit
  separate opaque/alpha shadow meshes while the compile-only sky shell stays
  out of both streams. A two-environment fixture gives the stage and gameplay
  disjoint local-light probe links and empty stage shadow-mesh ranges. Native
  1.31.13 harness runs loaded both maps cleanly; the environment-volume run
  showed a clear warm/cool player-colour split, while the alpha run's shadow
  contrast stayed near the capture noise floor. See
  `.local/respawn/tf2-alpha-shadow-20261124/native-run/native-evidence.json` and
  `.local/respawn/tf2-env-volume-20261124/native-run/native-evidence.json`.
- **Quake E1M1** (198 lights): one 1024² page and 8 RTL pages. Bake time is
  about 0.3 s. Mask averages are 224–236. Lit vs unlit agrees with the
  independent Python vertex reference on 82.6% of vertices; that reference used
  a longer, different falloff. The structural inspector and record validator
  report no issues.

### Shadow environments (0x05) and shadow meshes

Retail Coliseum has one 36-byte `SHADOW_ENVIRONMENTS` record per light
environment: `[first, last)` CSM AABB nodes, CSM object references and shadow
meshes, then that environment's sun normal. Coliseum has two empty CSM roots
(min = +FLT_MAX, max = −FLT_MAX). The compiler writes the same layout:
- **Gameplay (environment 0)** owns the shadow meshes. These are position-only
  copies of the world model's opaque meshes, with mesh-local uint16 indices.
- **Other environments** own none.

Sky meshes never cast these shadows. Ported sky domes can have the compiler's
`sky` flag without the runtime sky surface flag; they remain visible but are
excluded from the shadow meshes. Otherwise the dome can cast a hard shadow
across the playable map, as seen on Surf Beginner.

Without these records, the menu stage's characters cast shadows into gameplay
in-game. That was not fixed by moving the stage.

For Titanfall 1 and Titanfall Online (v29), mark cutout casters with
`$compileflag alphashadow`. The compiler emits a separate UV-bearing shadow
stream and sets the runtime alpha-test bit on the mesh and material. If no
preview image is available, expose the native material and its `$basetexture`
under the compiler's mounted `materials/` tree (VMT and VTF, including any
VMT Patch includes). The compiler reads the VTF dimensions to scale the UVs
and populate texture metadata. It does not decode VTF alpha for baked lighting
or package the assets for the runtime.

### Bounce lighting

SKY A now includes one diffuse bounce:
1. Each texel's direct irradiance is recorded: realtime lights and the sun
   (scaled by their baked shadow masks), static lights and sky ambient times sky
   visibility.
2. Outgoing radiance (albedo × direct irradiance) is splatted into a sparse
   32-unit grid. Each cell has six bins by surface facing, so a gather reads the
   side of a thin wall it actually hit.
3. Each texel casts 16 cosine-weighted rays to the first brush hit and averages
   the radiance stored there.

Albedo is the shader's average texture colour, linearised and clamped to
0.02–0.9. Probes gather the same grid over the full sphere. The bounce scale
defaults to 3, which brings E1M1's SKY A (median 0.0032 → 0.0215, p90 0.0069 → 0.057) into
retail Coliseum's range. Worldspawn `_bouncescale` overrides it, and 0 turns
bounce off. Harness captures show darker walls lifted: in the `start-back` view,
near-black pixels dropped from 43% to 36%.

### Bake quality (18 November 2026)

Released custom maps showed harsh, splotchy lighting. Ray counts were not the
cause: the Minecraft and Source port builders already use 128–256 sky rays.
Decoding the released atlases found three defects, now fixed:

- **Buried texels.** CSG keeps partly buried faces whole, so texels under a
  touching brush started their rays inside it and baked black. Bilinear
  filtering bled that onto the visible face, giving regular dark dots and
  dark seams at wall feet. Such texels are now nudged within their footprint
  or, if fully buried, copy every plane from a visible texel of their chart.
  They are left out of the bounce grid.
- **Speckle.** Sky visibility and bounce came from 16 rays per texel with no
  filtering. Both are now smoothed with a tent filter that only averages
  texels of the same chart facing within ~25°: 3×3 for sky (`_skyfilter`),
  5×5 for bounce (`_bouncefilter`); 0 turns either off. Shadow masks and
  direct light are not filtered.
- **Stair-stepped static-light shadows.** Static lights used one ray from the
  texel centre; they now use the four sub-texel rays of realtime masks.

Uma, same map and settings: the 90th percentile of the neighbour-to-neighbour
change in sky visibility fell from 1.00 (a full on/off jump) to 0.15; retail
Glitch, Angel City, Relic and Coliseum range 0.08–0.55. Bake time went from
49.8 to 52.2 s. New worldspawn keys: `_ambientscale`, `_bouncesamples`,
`_skyfilter`, `_bouncefilter`.

**Fill level is a separate, open question.** The 0.04 fill was calibrated on
Coliseum, which is the dim outlier in retail. Decoded SKY A medians: Coliseum
0.014, Angel City 0.082, Relic 0.054, Glitch 0.176, Colony 0.169. Released
ports sit at 0.013–0.030, and the Minecraft ports also turn bounce off, so
shade gets a much dimmer fill than in most retail maps. Raising
`_ambientscale` or `_bouncescale` per map is supported. The default is
unchanged until in-game captures confirm the right level.

**TF1 SKY A is linear.** A contributed R1 patch encodes SKY A RGB as sRGB.
Retail TF1 and TF2 builds of the same maps argue against that: decoded as
linear, TF1 Angel City's median (0.049) is near TF2's (0.082). Decoded as
sRGB it would be 0.012. Colony and Relic agree. The multiplier, (alpha+1)/64,
is the same in both readings. Linear encoding is kept.

**TF1 texture reflectivity** is now written. Retail v29 TEXTURE_DATA stores
each texture's mean linear colour (431 of 433 Angel City records are nonzero),
while v37 leaves it zero. Missing textures keep zero. This follows r3muxd's R1
patch.

**The rest of that patch is not merged.** It was written against an
unpublished tree, and four files fail to apply even to upstream `main`. Its
R1 lighting, tricoll, physics and visibility code duplicates this branch's.
It also stops with an error on `light_environment`, `prop_static`, styled or
targeted lights, lit-bump materials and rotated brush models, which every
custom map uses. Two smaller pieces were taken: the reflectivity above, and
checked `fseek`/`fclose` results in the BSP writers, so a failed flush on a
full disk is now an error rather than a silently truncated file.

### Hidden brush faces

Respawn writers emit brush faces directly, so `respawn/csg.h` removes faces
hidden by other solid, visible, non-translucent brushes:
- faces lying entirely inside another brush, or flush against it facing in, are
  removed;
- coplanar faces facing the same way, which z-fight, are trimmed, and the later
  brush keeps the shared area;
- partly buried faces are kept whole, because depth testing hides the buried
  part and trimming would only fragment them.

In E1M1 this removes 2,238 faces and trims 272, cutting it from 13,610 to
10,898 triangles. It also fixed the z-fighting light fixture.

Bevel sides have no `side.plane` (it stays zeroed); occluders must read
`mapplanes[side.planenum]`. With zero-normal planes every point counted as "on
the plane", so whole faces came back as extra fragments, drawing up to three
copies of a face (492 duplicated triangles in E1M1, fixed in a2a3533).

### Index padding

The runtime reads world triangles in pairs. Retail six-aligns every mesh and
follows each odd-sized one with a degenerate triangle (Angel City: all 1,097 odd
meshes). Without that, a grenade's decal projection read the next mesh's indices
and crashed at `engine.dll+0xae8d3`, the address apex-to-titanfall-2 also
recorded. `validate_records.py` now enforces the rule.

## Remaining work

Updated 6 November 2026; the earlier list predated work since done (bounce
lighting, the menu-stage `light_environment_volume`, shadow meshes, static-prop
probe indices, the TF1 bake, and baked maps loading in Northstar).

1. Add Apex season profiles. No cross-game bake equivalence is assumed from
   shared lump numbers.
