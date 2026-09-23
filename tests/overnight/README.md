# Isolated engine playtest harness

This is a separate **test-only mod**, never part of the installed Dealmaker release. It runs the actual game engine, encounters, card effects, RNG, resource spending and rewards. Its pilots are deterministic heuristics, not people or LLMs deliberating at every turn. Agent reviewers inspect their decision logs afterward. These runs can reveal failures and interaction patterns; a small sample is not a win-rate estimate or proof of balance.

## Isolation requirements

Launch only a cloned app whose Godot `user://` directory is a dedicated test directory. Steam must be explicitly disabled with `--force-steam=off`; the harness refuses other launches. Set `DEALMAKER_TEST_USERDIR` to the verified `OS.GetUserDataDir()` path. Set `DEALMAKER_TEST_LOG` to an absolute JSONL path and `DEALMAKER_POLICY` to balanced, boast, favor, wall, or status. The parent task manages the isolated launcher and validates the directory before launch. Do not install this DLL into the normal game.

Compile with the local .NET SDK, `DOTNET_CLI_HOME` set to `.tooling/home`, and `-p:UseSharedCompilation=false`. Copy the resulting DLL and manifest into the clone's `mods/OvernightHarness/` beside copies of BaseLib and the baseline Dealmaker. Launch headless with `--autoslay --seed=<seed> --force-steam=off`. Both normal combat and event combat handlers are completely replaced. The stock AutoSlay adds enormous buffs and kills event enemies; those stock handlers are **not valid balance tests**.

## Policy and measurement limits

- All card plays use the ordinary `PlayCardAction`, including normal costs, hand membership, legality, hooks and card selection. No extra energy, health, powers or cards are injected.
- Providers of Boast are sequenced ahead of two affordable subsequent Attacks; existing partially completed Boasts discourage resetting. Power setup, useful defense, attacks and selected mechanic priorities follow.
- Survival-aware v3 adds visible lethal checks, immediate defense priority when displayed damage is lethal, and less setup priority under substantial pressure. This remains a bounded heuristic, not multi-card search. Targets that can be killed are ranked by their displayed incoming damage.
- Reward priority varies by pilot. All pilots may draft support from other mechanics. Current ranking is deliberately simple and does not yet model complete future deck value or reward skips.
- Favor choices consider displayed incoming damage. Optional exhaust protects core engines. Calling in Everything preserves Favors when their individual Strength-scaled damage is better.
- Rest below 60% health; otherwise upgrade a prioritized card. Potions are used below half health or in elite/boss combats. Shops and most events use the game's seeded smoke-navigation choices, a significant pilot limitation.
- Map navigation uses AutoSlay's deterministic first available route. This is a fixed-route pilot experiment, not an optimal pathfinding test.
- Turn, decision, post-play, selection, reward, rest, upgrade and combat telemetry is JSONL. Captures include hand, deck, relics, health, energy, enemy intents, Strength, Wall, and Boast progress.
- A recorded death is a completed run. Timeout/crash is an incomplete infrastructure or gameplay failure, never a victory. The test harness lifts the stock driver's floor-49 cutoff so the final boss can be played. `run_end: victory` is recorded only on the driver's explicit post-victory return to the menu. `driver_completed` alone does not establish victory. Read the room/outcome evidence.

Use `python3 tests/overnight/summarize.py <logs...> --output <summary.json>` to summarize evidence without inventing missing outcomes. Preserve original logs and code/version hashes with the report. Freeze baseline card balance until review.

## Pilot revisions and seed correction

Runs 01–04 are exploratory. v1 could block instead of taking a visible lethal. v2 fixed that, but still spent on Boast setup while facing preventable lethal damage. v3 adds the survival rules above.

The stock AutoSlay sets `DebugSeedOverride` before opening character selection; that screen clears it in singleplayer initialization. Thus the A/B strings in runs 01–04 seeded driver choices **but did not fix the world seed**. Their real seeds are in the engine's `Embarking...Seed:` line and archived history. They are not matched-pair controls. v3 restores the requested seed after character-selection initialization and logs the actual run RNG seed in each state snapshot. Verify it against the embark log before treating new runs as controlled.

The optional `DEALMAKER_QUOTE_SMOKE=1` mode loads `QuoteSmoke.dll` from alongside the harness and invokes its functional fixture at the first combat. This deliberately creates artificial state and exits after the fixture: it must never count as a balance run. Normal balance runs leave that variable unset.
