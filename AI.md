# AI disclosure

This is a fork of MRVN-Radiant. **The original, human-built MRVN-Radiant is
[MRVN-Radiant/MRVN-Radiant](https://github.com/MRVN-Radiant/MRVN-Radiant)**, itself
built on NetRadiant-custom and GtkRadiant. Use it for the editor as its authors
made it.

## What AI changed here

The fork's own changes, made from October 2026 onwards, were produced with AI:
Anthropic's Claude (through Claude Code), with some earlier work by OpenAI's
Codex. The maintainer, Tristan Kennedy, directed the work, tested builds in
Titanfall 2 and reviewed what was kept. Commits written this way carry a
`Co-Authored-By: Claude` trailer.

AI wrote:

- the Respawn research tools, converters and tests in `tools/respawn/`;
- the research notes in `docs/respawn/`;
- changes to the `remap` compiler in `tools/remap/source/` (Titanfall 2
  lighting, collision, visibility, portals, meshes and BSP writing);
- the Titanfall 2 entity definitions and prefabs in `install/gamepacks/`;
- build and CI wiring for the new tests (`CMakeLists.txt`, `.github/workflows/`).

Everything else, including the Radiant editor, is the upstream human-written code.
To see exactly what the fork changed, compare it with upstream:

```bash
git fetch https://github.com/MRVN-Radiant/MRVN-Radiant.git main
git diff FETCH_HEAD...HEAD --stat
```

The badge in the README is a self-declaration. It is not a quality rating or a
security review. Maps made with these tools are in
[Titanfall-2-Custom-Maps](https://github.com/taskinoz/Titanfall-2-Custom-Maps), and
its [AI disclosure](https://github.com/taskinoz/Titanfall-2-Custom-Maps/blob/main/AI.md)
links to each original map.
