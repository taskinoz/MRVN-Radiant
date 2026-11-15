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
| Titanfall 1 / R1Delta + Titanfall Online | 99% (74/75), legacy writer count | Shared v29 compiler. Sampled collision and prop support pass in both runtimes; underwater geometry/fog passes one TFO scene. R1Delta water surface/upper-view rendering remains unresolved. Full Phase 2 compatibility is open; see [Phase 2 evidence](docs/respawn/RESPAWN_TF1_PHASE2.md) |
| Titanfall 2 | 100% (81/81) | Every lump retail fills; triangle collision bevels use a natively tested rule, not retail's exact lists; see [RESPAWN_TF2_LUMPS.md](docs/respawn/RESPAWN_TF2_LUMPS.md) |
| Apex Legends | 38% (26/68) | BVH collision; no lighting, no portals. Not yet recounted for empty lumps |

> Coverage = lumps remap writes as retail maps do / lumps named for that game in
> `tools/remap/source/lump_names.h`. A lump counts when remap generates it from the
> map, or when it is empty in every surveyed retail map and remap writes it empty.
> Fixed placeholder stubs don't count. Titanfall 2's lighting, probe and shadow
> lumps are generated when the map has lights.

> NOTE: These values are updated manually. Last counted 2026-11-06 from
> `titanfall.cpp`, `titanfall2.cpp` and `apex_legends.cpp`.

## TF1 / TFO compatibility (15 November 2026)

The shared compiler target does not imply identical runtime behavior. R1Delta
needs an intermission camera and coordinates within +/-16384; the compiler now
creates a missing camera from an existing pilot spawn. Models and materials
must be packaged with their dependencies for standalone maps.

| Area | Verified samples | Remaining acceptance |
| --- | --- | --- |
| v29 structure/startup | 37 compiled/reference maps validate; fresh maps start in both runtimes | Remaining record semantics and broader maps |
| Collision/physics | Paired ray/hull probes, barrel support, sequential R1 drops; actual-PHY support in one TFO crate stress scene | Curved/transformed/backface collision, masks, repeated stress and historical fall-through |
| Water | Wet/dry cell regression; compiled underwater geometry and fog in TFO | R1 surface rendering, paired buoyancy, slopes/multiple pools and submerged props |
| Lighting | Fallback lightmap planes and structural probe checks | World/character appearance and real-time-light semantics in both runtimes |
| Assets/gameplay/release | Controlled harness staging and baseline spawns | Complete dependency packages, objectives/modes/navigation and human matches |

Validation at this checkpoint: 232 MRVN tool tests and 60 compiler regression
reports pass. ARES provides the paired native adapters and diagnostics. These
counts and the writer coverage above are not a percentage of full compatibility.
The [Phase 2 log](docs/respawn/RESPAWN_TF1_PHASE2.md) retains native failures and
is the detailed source for acceptance status.

## Other tools
- [bsp_tool](https://github.com/snake-biscuits/bsp_tool)
    - A Python library for analyzing .bsp files

- [bsp_regen](https://github.com/snake-biscuits/bsp_regen)
    - `Titanfall -> Titanfall | 2` Map Converter

- [MRVN-Explorer](https://github.com/MRVN-Radiant/MRVN-Explorer)
    - A OpenGL/ImGui respawn bsp viewer
