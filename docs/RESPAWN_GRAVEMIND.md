# Gravemind conversion research cross-check

Read on 11 October 2026 through the user-authorized Gravemind MCP service at
`http://gravemind.local/mcp`. Authentication stays outside project files. The
articles describe the separate Apex-to-Titanfall conversion project, specifically
tested Apex rBSP 47 and TF2 rBSP 37. Their `verified` status is the source's status,
not an independent compatibility certificate for MRVN-Radiant or all Apex seasons.

## Attribution and revision provenance

All articles below are recorded as authored/updated by `agent:Codex` in Gravemind,
project `apex-to-titanfall-2`. No conversion implementation was copied. Only
technical facts, measurement provenance and concise research notes inform the
original project code. The article references point to files in the conversion
workspace; those files were not supplied by the MCP service or examined here.

| Article path under `games/respawn/maps/` | Document ID | Revision |
| --- | --- | ---: |
| `index.md` | `gm_01m4nfrrht11q492zdc2qynfs0` | 10 |
| `visibility-and-limits.md` | `gm_01m4nfvbskvsb60d8mw81t2qjd` | 1 |
| `lighting.md` | `gm_01m4nfw145wpegeck18agcewhz` | 1 |
| `binary-formats.md` | `gm_01m4nftxmz4nmgdg2k2jb7hn40` | 1 |
| `materials-and-streaming.md` | `gm_01m4nfvnsprv0ymngbh25c2hz2` | 1 |
| `collision.md` | `gm_01m4nfv1snwem6gvwd6yhe65t9` | 1 |
| `testing-and-packaging.md` | `gm_01m4nfwwnxq30rgpr6w7490ka2` | 1 |

## Independently checked engine identity and capacities

The installed engine SHA-256 is
`58eb1a1b44b30275bdd21368de264d856bc310d37d93a0f76f111f0026913487`;
client SHA-256 is
`002b36487fec7c98882929fbccdb506d0146bbf3270cbb964a4d21c5edf7eebc`.
Both exactly match the source's tested binaries. Read-only disassembly confirms
`engine.dll + 0xB72AF` compares submitted world indices to `0x300000` (3,145,728),
and `+0xB7304` checks batch count against `0x800` (2,048).

The article reports per-mesh cost `3 * (triangles + (triangles & 1))`, including
disabled triangle slots, and an 8,192-material-sort loader capacity. Those two
interpretations have not independently been re-audited here. Native field ranges
alone are insufficient to prove engine capacity. Project margins such as 90%,
95%, 60,000 local vertices or 96-triangle groups are policies, not format limits.

The original read-only `audit_tf2_budget.py` tool reports conservative all-visible
world-model cost, applies the known capacities only for the exact engine hash,
and identifies the source-only measurements. It does not infer draw batches from
mesh count, certify runtime effects, or impose this profile on TF1/Apex.

```powershell
python tools/respawn/audit_tf2_budget.py path/to/map.bsp --engine C:/Games/Titanfall2/bin/x64_retail/engine.dll
```

The E1M1 0.2.1 test reports 41,226 estimated padded world indices (1.31% of
capacity), 43 meshes and two material sorts. Thus the world-index estimate gives
no indication of capacity pressure for that build; it does not rule out defects
in effects, collision, surface ranges or lighting. Retail Coliseum and Glitch
also pass the audit's selected checks. The Python suite passes 60 tests.

## Lighting work informed by the articles

The source reports SKY A RGBM decoding as `rgb * (alpha * 3.984375 + 0.015625)`
and SKY B direction as `rgb * 2.007874 - 1`, using normalized channels. RTL IDs
address a filtered hardware light table, not WORLD_LIGHTS positions; ambient
entries change that mapping. Character probes also have native reserved offsets.
These formulas/mappings remain research inputs until independently shader-tested
here; the current raw-plane inspector and experimental writers retain their
existing unverified status.

Next implementation needs explicit hardware light remapping, probe spatial
structures, normalized chart UVs and correct material-sort page bindings. Dense
receiver samples and per-chart gutters matter: copying the nearest sample from
another chart can contaminate shadows. Physical menu anchors, geometry, lights
and probes need coordinated separation from gameplay, rather than moving only
the camera. The Quake test's remote anchors alone do not establish full isolation.

## Other compatibility work

The material article distinguishes STBSP material catalogues from texture
STARPaks and requires dependency closure for native shader/pass assets. A material
name or a valid GUID alone does not establish a usable cold-load dependency chain.
The collision article preserves source ownership, coordinate frames and primitive
types; whole-prop bounds can obstruct concave passages. Its Apex BVH and PHY
layouts need exact version dispatch and independent sample checks here.

The packaging article requires cold launch, stock-map reload and native gameplay
tests as well as structural validation. Conservative all-visible structures are
a documented fallback; selective portal graphs and complete spatial texture
streaming remain unvalidated. None of these readings establishes a complete
MRVN-Radiant light baker, shader pipeline or converter.

## Original findings published to Gravemind

With the user's authorization, two original articles were added on 12 October
2026 under `games/respawn/mrvn-radiant`. Both are revision 1 drafts, preserving
the distinction between established binary defects/checks and pending game tests:

- `surface-range-crash.md`, document `gm_01m4nk3k1wfg5d44f7k7qnvxpx`: the grapple
  dump evidence, sort-relative inclusive vertex ranges, compiler correction,
  regression coverage and remaining effects-crash retest.
- `budget-audit-and-tool-status.md`, document `gm_01m4nk3n4xbmnp8dwmb3sxezk3`:
  independent engine identity/capacity checks, original budget auditor, E1M1
  measurements and the current unverified native-lighting scope.

Existing conversion articles remain unchanged. The articles link to their
research sources and cite project-relative evidence; no credentials, game assets
or raw crash dumps were uploaded.
