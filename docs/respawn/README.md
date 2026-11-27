# Respawn research notes

Notes on Respawn's map formats and the fork's compiler and converter work. They
were written with AI alongside the code; see [AI.md](../../AI.md). Each note
says what was tested in game and what wasn't. The tools are indexed in
[tools/respawn](../../tools/respawn/README.md).

## Start here

- [GOALS.md](GOALS.md): the goal list for retail-compatible, retail-complete
  maps in TF1 (R1Delta), Titanfall Online, TF2 (Northstar) and Apex S3
  (R5Reloaded, with S0–S2), with R5Flowstate as release 1.1.
- [SOW_COMPATIBILITY_TRACKER.md](SOW_COMPATIBILITY_TRACKER.md): the closed
  24 November 2026 scope of work. It and the other `SOW_*.md` files are kept as
  the evidence record behind the goal list.
- [RESPAWN_MAP_SUPPORT_AUDIT.md](RESPAWN_MAP_SUPPORT_AUDIT.md): 17 November 2026
  TF1/R1Delta, TFO and TF2 engine/game-file review, support matrix and measured limits.

- [RESPAWN_COMPATIBILITY.md](RESPAWN_COMPATIBILITY.md): current gaps, release
  gates and how to inspect a BSP.
- [RESPAWN_SOURCES.md](RESPAWN_SOURCES.md): who and what the research and tools
  draw on.

## Compiler and formats

| Note | Covers |
| --- | --- |
| [RESPAWN_APEX_S3.md](RESPAWN_APEX_S3.md) | Apex S0–S3 compiler: r5valkyrie backend port, S3 native tests, season comparison, open work |
| [RESPAWN_APEX_FORK_REVIEW.md](RESPAWN_APEX_FORK_REVIEW.md) | Pinned r5valkyrie fork review, initial Apex metadata fixes and season/schema limits |
| [RESPAWN_TF2_LUMPS.md](RESPAWN_TF2_LUMPS.md) | Cubemaps, probe BSP, CSM objects, collision primitives and noded triangle collision |
| [RESPAWN_TF1_LUMPS.md](RESPAWN_TF1_LUMPS.md) | Titanfall 1 lighting, tangents, cubemaps, VPhysics, portals and testing in Titanfall Online |
| [RESPAWN_TF1_NAVIGATION.md](RESPAWN_TF1_NAVIGATION.md) | Native AIN export, offline CRC packaging and two paired grunt route fixtures |
| [RESPAWN_TF1_PHASE2.md](RESPAWN_TF1_PHASE2.md) | Phase 2 parity checklist, remaining tasks and reproducible TFO baseline |
| [RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md) | Lightmaps, sun, probes and the baker |
| [RESPAWN_BUILD_PERFORMANCE.md](RESPAWN_BUILD_PERFORMANCE.md) | Compiler speed, memory, worker budgets and before/after output checks |
| [RESPAWN_TRICOLL_PORTALS.md](RESPAWN_TRICOLL_PORTALS.md) | Triangle collision and view portals |
| [RESPAWN_GAME_LUMP.md](RESPAWN_GAME_LUMP.md) | Game lumps and static prop placement |
| [RESPAWN_SURFACE_CRASH.md](RESPAWN_SURFACE_CRASH.md) | The surface vertex range crash and its fix |
| [RESPAWN_SAMPLES.md](RESPAWN_SAMPLES.md) | Retail sample evidence |
| [RESPAWN_MAP_TRIALS.md](RESPAWN_MAP_TRIALS.md) | Compiling known maps; Coliseum recovery |
| [RESPAWN_DECOMPILE.md](RESPAWN_DECOMPILE.md) | Recovering TF2 scenes as editable maps |
| [RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md) | Cross-check against the shared research knowledge base |

## Map conversions

| Note | Covers |
| --- | --- |
| [RESPAWN_NORTHSTAR_TEST.md](RESPAWN_NORTHSTAR_TEST.md) | Quake E1M1 test mod |
| [RESPAWN_MINECRAFT_PORTS.md](RESPAWN_MINECRAFT_PORTS.md) | Minecraft world converter (UMA, Glitch, Survival Games): terrain, glass, water, redstone |
| [RESPAWN_SOURCE_PORTS.md](RESPAWN_SOURCE_PORTS.md) | Source 1 and CS2 converters (Trainstation, Jump Academy 2, Nuke) |
| [RESPAWN_MATERIAL_TEMPLATES.md](RESPAWN_MATERIAL_TEMPLATES.md) | Translucent and alpha-tested world materials from retail Coliseum; decoding v7 paks |
| [RESPAWN_BOX_GENESIS.md](RESPAWN_BOX_GENESIS.md) | Authored `mp_box` test yard |
| [RESPAWN_MP_BOX.md](RESPAWN_MP_BOX.md) | Repairing and relighting a Titanfall Online port |
| [RESPAWN_TF2_TO_APEX.md](RESPAWN_TF2_TO_APEX.md) | TF2 to Apex geometry port |
| [RESPAWN_R5_HARNESS.md](RESPAWN_R5_HARNESS.md) | Local R5Reloaded test harness |

The finished maps, their recipes and releases are in
[Titanfall-2-Custom-Maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps).
