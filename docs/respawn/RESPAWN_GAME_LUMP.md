# TF2 game lumps and static placements

Recorded 22 October 2026. This work adds a bounded original reader for TF2 BSP
v37 `GAME_LUMP` (0x23), a version-13 `sprp` placement decoder, and conservative
directory relocation. It builds on the existing light baker and test mod 0.4.0;
it does not replace that work or establish complete BSP compatibility.

## Sources and version scope

- Local MRVN-Radiant `titanfall2.h` and `titanfall2.cpp` already describe/write
  these records. The new implementation is original GPL-2.0-or-later code.
- Gravemind `games/respawn/maps/binary-formats.md`, document
  `gm_01m4nftxmz4nmgdg2k2jb7hn40`, revision 2, read 22 October 2026: absolute game
  payload offsets, version dispatch and the 64-byte v13 placement layout.
  Recorded authors are `agent:Codex` and `agent:Claude` in the separate conversion
  project. Its referenced source files were not supplied or copied.
- Schema cross-check: snake-biscuits/bsp_tool commit
  `655627ea8704353ac14bd753df8ca05c15838eda`, GPL-3.0, Respawn `titanfall2.py`.
  That source credits BobTheBob for the placement layout and Legion developer
  DTZxPorter for scale identification. Only schema facts were consulted; no
  upstream parser implementation was copied or imported.
- Five local retail TF2 maps provide the measurements below. Game files and
  extracted assets remain outside Git. The inspector does not resolve model
  dependencies, reconstruct collision, or establish renderer behavior.

## Observed layout

The game lump starts with a uint32 directory count, then 16-byte descriptors:
`<4sHHII>` = stored identifier, flags, version, absolute payload offset, byte
length. The stored bytes `prps` identify `sprp`. Crucially, offsets in the default
external `.0023.bsp_lump` still use the outer BSP directory's virtual base;
they are not offsets relative to byte zero of the sidecar.

An unencoded v13 `sprp` payload contains:

1. uint32 model count and that many fixed 128-byte NUL-terminated model names;
2. three uint32 values: placement count and two still-unknown counters;
3. 64-byte placements, format `<7fH2B2H4f4b4B2H>`;
4. uint32 opaque-extra-record count followed by that many 64-byte records.

The two header counters are preserved, not guessed to equal placement count:
Colony reports `18056, 18035, 17937`, for example. Unknown extra records are
inventoried/hashed without assigning meanings to their contents.

| Byte | Placement field | Interpretation |
| ---: | --- | --- |
| 0 | 3 floats | Origin |
| 12 | 3 floats | Raw angle components, exported without reordering |
| 24 | float | Uniform model scale |
| 28 | uint16 | Model-name index |
| 30 | uint8, uint8 | Solid mode, flags |
| 32 | uint16, uint16 | Skin, cubemap (0xffff sentinel retained raw) |
| 36 | float | Fade scale; -1 occurs in retail |
| 40 | 12 bytes | Lighting-origin vector when flag 0x02 is set; otherwise opaque |
| 52 | 4 signed bytes | CPU/GPU level ranges |
| 56 | 4 unsigned bytes | Diffuse modulation |
| 60 | 2 uint16 | Collision masks; complete behavior remains unresolved |

### Conditional lighting-origin bytes

Treating bytes 40–51 as three always-valid floats rejects valid retail files.
Thousands of placements contain nonfinite bit patterns there. Across the tested
corpus, all such placements have flag `0x02` clear; no flagged vector is
nonfinite. Some inactive fields even contain string fragments. This supports
interpreting the vector only when that flag is enabled, consistent with the
upstream field/flag schema; the native read path has not been disassembled here.

The inspector exports inactive vectors as JSON `null`, retains their exact 12
bytes as hex, and reports the nonfinite inactive count. It never normalizes or
zeroes those bytes. Enabled vectors, origins, scales, angles and fade scales
must be finite. An unused NaN is not itself proof of malformed geometry.

## Retail evidence

All five effective game lumps are default external sidecars with one v13 `sprp`
entry and zero opaque extra records. Every placement's model index resolves.
Moving each blob's virtual base by 4096 and restoring it gives identical bytes,
including padding and inactive fields. This tests directory arithmetic, not an
in-game rewrite.

| Map | Model names | Placements | Inactive nonfinite lighting origins |
| --- | ---: | ---: | ---: |
| Coliseum | 3 | 3 | 0 |
| Colony | 738 | 18,056 | 107 |
| Glitch | 28 | 16,183 | 3,361 |
| Homestead | 307 | 16,146 | 1,508 |
| Live Fire Stacks | 68 | 2,200 | 152 |

Total: 52,588 placements, 5,128 inactive nonfinite vectors. The retained local
`.local/respawn/game-lump-corpus.json` records BSP/game-lump SHA-256 hashes,
counts, round-trip outcomes and selected validation results. All selected checks
pass, which does not establish complete engine compatibility.

## Tools and compiler corrections

```powershell
python tools/respawn/game_lump.py inspect path/to/map.bsp --placements --output props.json
python tools/respawn/game_lump.py relocate authored.bsp relocated.bsp
```

Inspection bounds directory counts, byte ranges, strides, model references and
known fields before exposing typed data. Unknown versions/flags remain opaque.
The normal `validate_records.py` path now includes these checks for TF2, while
TF1 and Apex do not silently inherit this schema.

The relocation command appends a relocated game lump and updates only its outer
directory offset. Other lumps and existing bytes retain their offsets. It refuses
sidecar-bearing files, existing destinations, unsupported game entries, opaque
extra records and inputs above 256 MiB. It does not compact an entire BSP or
rewrite unknown private pointers. Unknown versions can be inspected, never
silently relocated using a guessed v13 layout.

Native `EmitStaticProp` now preserves authored uniform `modelscale` (or uniform
`modelscale_vec`), `skin`, and the single `angle` yaw key. Visibility bounds use
the same rotated/scaled transform as the existing model compiler instead of
translation alone. Nonuniform scales are rejected because this format stores
one scalar. Model-name/skin/cubemap fields are unsigned 16-bit, and model-name
capacity and path length are checked before narrowing. `_cullradius` remains an
explicit world-space fallback hint for models without editor geometry.

The compiler regression builds an original OBJ triangle at origin `(256,128,16)`,
yaw 90, scale 2.5 and skin 7. It independently checks serialized placement fields
and expected world bounds `(256,128,16)`–`(266,148,16)`, relocates the result,
then revalidates unchanged payload hashes. This is an authored format/bounds
fixture; its OBJ is not a native game model. The game installation is unchanged.

Remaining work includes native prop model/material import, collision ownership,
probe-index relationships, complete unknown-field semantics and runtime tests.
