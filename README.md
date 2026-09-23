# sts2-jev-runner

An AI-playtest harness for Slay the Spire 2 mods: a Python controller that talks to
Typesafe's Jev decision API (or other model backends), a C# Harmony-patched bridge
that exposes the game's real decision points over a local HTTP API, and a Mission
Control dashboard for watching/replaying runs. Originally built inside the
`slay-the-spire-2-dealmaker` mod project; split out here so it can drive base
characters (Ironclad, Silent, ...) and future mods without being tied to any one
character's content.

See [docs/JEV.md](docs/JEV.md) for the full protocol/usage doc,
[docs/MODEL-HARNESS.md](docs/MODEL-HARNESS.md) and
[docs/STRATEGIES.md](docs/STRATEGIES.md) for the strategy-packet system, and
[docs/direct-snapshot-replay.md](docs/direct-snapshot-replay.md) for the
full-game-state snapshot/replay machinery (capture verified against native combat
state, enemy next-move IDs, and RNG stream determinism).

## Status: extracted scaffold, not yet fully standalone

This is a straight copy of the working code out of `slay-the-spire-2-dealmaker`,
with import paths intact. It is **not yet decoupled** — see "Known coupling to
remove" below. Until that's done, treat this repo as a staging area for the parts
that genuinely don't belong to any one mod (the controller, strategy content,
snapshot machinery, dashboard), developed here, and periodically synced back.

## Known coupling to remove

- `tests/overnight/OvernightHarness.csproj` references `BaseLib.dll` and
  `Dealmaker.dll` via relative paths into a sibling `slay-the-spire-2-dealmaker`
  checkout (`../../../slay-the-spire-2-dealmaker/...`). The bridge currently loads
  the Dealmaker mod DLL even when playing a base character — it's inert for those
  runs but shouldn't be a hard dependency. `.tooling` (the .NET SDK, BaseLib, and
  decompiled game source used to build against game assemblies) is never copied or
  committed here or anywhere — the existing `slay-the-spire-2-dealmaker` README is
  explicit that `.tooling`, decompiled game sources, the SDK, and game DLLs must
  never be distributed. Anyone else building this needs their own legitimately
  obtained copy of the game and BaseLib.
- `scripts/run_jev.py` / `scripts/run_playtest.py` still assume they're launched
  from a directory that also contains `.tooling/overnight/Runner.app` (the
  isolated game clone with the built DLLs installed) and `dist/Dealmaker/`. That
  layout currently only exists in the `slay-the-spire-2-dealmaker` checkout, so
  actually launching a run from *this* repo's location doesn't work yet — running
  a run today still happens from the dealmaker checkout with `DEALMAKER_STRATEGY_VERSION`
  pointed at a strategy file synced from here. Fully standalone launch (own isolated
  Runner.app, own dist output, no dependency on the dealmaker repo's layout) is
  follow-up work once a mod-agnostic build exists to install.

## Layout

- `scripts/` — the Python controller: `jev_playtest.py` (HTTP client + decision
  loop), `run_jev.py` (launcher), `strategy_registry.py` (versioned strategy
  packets), `decision_prompts.py`/`compact_decisions.py`/`decision_memory.py`
  (prompt construction), `mission_control.py` (dashboard server), `replay_*.py` /
  `prepare_snapshot_replay.py` / `watch_replay.py` (snapshot replay tooling).
- `tests/jev/` — Python unit tests (`python3 -m unittest discover -s tests/jev`).
- `tests/overnight/` — the C# Harmony bridge (`OvernightHarness`): patches the
  game's AutoSlay decision points to route through `DecisionBridge`'s HTTP API
  instead of the built-in heuristic pilot, and the snapshot capture/restore/replay
  machinery (`DecisionSnapshots.cs`, `DecisionSnapshotGraph.cs`,
  `SnapshotPlayback.cs`).
- `strategies/balanced/*.json` — versioned strategy content (per-encounter tactics,
  turn-level survival heuristics, character potion policy). `approvals.json` is the
  content-hash approval ledger — every version must be explicitly approved before a
  live run can use it (see `strategy_registry.require_approved`).
- `dashboard/`, `infra/bifrost/` — Mission Control's web UI and the local Bifrost
  gateway config for non-Jev model backends.

## Running tests

```sh
python3 -m unittest discover -s tests/jev
```

No game or API key needed for the Python unit tests. `docs/playtests/runs/` includes a
few historical run recordings (decisions/logs/manifests only — no save archives or
DLLs) that several tests replay against as fixtures.

79/80 pass out of the box. The one exception,
`test_complete_installed_encounter_coverage_and_routing`, checks the strategy
catalog's exact-encounter modules against the installed game's decompiled encounter
source under `.tooling/game-src/` — never committed or distributed here, per the
`slay-the-spire-2-dealmaker` project's own rule against distributing decompiled game
source, the .NET SDK, BaseLib, or game DLLs. That test passes if you point a local,
legitimately obtained `.tooling/game-src` checkout at this repo; it's expected to
fail otherwise.
