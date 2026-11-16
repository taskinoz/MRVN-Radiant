# MRVN-Radiant

> **This is a fork with AI-generated changes.** The Respawn tools, research notes
> and compiler changes added here were produced with AI; see [AI.md](AI.md). The
> original, human-built editor is
> [MRVN-Radiant/MRVN-Radiant](https://github.com/MRVN-Radiant/MRVN-Radiant).

The open-source, cross-platform level editor for Respawn Entertainment Source based games.

MRVN-Radiant is a fork of NetRadiant-custom (GtkRadiant 1.4 &rarr; massive rewrite &rarr; 1.5 &rarr; NetRadiant &rarr; NetRadiant-custom &rarr; this)

<div align=left>
<a href="AI.md"><img alt="AI: generated Respawn tools" src="https://img.shields.io/badge/AI-generated_Respawn_tools-8957e5?style=for-the-badge"></a>
<a href="https://github.com/taskinoz/MRVN-Radiant/actions/workflows/build.yml"><img alt="GitHub Workflow Status" src="https://img.shields.io/github/actions/workflow/status/taskinoz/MRVN-Radiant/build.yml?branch=respawn-format-research&style=for-the-badge"></a>
<a href="https://github.com/taskinoz/MRVN-Radiant/releases/tag/prerelease"><img alt="Pre-release" src="https://img.shields.io/badge/download-pre--release-orange?style=for-the-badge"></a>
<img alt="GitHub Issues" src="https://img.shields.io/github/issues/MRVNRadiant/MRVNRadiant?style=for-the-badge">
<img alt="GitHub Pullrequests" src="https://img.shields.io/github/issues-pr/MRVNRadiant/MRVNRadiant?style=for-the-badge">
</div>

## Supported games
- Titanfall 1 / [R1Delta](https://r1delta.net/) and Titanfall Online / [TFORevive](https://tforevive.net/) (shared BSP v29 compiler target)
- Titanfall 2 ( [Northstar](https://northstar.tf) )
- Apex Legends ( [R5Reloaded](https://r5reloaded.com/) )

## Status

Coverage counts which BSP lumps remap writes from the map rather than as fixed
placeholders. It is not a measure of playable-map compatibility. Titanfall 2 maps
compiled with this fork load and play in Northstar, with baked lighting (see the
[Titanfall 2 Custom Maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps)).
Titanfall 1/R1Delta, Titanfall Online and Apex output remain partially verified.
TF1 and TFO currently share `remap -game titanfallonline`; runtime validation and
asset packaging are separate because the games mount different content and have
different startup requirements.

Respawn research notes live in [docs/respawn](docs/respawn/README.md): the
[compatibility plan](docs/respawn/RESPAWN_COMPATIBILITY.md) (current gaps, release
gates, BSP inspection), [lighting](docs/respawn/RESPAWN_LIGHTING.md), retail
samples, map trials, crash investigations and the converter notes. See the
[source attribution register](docs/respawn/RESPAWN_SOURCES.md) for research/tool credits.

| Game | Coverage | Note |
|------|----------|------|
| Titanfall 1 / R1Delta + Titanfall Online | Partial; legacy writer count 74/75 | Shared v29 compiler. Sampled collision and prop support pass in both runtimes; underwater geometry/fog passes one TFO scene. R1Delta surfaces render with packaged shader caches; an underwater band remains unresolved. Full Phase 2 compatibility is open; see [Phase 2 evidence](docs/respawn/RESPAWN_TF1_PHASE2.md) |
| Titanfall 2 | 100% (81/81) | Every lump retail fills; triangle collision bevels use a natively tested rule, not retail's exact lists; see [RESPAWN_TF2_LUMPS.md](docs/respawn/RESPAWN_TF2_LUMPS.md) |
| Apex Legends | 38% (26/68) | BVH collision; no lighting, no portals. Not yet recounted for empty lumps |

> Coverage = lumps remap writes as retail maps do / lumps named for that game in
> `tools/remap/source/lump_names.h`. A lump counts when remap generates it from the
> map, or when it is empty in every surveyed retail map and remap writes it empty.
> Fixed placeholder stubs don't count. Titanfall 2's lighting, probe and shadow
> lumps are generated when the map has lights.

> NOTE: These values are updated manually. Last counted 2026-11-06 from
> `titanfall.cpp`, `titanfall2.cpp` and `apex_legends.cpp`.

## TF1 / TFO compatibility (17 November 2026)

The shared compiler target does not imply identical runtime behavior. R1Delta
needs an intermission camera and coordinates within +/-16384; the compiler now
creates a missing camera from an existing pilot spawn. Models and materials
must be packaged with their dependencies for standalone maps.

| Area | Verified samples | Remaining acceptance |
| --- | --- | --- |
| v29 structure/startup | 37 compiled/reference maps validate; fresh maps start in both runtimes | Remaining record semantics and broader maps |
| Collision/physics | Paired ray/hull and transformed-brush probes; paired flat-patch/backface and 32 contents-mask probes; prop support samples | Broader curved collision, actual projectiles/titans, repeated stress and historical fall-through |
| Water | Wet/dry cell regression; compiled underwater geometry/fog in TFO; paired wet/dry cardboard buoyancy sample | R1 underwater band, broader buoyancy/model/depth controls, slopes/multiple pools and submerged props |
| Lighting | Fallback lightmap planes; structural probe and CSM-tree checks | World/character appearance and real-time-light semantics in both runtimes |
| Assets/gameplay/release | Controlled harness staging and baseline spawns | Complete dependency packages, objectives/modes/navigation and human matches |

Validation at this checkpoint: 255 MRVN tool tests and 60 compiler regression
reports pass. ARES provides the paired native adapters and diagnostics. These
counts and the writer coverage above are not a percentage of full compatibility.
The v29 mesh vertex-type enum now matches surveyed retail TF1 maps (unlit 0,
lit-flat 1, lit-bump 2), with pool selection/lightmap bookkeeping kept separate.
Material sorts also store their referenced vertex span, matching the surveyed
retail records. Regression cases check both metadata relationships.
R1 Water shader caches must load through the map VPK in the tested scene.
See the packaging result below.
Paired wet/dry cardboard probes now show flotation in both runtimes, with dry
PHY support passing. The wet bodies continue bobbing; entity-reported velocity
can be zero during motion. ARES now checks sampled translation separately and
TFO sequential drops honor sample recording. This is one buoyancy sample, not
broad physics parity or proof of rest.
The [Phase 2 log](docs/respawn/RESPAWN_TF1_PHASE2.md) retains native failures and
is the detailed source for acceptance status.

R1 cold-load water surfaces now render when the two supplied compiled Water
shader caches are in a map VPK; loose shader copies do not work. The explicit
`pack_tf1_shaders.py` command reproduces the native-tested shader package and
records hashes without including retail assets. A new dependency audit checks the
known Water material, texture and cache files before packaging. On the same fully
flooded BSP, TFO renders the sampled underwater view without a black band while
R1Delta retains it; a supplied zero-refraction underside control also retains it.
The CSM, shadow and occlusion streams now have structural checks. Writer record
schema coverage is 61/70; texture-name references and physics model/solid framing
also validate against the reference corpus. Alive retail R1 water captures show a
horizon artifact too, so the band is not unique to an authored BSP.
Both adapters reject missing declared v29 entity sidecars before staging.
R1 prefers verified engine screenshots; TFO engine capture remains
opt-in after native crashes. Full Phase 2 release acceptance is still open.

## Other tools
- [bsp_tool](https://github.com/snake-biscuits/bsp_tool)
    - A Python library for analyzing .bsp files

- [bsp_regen](https://github.com/snake-biscuits/bsp_regen)
    - `Titanfall -> Titanfall | 2` Map Converter

- [MRVN-Explorer](https://github.com/MRVN-Radiant/MRVN-Explorer)
    - A OpenGL/ImGui respawn bsp viewer
