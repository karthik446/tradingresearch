# Who answers a model call? Providers, adapters and one error taxonomy (concept note)

**The idea.** A model call is an HTTP request to someone's API. This repo talks to two: OpenRouter, a router that
forwards one request shape (OpenAI's chat completions) to many vendors' models, and Anthropic's own Messages API.
The rest of the code never sees either. It builds one `ModelRequest` (system and user turns, a token cap, JSON or
schema mode) and gets back one `ModelResult` (text, token usage, cost, finish reason). An adapter per provider
translates between the two. `TR_PROVIDER` picks the adapter; the runbook's "Providers" section has the operator's
view and ADR-014 has the decisions.

**What differs between the two APIs, and how the adapters hide it.**

| | OpenRouter | Anthropic Messages |
|---|---|---|
| Endpoint and key | `POST /api/v1/chat/completions`, `Authorization: Bearer` | `POST /v1/messages`, `x-api-key` plus an `anthropic-version` header |
| Model id | `anthropic/claude-sonnet-5.5` (vendor/name) | `claude-sonnet-5-5`; the adapter derives it from the config id |
| System prompt | a `system` message in the list | a top-level `system` field |
| JSON output | `response_format` (a JSON schema or plain JSON) | `output_config.format` for a schema; no plain-JSON switch |
| Cost | reported in the reply's `usage.cost` | not reported: tokens x the adapter's price table |
| Which server ran it | `provider` in the reply (the routed host) | `model` and `inference_geo` in the reply |

**One error taxonomy.** Each API fails differently (OpenRouter's 402 versus Anthropic's 400 "credit balance" or
spend-limit message, Anthropic's 529 "overloaded"). Both adapters map their failures into five kinds:
`credit_exhausted`, `rate_limited`, `upstream_5xx`, `output_not_json` and `refused`. The retry policy and the journal
then behave the same whichever provider failed. One rule matters for cost: **a reply you were billed for is never
thrown away.** A reply that is not valid JSON, is cut at the token cap, or is a refusal comes back as a result with
its cost, and the caller's parser records the failure. An exception would lose the cost, because the run records
only a result's cost.

**Redaction at the adapter.** An API can echo what it was sent, a key included, in an error body or a reply. Both
adapters run `redact.scrub` on the error message, the reply text and each tool call's arguments before anything
leaves the adapter, so a key-shaped string reaches the trace as `[REDACTED:<name>]` and the billed cost is kept
(ADR-004 Gaps).

**Why a provider change is a new route.** The same model behind two providers can differ in serving stack, region
and price, so a comparison across them is not like for like. The recorded route starts with the provider
(`openrouter:...` or `anthropic:...`), which keeps experiments from mixing them silently.

**Batch judge (OpenRouter batches).** `tr grade --judge --batch` sends every judge call `tr grade --judge` would make
as one OpenRouter batch, billed at the model's `:batch` row of the public price list. `--judge-max-usd` caps the
worst-case estimate at that price, and the theses over the cap wait for the next run. Each entry's body is the sync
body under the normal model slug (no `:batch` on the wire) and its `custom_id` is the thesis id. It stores nothing in
the journal; it writes `<data_dir>/batches/<id>.json` (thesis ids, each prompt's digest, model, submit time; never the
key). `tr grade --judge --collect <id>` polls once. Still running: it says so
and exits 0. Failed, expired or cancelled: exit 1, nothing stored. Completed: each thesis runs through the same
`run_eval` as a sync judge, with a provider that answers from the batch result whose `custom_id` matches (results
come unordered). The run file, spans, ScoreRecord and verdict are those of a sync call. An error entry, a missing
entry or a prompt that changed since submit is a failed call, so nothing is stored for that thesis. A result entry
with no `custom_id` is skipped: the thesis it answered has no result (a failed call) and the other theses still store.
Each call's cost is `derived`: tokens times the `:batch` price. Collect prints the sum next to the batch's own
`usage.cost` and exits 1 when they differ by more than $0.001. The verdicts are kept either way, and the line says the
run files hold the derived cost. The run's latency is 0, because a batch reports no per-request time. With `--batch`
(not a dry run) or `--collect`, an empty `OPENROUTER_API_KEY` exits 2 first: before the grade step reads Alpaca bars
or writes a grade, and before any OpenRouter request. This path is tested on fake HTTP only (`tests/test_batch.py`)
and has never run against the real endpoint. Only a paid run will show the real turnaround, which provider OpenRouter
picks, whether each result entry carries `usage` (without it the derived sum is short and collect exits 1), and the
real `usage.cost`.

**Options this repo does not use yet.**
- *Anthropic Message Batches.* Anthropic's own batch API takes many requests at once at half the standard price and
  returns results within 24 hours. The batch judge above uses OpenRouter's batches instead.
- *Prompt caching.* Both APIs can bill a repeated prompt prefix at a lower rate. The Anthropic price table already
  prices cache writes and hits when a reply reports them.
- *Data residency.* Anthropic's `inference_geo: "us"` keeps inference in the US at 1.1x the price. The adapter does
  not price that multiplier.
- *A direct OpenAI adapter.* `.env.example` holds a commented `OPENAI_API_KEY` slot for it.

**Read the source docs.**
- OpenRouter: [API overview](https://openrouter.ai/docs/api/reference/overview),
  [chat completions](https://openrouter.ai/docs/api-reference/chat-completion),
  [quickstart](https://openrouter.ai/docs/quickstart).
- OpenRouter batches: [quickstart](https://openrouter.ai/docs/batch-quickstart).
- Anthropic: [Messages](https://platform.claude.com/docs/en/api/messages),
  [errors](https://platform.claude.com/docs/en/api/errors),
  [rate and spend limits](https://platform.claude.com/docs/en/api/rate-limits),
  [versioning](https://platform.claude.com/docs/en/api/versioning),
  [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
  [pricing](https://platform.claude.com/docs/en/about-claude/pricing),
  [Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing).
