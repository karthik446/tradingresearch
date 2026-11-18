# ADR-014: one provider interface, OpenRouter and Anthropic adapters

**Status:** accepted, 2026-11-17 (bead gigai-csy.66). Code: `src/tradingresearch/providers/`. Tests:
`tests/test_provider_golden.py` and `tests/test_provider_anthropic.py`. No paid call was made to write it; the first
paid Anthropic call is the coordinator's smoke run.

**Context.** Every model call went to OpenRouter (`openrouter.py`). The operator's Claude plan includes Anthropic API
credit, so the champion's Claude calls can go straight to Anthropic's Messages API. Teachers are DeepSeek and Qwen on
pinned DeepInfra routes and can only run on OpenRouter. Keys lived in `~/.config/tradingresearch/verify.env`. A fresh
clone had no file naming the variables.

**Decision.**

1. **One interface.** It is gigai-core's `ModelProvider` (`invoke`, `identity`, `capabilities`), with this repo's
   `served`, `routes` and `route_for(prompt)` added. Both `OpenRouter` (`providers/openrouter.py`) and `Anthropic`
   (`providers/anthropic.py`) implement it. `providers/__init__.py` owns the choice:
   - `make_provider(settings, role)` builds the adapter for a role;
   - `prices(settings, role, models)` gets that adapter's prices;
   - `check_models(...)` refuses, before any call, a model the provider cannot serve.
   
   Core is unchanged.
2. **`TR_PROVIDER`** is `openrouter` (the default) or `anthropic`. Any other value exits. It picks the provider for:
   - the champion and challenger (`analyze`, `thesis`, `daily`);
   - experiment arms;
   - the judge.
   
   **Teachers always use OpenRouter.** Only the chosen provider's key is read. A missing key exits with one line that
   names it.
3. **The OpenRouter move is behaviour-preserving.** The file moved as it was. Six wire bodies captured from `18a7209`
   (schema, json, judge, tools, two teacher routings) match byte for byte (`tests/fixtures/providers/openrouter/`).
   **Behaviour change:** OpenRouter model calls now honour `Retry-After` on a 429 or 5xx. Before, a model call's
   `OpenRouterError` carried no `retry_after`, so the policy always used its jittered wait.
4. **One error taxonomy** (`providers/errors.py`):

   | Kind | When | Retried |
   |---|---|---|
   | `credit_exhausted` | 402, `billing_error`, Anthropic's 400 "credit balance", or Anthropic's 400 for a spend limit you set ("You have reached your specified [workspace] API usage limits") | no |
   | `rate_limited` | 429, honouring `Retry-After` | yes |
   | `upstream_5xx` | 5xx, including Anthropic's 529 | yes |
   | `output_not_json` | core `OutputNotJSON`: a JSON or schema call whose reply is empty | no |
   | `refused` | Anthropic `stop_reason: refusal`, returned (not raised) as a result with `finish_reason="content_filter"` | no |
   | `rejected` | any other HTTP error | no |

   The journal's `code` strings are the same on both providers: `insufficient_credits`, `rate_limited`,
   `http_<status>`, `model_output_not_json`. So `retry.py`, the daily run and `CallError` rows do not need to know
   which provider failed.

   **A billed reply is never raised.** The callers (`analyze._model_span`, core `run`) read cost only from a
   `ModelResult`; an exception is recorded with `cost_usd=None`. So, as the OpenRouter adapter already did, a reply
   that is not valid JSON or was cut at `max_tokens` (`finish_reason="length"`) comes back with its text and cost, and
   the caller's parser records the failure. A refusal comes back with its cost, `finish_reason="content_filter"` and
   the reply's `stop_details` in `TokenUsage.raw`; `errors.kind(result)` names it `refused`. Only an empty reply in
   JSON mode raises `OutputNotJSON`.
5. **Model ids.** Configs and defaults keep the OpenRouter id (`anthropic/claude-sonnet-5.5`), so prompts, records,
   terms classes and experiment configs do not change. The Anthropic adapter derives the API id: it drops `anthropic/`
   and turns dots into hyphens, giving `claude-sonnet-5-5`. Any other vendor, or a non-`claude-` name, raises
   `WrongProvider` (`model_wrong_provider`). The commands turn that into an exit before any call.
6. **Anthropic request.**
   - The key goes in `x-api-key`, with `anthropic-version: 2026-10-21`.
   - System turns are joined into `system`.
   - Tool turns become `tool_result` blocks, and assistant tool calls become `tool_use` blocks.
   - Schema mode sends `output_config.format = {"type": "json_schema", ...}`. This is GA with no beta header.
   - JSON mode has no wire switch, so the reply's parse is left to the caller, as on OpenRouter.
   - `temperature`, `top_p` and `seed` are refused with `UnsupportedRequestField`, because the API rejects sampling
     knobs on Claude 5.5 with a 400. Our call settings never set them.
7. **Cost.** Core's `cost_status` vocabulary is `provider_reported`, `derived` and `unavailable`.
   - OpenRouter reports cost, so its calls are `provider_reported`.
   - Anthropic reports none. Cost is derived from the `PRICES` table, covering uncached input, output, 5-minute and
     1-hour cache writes, and cache hits. These calls are `derived`, or `unavailable` for an unpriced model.
   - US-only routing (`inference_geo: "us"`) costs 1.1x on every token category. That is not modelled: a call whose
     route ends in `/us` is underpriced by 10%. Our requests never ask for it.
   - `usage.input_tokens` is uncached input plus cache writes plus cache hits. The raw usage and the reply's `id`
     (`response_id`) are kept in `TokenUsage.raw`, because core's `ModelResult` has no field for them.
   - `tr usage` has no Anthropic key-spend line, because no such endpoint exists.
8. **Provenance.** The Anthropic route is `anthropic:<served model>`, with `/<geo>` added when the reply's
   `inference_geo` is not `global`. `records.clean_route` accepts both prefixes. A provider change is therefore always
   a new route and a new `provider.identity`, so a comparison cannot mix providers silently. OpenRouter's `Routing`
   (the per-arm `provider` table) has no meaning on Anthropic, so such an arm under `TR_PROVIDER=anthropic` exits.
9. **Env file.** The default is the clone's `.env` (`DEFAULT_ENV_FILE`, found from the package path), copied from the
   committed `.env.example`. `.env.example` names every variable and holds no value. `TR_ENV_FILE` overrides the
   path. The LaunchAgent keeps `verify.env` by setting `TR_ENV_FILE`, and that has to happen before the pin moves
   past this commit (runbook, "Pinned code, live data").

**Sources** (read 2026-11-17):
- https://platform.claude.com/docs/en/about-claude/models/overview (API ids)
- https://platform.claude.com/docs/en/about-claude/pricing (Sonnet 5.5: $2 input, $10 output, $2.50 5m write, $4 1h
  write, $0.10 hit per MTok; Opus 5.5 double)
- https://platform.claude.com/docs/en/api/messages
- https://platform.claude.com/docs/en/api/errors
- https://platform.claude.com/docs/en/api/versioning
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- https://platform.claude.com/docs/en/api/rate-limits (spend limits)
- https://platform.claude.com/docs/en/build-with-claude/batch-processing
- https://openrouter.ai/docs/api-reference/chat-completion

**Consequences.**
- Paid champion runs can use Anthropic credit by setting `TR_PROVIDER=anthropic`.
- The judge (`openai/gpt-6-sol`) and the bake-off still need OpenRouter.
- A price change at Anthropic needs an edit to `PRICES`, because there is no price endpoint.
- Under `TR_PROVIDER=anthropic` the live stream would record `anthropic:` routes, which are a new route. Switching the
  live agent is the operator's decision. It is not part of this change.
- **Future option, not code: the Message Batches API.** Anthropic's batch endpoint takes many Messages requests at
  once, at half the standard price, and returns results within 24 hours. That suits non-urgent work such as
  experiment arms and re-grading, never the live daily run. It would be a separate submit-and-poll path beside
  `invoke`, with its own price factor in `PRICES`. Nothing here implements it.
- **Future option, not code: a direct OpenAI adapter.** `.env.example` holds a commented `OPENAI_API_KEY` slot.
