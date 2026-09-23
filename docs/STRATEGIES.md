# Versioned strategy packages and model smoke tests

Mission Control has Runs, Strategies, and Prompt examples tabs. Runs show total
wall time (including setup, configured delay and pauses) and model-decision time.
For incomplete runs, duration is the span recorded so far, not an invented finish.

## Adaptive Survival 1.0.0

The first package is `strategies/balanced/1.0.0.json`. `Strategy` owns its goal and
15 `StrategyModule` objects. Modules contain a stable ID, version, priority,
matcher, exact prompt and rationale. Exact matches take precedence over broad
fallbacks. Generic templates cover normal fights, elites, bosses, multi-enemy
normal fights, card choices/rewards, deck improvement, rewards, routes, shops,
rest sites and events. Exact examples cover Kaiser Crab (observed Crusher/Rocket
components) and Phrog Parasite. Monster identities and room categories were
checked against the installed game source.

The Strategies view visualizes precedence and exposes each module's matching
rule, prompt and rationale. It is an initial authored strategy, not a proven
optimal policy. We have not authored unique tactics for every boss/elite/event.
Exact event routing supports `event_id` in the class; the current observation
bridge does not yet expose this identity, so events use the generic fallback.
Model-selected group routing is shown as future work and is disabled. A future
router should choose once per encounter, cache the choice, log its request/cost,
and never override an exact match.

## Immutable run provenance

At controller startup, `strategy-packet.json` freezes:

- Package identity, version, goal/profile and every module's text/rules.
- Prompt projection and strategy implementation source.
- A SHA-256 hash over canonical packet JSON.

Each decision records package hash, selected module/version, matching rule, and
routing method. Actual provider requests/responses remain in the trace. The
packet is independent of later edits to the catalog. “View recorded strategy”
opens a run's saved packet in the visual explorer. Historical runs that predate
packets are clearly legacy; their exact original prompts remain inspectable.
No current strategy is retroactively attributed to them.

A human-readable version identifies the authored release; the content hash also
detects changes to prose, profile or prompt-building implementation even if
someone forgets to bump that version. Preserve released JSON files and create a
new version file when evolving a package. The current registry pins 1.0.0; a
future registry can select among versioned releases explicitly.

## Live smoke results, September 19

Only one recorded combat decision was submitted per transport/provider. No game
actions were executed and no full runs were launched by these tests.

| Adapter | Result | Input tokens | Output tokens | Wall time |
| --- | --- | ---: | ---: | ---: |
| Bifrost → Gemini 2.5 Flash | Legal action, passed | 1,308 | 4,932 | 23.094 s |
| Bifrost → OpenAI gpt-4o-mini | Legal action, passed | 1,297 | 7 | 2.064 s |
| Codex CLI → configured default | Legal action, passed, existing ChatGPT login | 18,030 | 122 | 10.511 s |
| Claude CLI → configured default | Authentication blocked: expired OAuth session | — | — | 1.094 s |

Gemini's usage reports 4,924 reasoning tokens within its output count. The Codex
CLI has significant system/agent overhead beyond our shared game-state prompt.
These smoke tests verify transport and legal-action parsing, not relative playing
strength or a controlled benchmark. Pin explicit model IDs/reasoning settings for
actual comparisons. Subscription usage is not reported as zero-cost API usage.

Individual evidence files are in `docs/playtests/model-smokes/` and visible under
Strategies → Model adapter smoke tests. They include requests, raw responses,
usage and routing provenance, but no API keys. Claude needs `claude auth login`
followed by a retry of its single-decision test.

## Local Bifrost

The gateway is bound to `127.0.0.1:18767`, using the official
`maximhq/bifrost` image pinned to digest
`sha256:a8942692af7b4b89196cd8fc33653b7353488dfd58b24078fe793b8574a8084b`.
The named container is `spire-bifrost`. Its secret-free config lives in
`infra/bifrost/config.json`; keys are passed by environment-variable name from the
user-authorized source file, not copied into project configuration. Docker startup
initially stalled, but the daemon subsequently completed startup and both real
provider tests passed. The helper now copies config into the container, avoiding
host bind-mount dependence.

To start a new container after removal:

```sh
python3 scripts/start_bifrost.py --credentials /path/to/your/.env
```

To start/stop the existing container: `docker start spire-bifrost` or
`docker stop spire-bifrost`. The launch form supports backend and model selection;
Bifrost defaults to this local gateway, configured for `gemini/gemini-2.5-flash`
and `openai/gpt-4o-mini`. Other models need a corresponding gateway configuration.
CLI model `default` uses the CLI default; enter an explicit ID for repeatable tests.

Reference: [official Docker setup](https://docs.getbifrost.ai/quickstart/gateway/setting-up).

## Adaptive Survival 1.1.0 — encounter catalog and context inspector

The active catalog is now `strategies/balanced/1.1.0.json`; 1.0.0 remains unchanged for historical packets. New runs freeze 1.1.0. It contains 37 modules: 12 exact bosses, 12 exact elites, and 13 encounter-group/decision/fallback modules.

The encounter inventory is derived from installed source under `.tooling/game-src/MegaCrit.Sts2.Core.Models.Encounters`, with act assignment from the four Act models and `ActModel`/`Underdocks.Index`. Overgrowth and Underdocks are Act 1 alternatives; Hive is Act 2; Glory is Act 3. Exact matches use room type and actual monster model IDs, including survivors and spawned Wrigglers. Generic boss/elite fallbacks remain for future or unknown encounters.

Tactics were checked against monster move implementations and the relevant power implementations (including Slow, Slippery, Skittish, Hardened Shell, Shriek, Plow, Infested, Personal Hive, Vital Spark/Tainted, Crab Rage, Steam Eruption and Sandpit). These are authored strategies, not evidence of improved win rate. No new paid model run was performed for this change.

The dashboard now expands type → act → encounter. Each module exposes:
- Its exact matching rule and strategy prose.
- A decision-kind selector for modules covering several decisions, including combat/noncombat pending selections.
- The structured context fields used by that decision projection.
- A clearly labeled illustrative complete Jev request, generated through the real request builder with sample values. It is not a historical boss fight.

The request separates `state.strategy` (global goal plus module prose), `state.decision.state` (fresh projected game facts), `state.card_definitions` (deduplicated definitions), and `questions.action.criteria` (legal actions). Bifrost/CLI adapters carry the same facts in messages plus response-format instructions. Exact historical requests remain on individual run moves; recorded packets are not retroactively replaced.

Smoke-test results were removed from the dashboard; archived test evidence remains on disk. Claude was removed from the launch selector and is deferred.

Validation: 45 Python tests pass, including installed encounter inventory coverage, each monster's routing, legacy packet compatibility, and context-contract examples. Browser verification confirms nested elite selection and context rendering without console errors.

## Reviewed runs and version diffs (2026-09-19)

Mission Control now compares catalog versions with colored unified diffs and approval status. Launches accept `--strategy-version`; both launcher and controller check the exact strategy JSON digest against `strategies/approvals.json`. Viewing a diff never grants approval. 1.1.1 was explicitly approved by the user after review; no later version is approved. The changed version is frozen into each run packet.

`--act1-overgrowth` forces the default act list in the isolated harness, verifies `act_id=OVERGROWTH` before model calls, and stops on reaching Act 2 with `act1_victory`. It does not count entering a boss fight as a victory. The dashboard exposes this scope for base characters and defaults to Ironclad. Context compression remains decision-v2; these were tactical comparisons, not the proposed 400–600-token experiment.

Same seed OVERGROWTH01, Ironclad A0:
- 1.1.0: died floor 12; 136 model calls, 267,448 input tokens; 198.79 s.
- User-approved 1.1.1: died floor 14; 184 model calls, 385,132 input tokens; 237.96 s.
- Byrdonis: nine turns / 4 HP remaining became five turns / 39 HP remaining. Earlier draft/upgrade decisions differed, so this is not isolated causal evidence.
- Phrog Parasite: survived in the second run but still lost substantial HP; Mawler killed the player on floor 14.

Full comparison: `overgrowth-comparison-01.json`. Both normal saves remained unchanged. Model reported `jev-1.13.0`. Next work should address compact, self-contained action descriptions and common combat sequencing, with another reviewed version before any model run.

Art installation 0.3.9 includes the six explicitly approved replacement cards and six-pose death animation. Rubble Dividend revision remains excluded pending its separate approval. Engine evidence in `runs/jev-ironclad-overgrowth-v111-01/decisions.jsonl` includes `approved_death_audit`: six atlas poses, flat frame held through 2.79 s, then successful Idle reset. Two earlier mock checks did not invoke that audit; they are not proof of animation behavior. No model calls were used for those mock checks.
