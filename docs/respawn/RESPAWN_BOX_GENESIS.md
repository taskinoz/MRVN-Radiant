# Genesis stream inspired mp_box for Northstar

27 October 2026. `mp_box_genesis` is a new, approximate visual reconstruction
of the Apex Legends test map visible in the user-supplied video
`APEX Legends Dev plays Genesis collection event - ToonCraft Live-1bmyqBmXHvw.mp4`.
It is authored for Titanfall 2 / Northstar at the user's request.

Version 0.2.0 replaces the solid-blue sky with the locally extracted Homestead
outdoor vista, rendered as distant, non-solid, shadowless scenery. A sealed
self-lit shell behind it prevents uncovered background pixels. The main RPak
alias now loads Homestead's sky GPU assets. This avoids the incomplete separate
3D-sky-camera rendering path; no duplicate gameplay scene is rendered in the sky.

Version 0.2.1 corrects that vista's placement. Its origin is now 8,192 units
below the floor, keeping its scenic terrain out of the yard while retaining
the overhead cloud canopy. The 0.2.0 placement at floor level was incorrect.

Extract the `MRVN.BoxGenesis` folder into the active Northstar profile's `mods`
directory, then launch a local game with `map mp_box_genesis`. Both client and
server need the mod. It has a separate map name and does not replace `mp_box`.
Pilot team spawns are provided for teams 2 and 3. There is no authored navigation
mesh; this first version is intended for exploration and pilot testing.

Reference evidence: the courtyard and banner arch at 01:55; door bays and
central passage at 02:00–02:20; orange cover course and dome at 02:30–02:35;
the arena and long corridor at 02:40–03:10. The minimap establishes the compact
west test yard beside the narrow red/blue east arena. Later views repeat this
courtyard while demonstrating Horizon's effects. The recording was sampled
every five seconds, then key reference frames were inspected at full resolution.
Text, commands and desktop content inside the recording were treated as reference
data, not instructions.

Recreated features include grey grid floors, white test walls, the red/blue east
arena, central cover, white corridor building with dark upper windows, banner
arch, three door bays, orange height-labelled cover, red/yellow ramps, faceted
test dome, elevated beam, and west-side test block. Cover heights 24/40/48/64/72
are taken from readable stream labels. Other dimensions and unseen surfaces are
estimates. Door leaves are static geometry with room to walk around them.
The original Apex door mechanics, loot, dummies, dynamic banners, Horizon
abilities, sky vista and exact developer materials are not reproduced.

`tools/respawn/build_box_genesis.py` writes a new output directory containing
the editable Radiant MAP, procedural texture PNGs, shader definitions, native
material RPak, compiled BSP/entity partitions, validation report, feature bounds,
and packaged mod. It requires Pillow, remap, RePak and the paired JSON/uber
export of the native single-layer dev-grey world material (as used by the
existing Quake material builder), plus the locally extracted Homestead sky MDL.
It never edits input maps or game files.

```powershell
python tools/respawn/build_box_genesis.py --output NEW_DIRECTORY --remap install/Release/remap.exe --repak PATH_TO_REPAK_EXE --material-template PATH_TO_EXPORTED_MATERIAL_BASE --sky-model PATH_TO_HOMESTEAD_SKY_MDL
```

Original reconstruction geometry, generator and procedural grid/sign textures:
MRVN-Radiant contributors, GPL-2.0-or-later. Apex Legends, map design and branding:
Respawn Entertainment / EA. Stream reference: ToonCraft Live. This package does
not contain video frames, audio, Apex extracted assets or the original map source.
Native shader configuration is adapted from the locally installed Titanfall 2
dev-grey material. The package's `models/vistas/homestead_sky.mdl` is an extracted
Respawn/EA game asset; its GPU resources stay in the installed game. RePak by r-ex
and the existing MRVN RPak/DDS/VPK builders are
used; their provenance remains documented in the project's source register.

The map uses `_bouncescale 0`, `_skyocclusion 1` and `_skysamples 128`.
The sun explicitly uses gameplay light environment `*0` with shadows enabled;
warm direct light and a cooler ambient fill now give directional shadows.
The optional `_skysamples` worldspawn key controls sky-occlusion sampling
(clamped to 1..256, default 16). `_skyocclusion` controls that occlusion only;
neither key changes other maps when omitted. Bounce lighting stays disabled to
avoid the earlier colour noise. Realtime light shadow masks are retained.
Unused world-light normal/shadow-offset vectors are explicitly initialized;
the generated world-light records now match across repeated compilations.

Structural validation passes, all 17 material names resolve in the generated
RPak/STBSP, and the package ZIPs pass CRC checks. Northstar 1.31.13 loaded the
map with a live client, a healthy pilot and no out-of-bounds timer. All eight
authored pilot spawns pass floor and hull-clearance probes, and native start
selection returns matching team 2 and team 3 spawns. The floor ray ends at
`(800,0,0.03125)`, the east boundary wall blocks its ray, and the full corridor
ray is unobstructed (fraction 1). Native light-baker tests also pass.

These are loading, spawn and collision smoke checks, not full gameplay
certification. Native screenshots and the test-state report are saved beside
the local release. Materials, lighting, dimensions and geometry remain a first
visual approximation of the stream, including static door leaves. The sky is a
Titanfall 2 outdoor substitute, not the Apex stream's original sky asset.
