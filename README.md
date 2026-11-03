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
- Titanfall Online ( [TFORevive](https://tforevive.net/) )
- Titanfall 2 ( [Northstar](https://northstar.tf) )
- Apex Legends ( [R5Reloaded](https://r5reloaded.com/) )

## Status

Coverage counts which BSP lumps remap writes from the map rather than as fixed
placeholders. It is not a measure of playable-map compatibility. Titanfall 2 maps
compiled with this fork load and play in Northstar, with baked lighting (see the
[Titanfall 2 Custom Maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps)).
Titanfall Online and Apex output is less complete and less tested.

Respawn research notes live in [docs/respawn](docs/respawn/README.md): the
[compatibility plan](docs/respawn/RESPAWN_COMPATIBILITY.md) (current gaps, release
gates, BSP inspection), [lighting](docs/respawn/RESPAWN_LIGHTING.md), retail
samples, map trials, crash investigations and the converter notes. See the
[source attribution register](docs/respawn/RESPAWN_SOURCES.md) for research/tool credits.

| Game | Coverage | Note |
|------|----------|------|
| Titanfall Online | 93% (70/75) | Baked lighting, probes, shadow meshes, brush and patch collision, sky portals; tested in Titanfall Online. Missing cubemaps, VPhysics and physics triangles; see [RESPAWN_TF1_LUMPS.md](docs/respawn/RESPAWN_TF1_LUMPS.md) |
| Titanfall 2 | 99% (80/81) | Every lump retail fills except triangle collision bevels; see [RESPAWN_TF2_LUMPS.md](docs/respawn/RESPAWN_TF2_LUMPS.md) |
| Apex Legends | 38% (26/68) | BVH collision; no lighting, no portals. Not yet recounted for empty lumps |

> Coverage = lumps remap writes as retail maps do / lumps named for that game in
> `tools/remap/source/lump_names.h`. A lump counts when remap generates it from the
> map, or when it is empty in every surveyed retail map and remap writes it empty.
> Fixed placeholder stubs don't count. Titanfall 2's lighting, probe and shadow
> lumps are generated when the map has lights.

> NOTE: These values are updated manually. Last counted 2026-11-04 from
> `titanfall.cpp`, `titanfall2.cpp` and `apex_legends.cpp`.

## Other tools
- [bsp_tool](https://github.com/snake-biscuits/bsp_tool)
    - A Python library for analyzing .bsp files

- [bsp_regen](https://github.com/snake-biscuits/bsp_regen)
    - `Titanfall -> Titanfall | 2` Map Converter

- [MRVN-Explorer](https://github.com/MRVN-Radiant/MRVN-Explorer)
    - A OpenGL/ImGui respawn bsp viewer
