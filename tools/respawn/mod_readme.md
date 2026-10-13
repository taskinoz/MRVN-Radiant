# MRVN Quake E1M1 test map

Quake's E1M1, compiled to a Titanfall 2 BSP by MRVN-Radiant's experimental
Respawn writer. This is a compiler test, **not a complete Quake port**: Quake's
doors, lifts, liquids, items and monsters are not included, and there is no
navigation mesh.

## Quick start

1. Close Titanfall 2. Unzip so the `MRVN.QuakeE1M1Test` folder sits in
   `Titanfall2/R2Northstar/mods`, replacing any older copy.
2. Start Northstar, check that `MRVN.QuakeE1M1Test` is enabled in the Mods menu,
   and start a private match. Then run `map mp_quake_e1m1` in the console.
3. Everyone who joins needs the same mod version installed; Northstar does not
   download it for them.

What to expect:
- LibreQuake textures, baked lighting with one light bounce, and a static sun.
- The map is wrapped in a sky shell, like retail maps, so death cameras and
  shots into gaps hit sky instead of the void.
- Titans are disabled: without a navmesh, Titanfall's drop code finds no spawn
  point and the script errors out.
- Pilot movement, weapons, grapples and grenades work in testing so far.

Please report crashes (with the time and what you were doing), z-fighting or
flickering surfaces (`cl_showpos 1` shows your position), holes, and areas
that look wrong or too dark.

## Sources and licenses

- Quake E1M1 / The Slipgate Complex: id Software, map by John Romero; source
  released by John Romero in October 2006. Retrieved from
  [fzwoch/quake_map_source](https://github.com/fzwoch/quake_map_source/tree/27abebaa3886bb0e3156cce3a604673d22b243f8),
  commit `27abebaa3886bb0e3156cce3a604673d22b243f8`. GPL-2.0; `COPYING`, original
  source and adapted MAP source are included. No original Quake WAD images are included.
- Textures: converted from the [LibreQuake](https://github.com/lavenderdotpet/LibreQuake)
  texture WADs; BSD-style license in `LICENSE-textures.txt`.
- Compiler: MRVN-Radiant / remap, including its NetRadiant lineage and Respawn
  format research attribution in `docs/respawn/RESPAWN_SOURCES.md` in the
  MRVN-Radiant repository.
- VPK layout and independent verification:
  [pg9182/tf2vpk](https://github.com/pg9182/tf2vpk/tree/b73c54d8e4245075ea207c7e51a2a86fdb94e4ff),
  commit `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff` (MIT). The package writer is
  original MRVN-Radiant GPL-2.0-or-later code; tf2vpk is not bundled.
- Mod structure, VPK mounting and RPAK alias behavior:
  [Northstar documentation](https://docs.northstar.tf/Modding/guides/gettingstarted/),
  [RPAK documentation](https://docs.northstar.tf/Modding/guides/tools/rpakmodding/),
  [NorthstarLauncher mod manager](https://github.com/R2Northstar/NorthstarLauncher/blob/42c635aef4929a8c8eaf4ee790efb6fa34ac56cc/primedev/mods/modmanager.cpp)
  and [map discovery](https://github.com/R2Northstar/NorthstarLauncher/blob/42c635aef4929a8c8eaf4ee790efb6fa34ac56cc/primedev/util/printmaps.cpp),
  source commit `42c635aef4929a8c8eaf4ee790efb6fa34ac56cc` (MIT), inspected locally
  to diagnose the 0.1.0 map-command rejection. No source or binary is bundled.
  No Northstar code is copied into the test script. Checked against the local
  Northstar 1.31.13 installation; no script VM or engine validation was performed.
