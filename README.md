# MRVN-Radiant

The open-source, cross-platform level editor for Respawn Entertainment Source based games.

MRVN-Radiant is a fork of NetRadiant-custom (GtkRadiant 1.4 &rarr; massive rewrite &rarr; 1.5 &rarr; NetRadiant &rarr; NetRadiant-custom &rarr; this)

<div align=left>
<img alt="GitHub Workflow Status" src="https://img.shields.io/github/actions/workflow/status/MRVNRadiant/MRVNRadiant/build.yml?style=for-the-badge">
<img alt="GitHub Issues" src="https://img.shields.io/github/issues/MRVNRadiant/MRVNRadiant?style=for-the-badge">
<img alt="GitHub Pullrequests" src="https://img.shields.io/github/issues-pr/MRVNRadiant/MRVNRadiant?style=for-the-badge">
</div>

## Supported games
- Titanfall Online ( [TFORevive](https://tforevive.net/) )
- Titanfall 2 ( [Northstar](https://northstar.tf) )
- Apex Legends ( [R5Reloaded](https://r5reloaded.com/) )

## Status

End-to-end game compatibility is not yet verified. The percentages below are
historical lump-generation counts, not a measure of playable-map compatibility.
Respawn research notes live in [docs/respawn](docs/respawn): the
[compatibility plan](docs/respawn/RESPAWN_COMPATIBILITY.md) (current gaps, release
gates, BSP inspection), [lighting](docs/respawn/RESPAWN_LIGHTING.md), retail
samples, map trials, crash investigations and the E1M1 test-mod build notes. See the
[source attribution register](docs/respawn/RESPAWN_SOURCES.md) for research/tool credits.
These tools do not yet provide a verified engine lightmap bake.

| Game | Coverage | Note |
|------|----------|------|
| Titanfall Online | 38% | No triangle collision, no lighting, no portals |
| Titanfall 2 | 37% | No triangle collision, no lighting, no portals |
| Apex Legends | 25% | No collision, no lighting, no portals |

> Coverage = Lumps generated / Total lump count. Stubbed lumps arent counted because they're not custom.

> NOTE: These values are updated manually.

## Other tools
- [bsp_tool](https://github.com/snake-biscuits/bsp_tool)
    - A Python library for analyzing .bsp files

- [bsp_regen](https://github.com/snake-biscuits/bsp_regen)
    - `Titanfall -> Titanfall | 2` Map Converter

- [MRVN-Explorer](https://github.com/MRVN-Radiant/MRVN-Explorer)
    - A OpenGL/ImGui respawn bsp viewer
