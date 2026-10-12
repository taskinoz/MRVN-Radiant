# Respawn lighting research and tools

For Titanfall 2, `remap` now bakes lightmaps whenever a map places light
entities (see [Compiler bake](#compiler-bake-titanfall-2)). The output matches the
retail layout and passes structural checks. It has **not yet been tested in-game**,
and the SKY A brightness scale is a guess. Maps without lights, and the Titanfall 1
and Apex writers, still emit placeholder records with atlas index `-1`. None of
this provides GI, light probes or CSM.

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
- **Which lights get slots:** only suns (flags 24) and point/spot lights with
  flags 28 appear in RTL pages. Lights with flag 4 (`"realtime" "0"` in the
  `.ent`) never do, so they are treated as baked-only.
- **RTL C:** nearly all zero in retail and written as zero here.
- **SKY B:** alpha is 255 on every charted retail texel. Decoded RGB is a
  direction whose mean length is about 0.78, consistent with a weighted average
  of incoming light directions.
- **SKY A:** small values, with a decoded p95 of about 0.03–0.07. It is warm
  under a cool sky ambient, which suggests bounced sunlight rather than plain sky
  ambient. Its exact meaning is not established.

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
- **`_pbr_falloff 1`:** these lights store intensity ×100000. They are not
  modelled; such lights are treated as `_pbr_falloff 0`.

### What the compiler does

1. Brush faces and patches are unwrapped at 16 units per texel. Patches use
   their row and column arc length. Islands are packed tallest first into
   1024² shelf pages with a 2-texel gutter. Islands larger than a page are
   scaled down. Page sizes are rounded up to powers of two, as retail pages are.
2. Lit material sorts point at their page, and vertex UVs are normalised to it.
3. For each texel, the four realtime lights with the highest contribution ×
   visibility get slots. Suns keep their slot even when fully shadowed, as
   retail does. Lights behind walls give up their slot. Each chart gets one RTL
   page holding at most 63 lights.
4. Shadow masks average four sub-texel rays against opaque, non-sky world
   brushes. Sky brushes let sun and sky rays through.
5. SKY A = sky ambient × cosine-weighted sky visibility (16 rays) × 0.05, plus
   static (`realtime 0`) lights. SKY B is the weighted incoming direction. The
   0.05 scale was chosen to match retail magnitudes and needs an in-game check.

Only the first `light_environment` is baked. Retail menu stages use a second
environment selected by `light_environment_volume`, which is not implemented.

### Verification so far

- **Lit regression fixture** (`compiler_regression.py`): world-light
  order/flags, plane sizes and page binding are correct. The roof's sun shadow
  falls on the correct side and reaches past the roof edge. Realtime point and
  spot lights get slots, the static light lands in SKY A, and the roof reduces
  sky ambient.
- **Quake E1M1** (198 lights): one 1024² page and 8 RTL pages. Bake time is
  about 0.3 s. Mask averages are 224–236. Lit vs unlit agrees with the
  independent Python vertex reference on 82.6% of vertices; that reference used
  a longer, different falloff. The structural inspector and record validator
  report no issues.

## Remaining work

1. Load a baked map in Northstar. Confirm the sun and point-light shadows, then
   calibrate the SKY A scale and the meaning of SKY B against retail-looking
   output.
2. Add indirect (bounce) lighting to SKY A, which retail appears to contain, and
   tangent-space handling for bump-lit surfaces.
3. Support `light_environment_volume` for menu stages, and splitting oversized
   charts.
4. Generate probes, model/parent links, shadow meshes and CSM structures from
   authored data, followed by independent validation and Northstar tests.
5. Add separate TF1/Online and Apex season profiles. No cross-game bake equivalence
   is assumed from shared lump numbers.
