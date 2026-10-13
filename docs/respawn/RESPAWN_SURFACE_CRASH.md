# Surface vertex range crash investigation

On October 7, 2026, the user reported a crash while grappling E1M1, plus older
crashes around grenade explosions and particles. Northstar 1.31.13 logged an
access violation at `engine.dll + 0xae74e` at 17:25:39. The matching local minidump
was inspected without modifying the executable or copying game binaries into the
project. The older explosion/particle failures have not been matched to dumps.

## Evidence

The faulting instruction reads a position using a 32-bit vertex reference:
`lddqu xmm1, [rbx + rcx*4]`, with `rcx = vertex_reference*3`. The invalid reference
is `0xb490b0d8`. Registers reproduce the logged invalid address exactly:
`0x234e9c21f00 + 12 * 0xb490b0d8 = 0x23d608a6920`.

The function reads a surface's first vertex at offset `0x0a`, last local vertex
index at `0x0c`, and material sort at `0x0e`. It adds the material-sort base to the
first vertex and loops `last_index + 1` times. The dump's surface at R12 contains
first vertex 4,984, last index 22,536, and material sort 1. These values match
generated BSP mesh 42, the wall material. Sort 1 starts at vertex 4,984; the bump
vertex pool contains 27,520 records. Thus the old surface path starts at 9,968
and attempts 22,537 records, exceeding the pool by 4,985 records.

The separate triangle-index path uses sort-relative indices and can render the
same mesh successfully, explaining why the geometry appears before the crash.
The surrounding projection routine is consistent with impact/decal processing;
there are no public symbols proving its function name. The range defect and the
matching crashing surface are established independently of that interpretation.

## Correction and verification

`Titanfall::EmitMeshes` now writes the first vertex relative to the selected sort
and writes `vertices.size() - 1` as the last local index. Material-sort allocation
still receives the actual vertex count. The corrected wall surface is first 0,
last 22,535, sort 1: the engine visits vertices 4,984 through 27,519 exactly.

The selected-record validator checks this inclusive range against the selected
vertex pool and requires every triangle index to belong to that surface range.
Tests cover a nonzero sort base, the old absolute-offset error, the inclusive
count error, and triangle indices outside a surface but inside the pool.
Retail TF2 Coliseum and Glitch pass these checks. The old E1M1 build fails on mesh
42; rebuilt version 0.2.1 passes. Compiler regression fixtures cover R1 and R2;
the existing Apex checks remain structural and do not establish gameplay safety.

The correction removes the demonstrated malformed data. In-game retesting is
still required for grapples, bullet impacts, grenade explosions and particles;
it does not establish that all older crashes share this cause. Lighting and other
unfinished BSP structures remain separate compatibility work.

## Attribution

Record-name/layout cross-checks used snake-biscuits/bsp_tool, commit
`655627ea8704353ac14bd753df8ca05c15838eda` (GPL-3.0), inspected locally. Its
`num_vertices` comment already notes the off-by-one behavior. The inclusive loop
and relative offset were independently confirmed against the user's installed
retail engine and crash dump. No upstream implementation was copied. The
validator, tests and compiler changes are original project code under the
project's GPL-2.0-or-later license. See [source attribution](RESPAWN_SOURCES.md).
