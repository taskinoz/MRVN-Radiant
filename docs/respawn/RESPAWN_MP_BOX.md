# BobTheBob's Titanfall Online mp_box port: repair and relighting

24 October 2026. Input: locally supplied `bobthebob.mp_box`, version `0.0.999`,
TF2 BSP v37 revision 30. Reference: the matching v29 `mp_box.bsp` in the user's
Titanfall Online `assets_dump`. Game and mod assets remain ignored local files.
The user reports flat lighting and weak shadows.

## Confirmed findings

- The embedded ZIP begins four bytes **before** the PAKFILE directory offset.
  The declared extent overlaps RTL lighting by one byte. Recovering its actual
  local-header and end-directory extent gives eleven CRC-valid files, including
  cubemaps and material patches. The repaired length remains 152,929 bytes;
  the offset changes from 8,675,300 to 8,675,296.
- The sprp entry has 77 converted 64-byte v13 records and no TF2 trailer. The
  outer GAME_LUMP also retains obsolete TF1 tail bytes. The repair appends a
  canonical directory/payload with the required zero unknown-record count.
  Existing file bytes remain preserved; inactive orphan bytes are unreferenced.
- Comparing each placement with the matching original proves that 26 scales
  were replaced by 1, all 77 forced-fade scales were changed from 1 to -1, and
  all 77 diffuse RGBA values were changed from white to zero. The original
  values are restored; model identity, positions and angles are checked first.
- All 5,898,240 bytes of the port's RTL atlas are `0xff`, and there is no RTL
  page table. In TF2 RTL A this encodes **unused light slots**, not a usable
  per-light shadow bake. Original v1 world lights retain TF1 flags (6 for local
  lights), while the port's copied shadow environments point at unrelated sun
  directions and cover only the first 1/31 CSM nodes and 2/13 shadow meshes.
- TF1's retained probe records and references have incompatible TF2 layouts:
  TF1 ambient-cube bytes are not TF2 directional coefficients; references are
  16 rather than 20 bytes. TF2 parent-info records are absent.

The render geometry, material strings, collision, portals, CSM tree and shadow
mesh data match the v29 source byte-for-byte. The existing selected-record,
triangle and portal cross-reference checks pass. Recompiling geometry is not
needed to repair these lighting and conversion defects.

## Original repair tools

`tools/respawn/repair_tf1_port.py` checks matching geometry and placement identity,
recovers and CRC-checks the embedded ZIP, restores known prop fields, and stages
a fresh copy of the mod. It never edits either input. It refuses unknown prop
sizes, compressed/sidecar inputs, placement mismatches and existing outputs.

`tools/respawn/relight_bridge.cpp` is a bounded binary adapter to the existing
native `Respawn::Bake` implementation in `lightbake.h`. Its RBL1 input is a
private tool protocol, not a game format. The Python front end passes existing
render charts/UVs, original light parameters, opaque collision brushes and
original probe-reference positions. Clip, trigger and sky brushes are excluded.
The adapter writes TF2 SKY/RTL planes, the RTL page table and new native probes /
references / KD tree. It does not recompile or modify geometry or UVs.

Rebuilding world lights preserves order, origin, intensity, cones, falloff and
direction, upgrades v1 to v3 records and uses TF2 realtime/shadow flags. Hardware
indices exclude ambient lights consistently in lights, RTL pages and probes.
The original complete CSM tree and shadow meshes are bound to the actual sun.
Static-prop probe indices are reassigned to the nearest newly baked samples.

```text
cmake -S tools/respawn -B BUILD_DIRECTORY
cmake --build BUILD_DIRECTORY --config Release --target relight_bridge
python tools/respawn/repair_tf1_port.py --mod PATH_TO_MOD --original PATH_TO_TFO_MP_BOX_BSP --output NEW_DIRECTORY --relight-bridge PATH_TO_RELIGHT_BRIDGE_EXE
```

This is a guarded repair for matching manual ports, currently packaged for
`mp_box`; it is not a general TF1-to-TF2 converter. Lighting rebakes currently
support one sun and existing atlas charts. Original inputs and archive assets
remain intact. The rebuilt mod retains its original author/name, adds a repair
version suffix, and is accompanied by a JSON report and hashes.

## Results and verification

- 62 chart meshes, 106 opaque brush occluders, 216,925 charted texels.
- 113,975 texels with realtime lights; one native RTL page table.
- Across two atlas pages: 121,339 active light slots, with 42,429 fully occluded,
  66,700 fully visible and 12,210 partially visible samples.
- 14,603 new TF2 probes/references and 4,095 KD-tree nodes, with parent info.
- Both atlas layouts, all 77 static props, collision and portal records validate.
- Native Northstar 1.31.13 server loaded the repaired map and completed ground
  and wall traces: ground end `(-944,-832,0.03125)`, fraction `0.333293`;
  wall end `(-1536.03,-384,64)`, fraction `0.0199902`.
- The local client connection was rejected by authentication. This is a server
  loading/collision smoke check, **not visual confirmation of the new lighting**.
  The user requested a package to test rather than further sign-in work.

Limits: occlusion uses world collision brushes; prop meshes and mesh-only
surfaces do not participate in the offline brush shadow bake. Native CSM data
is retained for runtime shadows. Seven TF1 32-bit prop contents-mask overrides
do not have an established mapping to TF2's two 16-bit fields, so the port's
values are retained and listed explicitly rather than truncated. Existing
navigation files, gameplay scripts, legacy VMT/VTF assets and the unrelated
resident STBSP catalogue are retained. Their presence is not a full asset,
navigation or gameplay compatibility certification.

## Attribution

- Original map/assets: Respawn/Nexon, from locally installed Titanfall Online.
- Manual TF2 port and mod: **BobTheBob**, original name `bobthebob.mp_box`.
- Repair code, adapter and existing light baker: MRVN-Radiant contributors,
  original GPL-2.0-or-later implementation, retaining the project's NetRadiant
  lineage and notices. No converter implementation was copied.
- Layout facts checked against **snake-biscuits/bsp_tool**, commit
  `655627ea8704353ac14bd753df8ca05c15838eda` (GPL-3.0), particularly sprp v12/v13
  and light-probe definitions. Upstream credits include rexx, BobTheBob and
  DTZxPorter. Schema facts informed original code; no GPL-3.0 implementation is
  incorporated.
- VPK inventory and CRC verification: **pg9182/tf2vpk**, commit
  `b73c54d8e4245075ea207c7e51a2a86fdb94e4ff` (MIT); the original VPKs are retained.
- ZIP member validation uses Python's standard-library `zipfile` implementation.
- Existing baker's encoding provenance and research credits remain in
  [RESPAWN_LIGHTING.md](RESPAWN_LIGHTING.md) and
  [RESPAWN_GRAVEMIND.md](RESPAWN_GRAVEMIND.md).

The repair-tool license does not relabel the supplied map, game assets or
BobTheBob's work. Those remain attributed separately.
