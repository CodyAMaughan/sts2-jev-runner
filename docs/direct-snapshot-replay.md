# Direct decision snapshots — September 20, 2026

Back and Go now load one compressed native state graph. They do not execute
earlier recorded actions, restart the game process, or walk through earlier rooms.
Play loads successive recorded positions at the selected interval.

## Verification

- Converted all 190 decisions in `jev-ironclad-overgrowth-v115-01` headlessly.
  This was a one-time conversion of an old recording, with no model calls.
- Every capture passed serialization/deserialization against the game's
  `NetFullCombatState`, enemy next-move IDs, and three future outputs from each
  public run RNG stream. Captured RNG checks operate on clones.
- A fresh headless process loaded positions in nonsequential order, including
  Vantom decisions 157, 158, and 190. Native combat hand and creature nodes bound
  successfully, and creating those scenes did not change the recorded state.
  Subsequent scene loads were approximately 0.2–0.4 seconds; the first also
  preloaded assets (about five seconds).
- Mission Control's actual HTTP launch/control endpoints loaded positions
  157 → 158 → 157 → 86 → 95 → 180 → 179 → 1 → 190 → 157 → 158
  in one headless session. Play, Pause, rate, Back, Step, and Go were exercised.
  No `remote_action` events were emitted. Median logical load: 61.7 ms;
  maximum: 212.9 ms. The session stopped normally and its original-save check passed.
- 80 Python tests pass; C# build succeeds without warnings; dashboard JavaScript
  passes syntax checking. No headed visual check was performed.
- Snapshot storage for this run is 26.42 MB compressed, with no screenshots/video.

Evidence: `direct-snapshot-control-verification.json`, source run's
`snapshot-index.json`, and referenced conversion/replay run logs.

Two earlier test sessions observed the normal profile changing concurrently.
The normal save identified a Harry Potter run, whereas this isolated replay was
Ironclad. Their failed save-change checks remain recorded; they are not claimed
as clean checks. The final control test's check passed. The controller now also
propagates launcher failures instead of concealing them.

## Operation

Mission Control defaults to headless. Select **Show game window** explicitly to
watch a replay later. Refresh an already-open dashboard after the server update.
The native replay overlay has the same Back/Step/Play/Go controls.

New controller runs capture and index decision snapshots by default;
`--no-snapshots` opts out. Unprepared historical recordings undergo one headless
conversion before their first snapshot replay. An incomplete capture does not
publish a usable index. Navigation has no reconstruction fallback.

Command-line example:

```sh
python3 scripts/watch_replay.py docs/playtests/runs/jev-ironclad-overgrowth-v115-01 --at 157 --headless
```

## Current boundaries

- This is read-only recorded-position playback. It does not yet support branching
  into alternative live actions from an arbitrary mid-combat snapshot.
- Combat positions use native game scenes. Noncombat decisions currently use a
  readable panel of recorded choices, rather than each original event/shop UI.
- Play advances between decision snapshots; intervening attack/effect animations
  are not replayed. The current scene is rebuilt from the selected state, but
  earlier gameplay is never rerun.
- Tasks, Godot nodes, and runtime event subscriptions are excluded from the logical
  graph; native scene bindings are rebuilt. This is why restoring a position is
  distinct from resuming an interrupted asynchronous card/event operation.
- Snapshot files are trusted local artifacts tied to the captured game/mod build;
  loading arbitrary external snapshot graphs is unsupported. Game assembly and
  Dealmaker build mismatches are rejected. Validation so far covers this Ironclad
  Overgrowth run, not every character/encounter or future game build.
