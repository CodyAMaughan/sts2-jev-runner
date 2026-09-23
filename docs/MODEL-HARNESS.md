# Decision harness: prompts, adapters and replays

Updated 2026-09-19. Production mod version unchanged.

## Prompt contract (`decision-v2`)

Full observations still live in the trace. Only a projection is sent to the model.
Each decision is stateless: the strategy and relevant rules accompany it. A sole
legal action makes no model call. Unknown decision kinds stop for implementation
instead of guessing which information is safe to drop.

| Decision | Model needs | Removed |
| --- | --- | --- |
| Combat | HP/block/powers, energy, turn, enemies/intents, indexed hand, unordered pile counts, relics, potions, character resources | Permanent deck duplicate, map, screen text, seed, transport IDs |
| In-combat selection | Combat context + source card, selection prompt, min/max, selected cards, offered choices | Screen names and unrelated run data |
| Card rewards, upgrades, removal, transform, enchant, bundles | HP, gold, counted deck, relics, potions, offered cards and selection rules | Old combat hand, enemies, energy and exhausted pile |
| Rewards | HP, gold, relics, potion inventory, available loot/skip | Deck and all stale combat state, screen/map |
| Map | HP, gold, counted deck, relics, potions, reachable future graph + legal next rooms | Visited/unreachable map nodes, repeated UI text |
| Shop | Gold, HP, counted deck, relics/potions, affordable stock prices and removal action | Old combat state and unrelated map |
| Rest | HP/max HP, deck/upgrades, relics, available rest actions | Old combat state |
| Event / special selection | Run context, unique event/selection text, costs and choices | Combat state unless an explicit combat selection |

Card definitions deduplicate identical card values; upgrades/cost/damage variants
remain distinct. Pile counts preserve duplicates without exposing hidden draw
order. Empty collections and null fields are omitted; meaningful zero values
remain. Formatting-only color tags are stripped. Target IDs refer to indexed
enemies rather than repeating their complete state for each attack.

The map graph is deliberately retained only on map decisions. Future branches are
strategically relevant (rest access, elites, shops); deleting every future node
would make route planning shortsighted. It is compact and limited to reachable
nodes. Event text is retained where it can contain unique rules. This is a
conservative first projection, not proof that every remaining field is essential.

The engine currently filters potion rewards when no slot is free, but does not
report total potion capacity explicitly. Legal reward options therefore remain
authoritative. Adding explicit capacity belongs in a later observation-schema
revision with replay compatibility, rather than inventing a slot count here.

Mission Control exposes **New compact template preview** for any selected move.
It is regenerated locally, not labeled as a historical API request. Original
requests/responses remain unchanged. `prompt-template-audit.json` contains per-kind
JSON-size measurements and examples; these are not measured tokenizer counts.

## Model boundary

`scripts/decision_models.py` defines `DecisionModel.decide(payload)` and adapters:

- `JevModel`: native typed choice request, legal-action validation, existing local key.
- `BifrostModel`: OpenAI-compatible chat completions, strict JSON schema with an
  enum of offered action IDs. Set `BIFROST_BASE_URL` (ending `/v1`) and optionally
  `BIFROST_API_KEY` in the controller environment. Model is `provider/model`.
- `CliModel`: installed `codex exec` or `claude -p`, structured JSON schema, fresh
  temporary working directory per decision, no game bridge credentials, no
  session continuation. CLIs manage their own existing login; no OAuth token
  extraction. CLI overhead must be compared separately from direct API inference.

Use `scripts/run_jev.py --backend jev|bifrost|codex|claude --model <model> ...`.
The dashboard launch form now selects Jev, Bifrost, Codex CLI or Claude CLI and a model. Both CLIs are installed.
Live one-decision tests now pass through Bifrost/Gemini, Bifrost/OpenAI and Codex CLI. Claude is blocked by expired authentication. See [STRATEGIES.md](STRATEGIES.md) for evidence and token counts.
Unit tests exercise Bifrost-shaped transport responses, malformed JSON, retries and simulated Codex/Claude CLI responses. The isolated real-engine replay passed forward/backward and room-boundary seeks with the same PID; normal saves were verified unchanged. All 34 Python tests and the C# harness build passed.

All transports consume the same projected facts and strategy. The Jev wrapper is a
typed choice question; generative transports add a JSON-only output instruction.
They get one repair retry on malformed/illegal output. Every attempt is recorded,
and usage sums both attempts. No invalid response can be submitted to the game;
no silent model fallback or heuristic substitution is allowed. HTTP/auth failures
stop rather than performing uncontrolled retries.

Jev move cost uses the existing estimate of $0.042 / million input tokens.
Other provider costs are explicitly unavailable until billing/pricing is configured;
subscription usage is not described as zero-cost API usage. Token counts supplied
by CLIs may include their system overhead and cached tokens. For fair benchmarks,
pin model/version, prompt version, strategy, seed, character, mod/game builds,
reasoning budget, adapter version, tools policy and retry limit. Keep latency,
format failures, all-attempt usage and win rate as separate measures. Subscription
limits and model availability still apply. No benchmarks against new backends were
run here.

## Research and supported integration paths

- [Bifrost provider matrix](https://docs.getbifrost.ai/providers/supported-providers/overview)
  documents OpenAI-compatible chat completions at `/v1/chat/completions` across its
  supported providers. Jev/TypeSafe is not listed as a native provider.
- [Bifrost custom providers](https://docs.getbifrost.ai/providers/custom-providers)
  extend existing provider API formats (OpenAI, Anthropic, Bedrock, Cohere, Gemini,
  Replicate). Our Jev `/v1/systemone` typed-question API is different. Inference:
  changing the base URL alone will not work; a translating adapter/plugin would
  be needed. Direct Jev is simpler and already established in this harness.
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
  supports `codex exec --output-schema` and reuses saved CLI authentication,
  including documented ChatGPT-managed account workflows. Use the official CLI;
  do not convert its subscription login into a generic Bifrost API credential.
- [Claude programmatic use](https://code.claude.com/docs/en/headless) supports
  `-p --output-format json --json-schema`, with `structured_output` and usage.
  [Claude authentication](https://code.claude.com/docs/en/authentication) documents
  subscription OAuth through `/login`; an API key can take precedence. The CLI
  adapter leaves authentication to Claude and reports cost as unknown. We have
  not established subscription-to-Bifrost forwarding as a supported integration.

## Replay transport

The previous Go/Back closed the process on purpose. Forward seek now simply
executes recorded actions until the target decision and pauses. Backward seek
unwinds the pilot, clears only the disposable current-run save, returns to the
menu inside the same game process, starts the original seed again, then executes
recorded actions until the target. This is reconstruction, not instantaneous
restoration of an arbitrary mid-combat snapshot. The window should remain open;
there is still a transition/loading period and a longer seek costs time.

Each reconstructed decision is checked against the original observation hash
(with the existing map-decoration exception). Divergence stops without submitting
an action. No model calls or screenshot/video storage are used by replays.
