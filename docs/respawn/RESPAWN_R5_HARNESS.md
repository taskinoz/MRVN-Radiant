# Local R5 map harness

`tools/respawn/r5_harness.py` controls the installed R5Reloaded SDK 2.3 through
its native netconsole. It launches the dedicated executable without a game
window, loads maps, selects game modes and playlists, runs console/Squirrel
commands, and returns structured readiness results over local HTTP.

This tests server loading, scripts and collision. It does **not** certify client
rendering, lighting, sky or dome appearance. A rendered client still needs a
separate visual check.

## Start the controller

From the repository root, with Python 3.10 or newer:

```powershell
python tools/respawn/r5_harness.py --game "F:/Games/Apex Detours/R5Reloaded" --state-dir .local/respawn/apex-port/harness
```

HTTP binds to `127.0.0.1:39300`; legacy netconsole binds to `[::1]:37025`.
`--port` and `--game-port` select different ports for another controller.
The controller prints its URL and the path of `connection.json`. That local
file contains the HTTP bearer token. The helper reads it without putting the
token into shell arguments.

```powershell
python tools/respawn/r5_harnessctl.py --connection .local/respawn/apex-port/harness/connection.json boot '{"mode":"dedicated","playlist_file":"playlists_mrvn_coliseum.txt"}'
python tools/respawn/r5_harnessctl.py --connection .local/respawn/apex-port/harness/connection.json load '{"map":"mp_mrvn_coliseum_s3","playlist":"mrvn_coliseum","gamemode":"tdm"}'
python tools/respawn/r5_harnessctl.py --connection .local/respawn/apex-port/harness/connection.json command '{"text":"status"}'
python tools/respawn/r5_harnessctl.py --connection .local/respawn/apex-port/harness/connection.json state
python tools/respawn/r5_harnessctl.py --connection .local/respawn/apex-port/harness/connection.json stop
```

`boot` also accepts `"mode":"client"` for the rendered executable. Dedicated
mode is the unattended path verified here; booting the rendered executable
does not itself prove that its title-screen connection gate was passed.

## Repeatable native checks

```powershell
python tools/respawn/r5_harness_smoke.py --connection .local/respawn/apex-port/harness/connection.json --map mp_mrvn_coliseum_s3 --playlist mrvn_coliseum --gamemode tdm --report .local/respawn/apex-port/harness/native-smoke.json --boot --reload --coliseum-checks
```

Omit `--boot` when the owned server is already running. `--reload` requests a
second load in the same process. Each load must observe a **new SERVER VM**,
then a Squirrel probe reporting the requested map, generated playlist, actual
game mode and `EntitiesDidLoad=true`. A still-running previous map cannot
satisfy that check. The optional Coliseum probes compare five floor rays and
three dome rays with independently recovered source geometry fractions.

The JSON report records failures as well as successes. `render_verified`
remains false. Missing navigation or model warnings remain visible in filtered
events; successful readiness does not mean those assets have been converted.

## HTTP interface

All requests require `Authorization: Bearer <token from connection.json>`.
POST bodies are JSON objects, at most 32 KiB. There is no CORS allowance.

| Method | Endpoint | Body / result |
| --- | --- | --- |
| POST | `/boot` | `mode`, `playlist_file`, optional `timeout` |
| POST | `/load` | `map`, `playlist`, `gamemode`, optional `timeout` |
| POST | `/command` | `text`, optional `timeout`; native output and acknowledgement |
| GET | `/state` | Child PID, liveness, exit code, console state, last load, short crash header |
| GET | `/events` | Latest 100 filtered native events |
| POST | `/stop` | Gracefully quit, then terminate only this controller's child if needed |

The native 2.3 command is `reload_playlists`. The newer SDK's
`playlist_reload` name is not interchangeable. Legacy RCON uses a big-endian
32-bit frame size followed directly by a protobuf message, without the newer
encrypted envelope. Requests put the command name in field 4 and the complete
command line in field 5. Authentication is checked before commands are sent.
The implementation has no protobuf package dependency.

For deterministic selection, `/load` creates `mrvn_harness_run`, inheriting the
requested playlist with the requested map and mode. Thus
`GetCurrentPlaylistName()` reports `mrvn_harness_run`; the response also records
the requested base playlist. The controller owns a separate temporary playlist
copy and startup config. Stock playlist/config files are not edited. Those
temporary files are removed on stop. Games and ports belonging to another
controller are not intentionally stopped or reused.

## Map prerequisites and evidence

Dedicated R5 mounts `englishserver_MAP.bsp.pak000_dir.vpk` plus its corresponding
server chunk, whereas the rendered game mounts the client archive. The port
writer now emits both. The native model/resource initialization requires that
server archive to be present; loose BSP files alone were insufficient in the
first Coliseum test. Map-specific gameplay scripts and required RPaks must
already be installed.

The local run artifacts are `events.jsonl`, `engine-output.log` and the chosen
smoke report. Events exclude password, token and network-key lines. Raw engine
output stays local and is not returned by the HTTP API. Native crash reporting
tracks the newly created engine log directory when unambiguous and exposes
only its short crash header. A fatal modal can leave a process alive, so both
readiness timeouts and crash headers matter.

Protocol and isolation regression checks:

```powershell
python -m unittest discover -s tools/respawn -p test_r5_harness.py
```

Native validation on 28 October 2026: dedicated Coliseum boot and reload each
created a fresh server VM; all eight collision probes passed within 0.0001 of
the source fractions. The same process switched from `tdm` to `fs_dm` on
Coliseum, then loaded `mp_rr_arena_composite` in `tdm`. HTTP requests without
authentication returned 401, and invalid map identifiers returned 400.
The local evidence is saved under `.local/respawn/apex-port/harness/` in
`native-smoke.json`, `native-mode-switch.json`, `native-map-switch.json` and
`http-validation.json`. Six protocol tests and the five existing VPK package
tests passed. These results do not resolve the rendered client's separate
sign-on crash or certify the unfinished visual port.

Protocol provenance: the user's installed SDK Git tag `v2.3_rc0`,
`resource/protobuf/cl_rcon.proto`, `resource/protobuf/sv_rcon.proto`,
`engine/server/sv_rcon.cpp`, and `common/callback.cpp`. The current
[R5 RCON documentation](https://docs.r5reloaded.com/hosting/rcon) describes the
newer encrypted interface; this harness deliberately targets the installed
legacy version. No upstream implementation code is included.
