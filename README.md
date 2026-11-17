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

**Titanfall 2 / Northstar has the most mature playable custom-map support.
Titanfall 1 / R1Delta and Titanfall Online have working experimental map support.
Full retail feature parity has not been demonstrated for any of these targets.**

The [17 November 2026 support audit](docs/respawn/RESPAWN_MAP_SUPPORT_AUDIT.md)
checks compiler source, installed engine/game fingerprints, 31 local game BSPs,
and retained native runtime reports. All 31 audited BSPs pass their selected
checks. The latest tool suite runs 278 tests; the latest compiler regression
checkpoint has 62 passing reports. Later paired native export/navigation results
are in the [navigation checkpoint](docs/respawn/RESPAWN_TF1_NAVIGATION.md);
the earlier audit retains its original session scope.

| Game / runtime | Practical support | Verified scope and main limits |
| --- | --- | --- |
| Titanfall 1 / R1Delta | Experimental, partially verified; BSP v29 | Authored maps load; sampled collision, standing trigger traversal, props/buoyancy, neutral Hardpoint capture/scoring and two grunt obstacle fixtures pass. Water surfaces need packaged shader caches; an underwater artifact remains. Broader physics, visuals, AI/titans, modes and clean packaging remain open. |
| Titanfall Online / TFORevive | Experimental, partially verified; BSP v29 | Paired native checks and one underwater geometry/fog scene pass. Core135 needs the TF1 content mods; Hardpoint passes require explicit temporary dialogue/sound fixes. Unmodified-Core controls fail. Broader gameplay, audio, AI/titans and release acceptance remain open. |
| Titanfall 2 / Northstar | Usable custom-map path, partially verified; BSP v37 | Authored/converted maps load and play with baked lighting; selected displacement collision and portal stress tests pass. Exact bevel/cubemap semantics, broad water/physics, navigation/titans, all modes and sustained multiplayer remain unproven. See [custom maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps). |
| Apex Legends / R5Reloaded | Experimental BSP v47; separate fork review | [r5valkyrie fork review](docs/respawn/RESPAWN_APEX_FORK_REVIEW.md) contributed generated level metadata, aligned prop references and a model-bounds correction. Larger lighting/collision/visibility integration and later-season support remain unverified. |

TF1/R1Delta and TFO share `remap -game titanfallonline`; TF2 uses
`remap -game titanfall2`. Shared BSP versions do not imply shared assets, scripts,
objectives, engine behavior or packaging. Unmodified retail online services and
other runtime builds are outside the verified scope.

The [Apex fork review and initial integration](docs/respawn/RESPAWN_APEX_FORK_REVIEW.md)
pins r5valkyrie's source revision and checks candidate layouts against supplied
S0-S3 v47 maps. Its single v47 target does not establish arbitrary later-season
support. Following the bounded fixes, all 62 compiler regression reports pass;
no new Apex runtime pass or compatibility percentage is claimed.

### Format coverage is not playable compatibility

Fresh source/corpus recount on 17 November 2026:

| Measure | TF1 / R1Delta | Titanfall Online | Titanfall 2 |
| --- | --- | --- | --- |
| Explicit payload write paths / named lumps | 70/75 | 70/75 | 74/81 |
| Additional unwritten lumps empty throughout the sampled corpus | 4 | 4 | 7 |
| Surveyed named-lump representation, including agreed empty lumps | 74/75 (98.7%) | 74/75 (98.7%) | 81/81 (100%) |
| Selected fixed-record schemas / explicit write paths | 61/70 | 61/70 | 44/74 |

These are structural inventory measures, **not overall compatibility scores**.
Conditional fallbacks and approximate algorithms remain. TF1/TFO omit the
populated `PHYSICS_TRIANGLES` precomputed data; existing research identifies an
engine load-time fallback. TF2 omits no named lump populated in the eight surveyed
maps, which is the limited meaning of its former "100% coverage" label.

The corpus contains six TF1 files (five distinct BSPs), 17 TFO maps and eight TF2
maps. Passing selected record checks does not validate every field, material,
render effect or gameplay path. The audit lists exact environments, hashes,
feature evidence, commands and remaining release gates; there is no defensible
single percentage for complete playable support.

### TF1 / TFO requirements and remaining Phase 2 work

R1Delta requires `info_intermission` and the tested coordinate range is +/-16384.
The compiler creates a missing intermission camera from an existing pilot spawn.
The tested R1 water setup loads `water_ps40.vcs` and `water_vs40.vcs` through a map
VPK; loose shader copies did not work. The underwater artifact also appears in
retail controls, so its cause is not proven to be solely an authored-map defect.

TFO Core135 tests enable `Titanfall1.Content.Client` and
`Titanfall1.Content.Shared`. Its Hardpoint pass uses reported temporary dialogue
and sound-definition fixes; alias/path validation does not certify audible audio.
Two navigation fixtures pass paired route checks using controlled NPC settings;
the changed-pillar fixture also passes two goal/return pairs on one grunt in
each runtime (four independently checked legs and 48 movement samples).
A [bounded native export and offline CRC workflow](docs/respawn/RESPAWN_TF1_NAVIGATION.md)
packages graphs for the pinned runtime; live R1/TFO CRC fields agree with the
changed fixture's offline result. Broader formats, hulls, dynamic obstacles and
general AI remain open. A native atlas NPC also passes an outbound/return route
in both runtimes (40 movement samples each), with expanded clearance and explicit
native type/bounds checks. Arrival facing is unspecified; the initial TFO
fixed-facing return hold fails and remains documented. This does not establish
piloting, combat or all titan behavior.

Phase 2 remains open for broader collision/physics/water and visual acceptance,
navigation automation, contested/other objectives, human matches and complete
package dependency closure. See the [Phase 2 evidence](docs/respawn/RESPAWN_TF1_PHASE2.md)
and [cross-target audit](docs/respawn/RESPAWN_MAP_SUPPORT_AUDIT.md).

Research notes live in [docs/respawn](docs/respawn/README.md). Start with the
[compatibility plan](docs/respawn/RESPAWN_COMPATIBILITY.md),
[lighting](docs/respawn/RESPAWN_LIGHTING.md), and
[source attribution register](docs/respawn/RESPAWN_SOURCES.md).

## Other tools
- [bsp_tool](https://github.com/snake-biscuits/bsp_tool)
    - A Python library for analyzing .bsp files

- [bsp_regen](https://github.com/snake-biscuits/bsp_regen)
    - `Titanfall -> Titanfall | 2` Map Converter

- [MRVN-Explorer](https://github.com/MRVN-Radiant/MRVN-Explorer)
    - A OpenGL/ImGui respawn bsp viewer
