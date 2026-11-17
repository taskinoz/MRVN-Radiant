# TF1/R1Delta and TFO navigation export and integrity

Checkpoint: 18 November 2026. **Two controlled grunt obstacle fixtures pass in
both runtimes. Full AI/navigation and Phase 2 release acceptance remain open.**

The scoped workflow now builds an AIN in an owned R1Delta session, calculates its
expected entity CRC offline and stages a new graph copy for fresh-load testing.
It does not require copying a CRC from a live process or modifying an installed
graph. This supersedes the map-specific CRC preparation limitation in the
[Phase 2 log](RESPAWN_TF1_PHASE2.md).

## Supported scope

- Little-endian authored BSP v29 with embedded, uncompressed lump payloads.
- Declared `01*` partitions with well-formed `ENTITIES01` sidecars.
- Simple quoted navigation entities: the case-sensitive `info_node` prefix,
  exact `info_hint`, `traverse` and `trigger_indoor_area` classes.
- Native-exported v54 graphs. The helper checks header/revision/node framing;
  ARES performs additional finite-node and link-endpoint checks.
- The exporter checks actual R1 engine/server SHA-256 against the pinned profile
  before staging or launching. Other builds fail explicitly.
- Linked input files, external BSP lump overrides, compressed lumps, duplicate
  classname keys, escaped or oversized selected navigation tokens are rejected.

A CRC match does **not** establish that a graph describes the current geometry.
Use the native exporter after geometry/node changes. Applying a new header CRC
to a stale graph is not graph regeneration or route acceptance.

## Commands

Run from MRVN-Radiant with the matching ARES checkout. Run native game sessions
sequentially and never stop an unowned client/server. Outputs must be new paths.

```powershell
python tools/respawn/prepare_tf1_navigation.py --remap install/Release/remap.exe --output .local/respawn/my-nav-source
# Read layout.json for the generated map name, then substitute it below.
python tools/respawn/build_tf1_navigation.py --ares ../ARES --maps .local/respawn/my-nav-source/maps --map GENERATED_MAP_NAME --output .local/respawn/my-nav-package
python ../ARES/harnesses/adapters/r1_harness.py --maps .local/respawn/my-nav-package/maps --map GENERATED_MAP_NAME --checks .local/respawn/my-nav-source/checks.json --output .local/respawn/my-nav-r1
python ../ARES/harnesses/adapters/tfo_harness.py --game "D:/Games/Titanfall Online" --maps .local/respawn/my-nav-package/maps --map GENERATED_MAP_NAME --checks .local/respawn/my-nav-source/checks.json --output .local/respawn/my-nav-tfo --enable Titanfall1.Content.Client --enable Titanfall1.Content.Shared
```

The exporter requires ARES's explicit `AIN_BUILD_FLAG` capability. It sets only
the owned session's `build_navigation` boolean, adding
`-r1delta_build_ain_no_existing` to enable the native initialization hook.
Ordinary harness launches do not acquire that flag. It invokes non-legacy
`updateain` with a new explicit private path, retains the original native graph,
creates an adjusted copy under `maps/graphs/<map>.ain`, and records hashes and
native export status. Failure and success both restore the hook and clean the
owned addon. Successful export is not a routing pass.

Inspect a supplied graph without changing it:

```powershell
python tools/respawn/tf1_navigation_crc.py --bsp BUILD/maps/MAP.bsp --graph BUILD/maps/graphs/MAP.ain --output NEW_REPORT.json
```

A mismatch returns 1; a match returns 0. `--output-graph NEW_FILE.ain` explicitly
creates an adjusted copy, changing only the CRC. Existing outputs, including the
source, are never overwritten. Tail/script and graph semantics remain separate.

## Engine-derived calculation

This is original standard-library code from read-only inspection of supplied
binaries and source. No third-party parser or native implementation was copied.

R1's engine CRC routine at RVA `0x101690` sorts 128 lump IDs by physical file
offset (comparator `0x1014a0`), skips ENTITIES (0) and ENTITY_PARTITIONS (24),
and processes other nonempty payloads. The stored CRC32 state is initialized
with `0xffffffff` and has **no final XOR**. Directory-index order produces an
incorrect result for our compiler output.

The server validator at `0x364b80` obtains that state and calls the selected-
entity update at `0x364720` (class filter `0x364650`). Selected raw spans start
immediately after the opening brace and end after the final value token,
excluding the closing brace and trailing whitespace. Internal raw whitespace
affects the CRC. Behavior outside the supported tokenizer subset is unverified.

| Pinned binary | SHA-256 |
| --- | --- |
| R1 engine | 0214a40436eca77f160d12763ab8f392a8ce2268bfe0a973188e426ae4c0263c |
| R1Delta server | 50faad928e0715a51ad624d0a3eb8f00f7ffad9e66258dc95c960f9d11ff41e4 |
| TFO engine | 39e2a1c83b7bea3fa1a2f98ecc6cde3016e3567a1bc89cf8926d8a613dc62ad1 |
| TFO server_local | 8dabdd4f46218bdd72bd9c4ea53d24178c7974ec4277f6872f671ac1fe99dd7b |

Independent read-only observations of **owned** processes:

| Fixture | Offline base CRC | Offline entity CRC | Native comparison |
| --- | ---: | ---: | --- |
| Original eight-node pillar | 2011031715 | 4285011719 | R1 file/expected CRC equal; computed flag 1 |
| Wider pillar and shifted southern nodes | 2027006736 | 1916430116 | R1 and TFO file/expected CRC equal; computed flag 1 |

R1's manager pointer is at server RVA `0xc31898`; fields start at manager+
`0x64c`. The supplied TFO server uses pointer `0x10900d8` and fields at
manager+`0x684`; its validator is `0x63ee90`. These offsets belong to private
profile-specific diagnostics, not a generic public memory interface. No process
memory or installed binary was written, and no integrity check was disabled.
TFO's developer-dependent rejection was not separately exercised with a
deliberately wrong graph; its computed expected value was read and compared.

## Paired results and limits

Both fixtures have eight nodes. The variant pillar spans
(-80,-160,0)..(80,160,192), with three southern nodes moved to y=-288.
The public exporter creates a 949-byte graph with eight nodes and 14 links.

Original and variant packages each pass fresh R1Delta 3.0.5 and TFO Core135 runs:
loaded/finished true, no errors, 12 living navigation samples, valid floor and
forbidden-volume checks, and final hold at (400,0,0.03125). The variant's
forbidden volume is (-96,-176,-1)..(96,176,192). Native assault goals drive the
grunt; no post-spawn NPC repositioning is used.

Private evidence is under `.local/respawn/phase2-navigation-crc/`:

- `r1-base-diagnostic/`: original route and native base/header state.
- `package/`: original graph adjusted by the offline tool.
- `r1-offline-package/` and `tfo-offline-package/`: original route reports.
- `variant-source/`: changed source, new hashes and structural checks.
- `variant-export/`: public export, native report and graph manifest.
- `r1-variant-route/` and `tfo-variant-route/`: changed-fixture route reports.
- `r1-variant-native/` and `tfo-variant-native/`: native CRC observations.
- `tfo-crc-control/`: additional fresh route used for TFO's CRC observation.
- `cli-checks.json`: mismatching/matching graph inspection returns 1/0.

Controls explicitly enable NPCs and disable movement starts and squad following.
They do not prove default AI, every intervening frame, continuous swept
collision, other hulls, broader/dynamic routes, combat or titan piloting.
AIN tail/script semantics, broader format variants and full Phase 2 gameplay,
visual and packaging release gates remain open.

Synthetic tests cover physical order, excluded/padding bytes, raw entity spans,
node edits, partition order, rejected layouts and exclusive graph copies.
Export tests cover owned-session cleanup, hook restoration, explicit
initialization, unknown-profile rejection and refusal to overwrite outputs.
The latest MRVN suite runs 278 tests; ARES runs 173 adapter tests with one skip.
All 17 focused R1 adapter tests pass.

## Repeated bidirectional routing (18 November checkpoint)

Late 17 November native runs additionally pass two round trips on changed fixture
`mp_ares_nav_64d4ee22` in both runtimes. Each run uses one living grunt for
four alternating goal/return legs, 12 movement samples per leg (48 total), and
four leg-start poses. Each leg must independently reach and hold its target for
its final two samples; forward success cannot mask a failed return or later leg.
The returns finish within the configured 24-unit radius, not necessarily at the
exact requested coordinate. The grunt is spawned once and never repositioned.

`navigation_probe.round_trips` is optional: 0 retains the legacy one-way
format; 1..3 requests that many goal/return pairs. The sampled route duration is
bounded to 180 seconds. Indexed leg events, living state, initial/leg-start
positions, floor and forbidden volume are checked on every leg. The R1 adapter's
wait includes all legs. Invalid, duplicate, missing and incomplete leg data fail.

`prepare_tf1_navigation.py --round-trips 2` now emits these checks. Its new
original public fixture compiled and passed structural validation; repeated native
evidence here uses the separately identified changed-pillar graph.

Private reports/checks and a compact summary are under
`.local/respawn/phase2-navigation-repeat/`: `r1/report.json`,
`tfo/report.json`, `checks.json` and `summary.json`. Both reports have
loaded/finished true and no errors. The current MRVN suite still has 278 passing
tests; the ARES adapter suite runs 170 tests with one skip.

This advances repeated static routing for the human hull only. Changing a goal
is not a dynamic-obstacle test. Default AI/animation settings, other hulls,
combat, continuous swept collision and general navigation remain open.

## Atlas NPC goal/return routing (18 November)

The shared probe now accepts `actor: "atlas"` as well as the default grunt.
It creates an actual native titan through `CreateSpawnNPCTitanTemplate` and
`SpawnNPCTitan`: R1 uses `titan_atlas`, TFO uses `titan_atlas_tier0`.
Connectivity queries use `HULL_TITAN`. A required native actor event records
`IsTitan()==true` and finite ordered bounds larger than the human hull.
Sampled floor support uses origin plus the recorded bounds minimum Z.

On changed fixture `mp_ares_nav_64d4ee22`, the final public probe passes one
goal/return pair in both runtimes: one atlas NPC, 20 movement samples per leg,
and independent living/clearance/arrival/hold checks on each leg. Both report
bounds (-60,-60,0)..(60,60,235). The forbidden origin box is expanded to
(-144,-224,-1)..(144,224,400) to account for the larger actor. This is a sampled
clearance check, not continuous swept contact-mesh certification.

Example configuration additions:

```json
{"actor":"atlas","round_trips":1,"samples":20,
 "forbidden_box":[[-144,-224,-1],[144,224,400]]}
```

These fields supplement the existing start/goal/nodes/floor fields.
`prepare_tf1_navigation.py --actor atlas --round-trips 1` emits actor-specific
checks with clearance appropriate to its own original, smaller pillar. That
fresh generated source compiles and validates structurally; the native evidence
above uses the separately identified changed-pillar package.

### Retained fixed-facing failure and final control

The initial shared implementation passed `Vector(0,0,0)` as arrival angles
on every leg. The supplied `CreateStrictAssaultEnt` helper interprets a
non-null angle as a request to face that direction at the goal. R1 passed that
atlas control, but TFO reached the return area and repeatedly moved away; its
final return hold failed. The failing report is retained as
`phase2-atlas-navigation/tfo-public/report.json`.

The final atlas navigation probe passes `angles=null` through the supplied
helper, leaving arrival facing unspecified. This does not change radius, floor,
clearance, sampled duration or final hold requirements. Both final public runs
pass with those unchanged assertions. Grunt behavior retains its previous
argument. Fixed-facing TFO return behavior remains unverified/unresolved;
the control does not prove a BSP writer defect or its sole cause.

Evidence under `.local/respawn/phase2-atlas-navigation/`:

- `r1-first/`: initial one-way private atlas observation.
- `r1-public/` and `tfo-public/`: original fixed-facing goal/return controls.
- `r1-no-facing/` and `tfo-no-facing/`: final public configuration, both pass.
- `checks-public.json`, `initial-summary.json` and `paired-summary.json`:
  exact parameters, retained failure and final native/source fingerprints.
- `public-fixture/`: generator output with atlas-specific clearance checks.

The 278 MRVN tests pass. ARES runs 173 adapter tests with one skip; all 15 focused
navigation tests pass, including actor type/bounds and per-runtime settings.
This advances actual atlas NPC navigation beyond the previous floor-only sample.
Piloting, combat, default AI/animation settings, other titan types, dynamic
obstacles, broader maps and fixed-facing acceptance remain separate open gates.
