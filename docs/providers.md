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

**Options this repo does not use yet.**
- *Batch processing.* Anthropic's Message Batches API takes many requests at once at half the standard price and
  returns results within 24 hours. That suits experiments and re-grading, never the live daily run.
- *Prompt caching.* Both APIs can bill a repeated prompt prefix at a lower rate. The Anthropic price table already
  prices cache writes and hits when a reply reports them.
- *Data residency.* Anthropic's `inference_geo: "us"` keeps inference in the US at 1.1x the price. The adapter does
  not price that multiplier.
- *A direct OpenAI adapter.* `.env.example` holds a commented `OPENAI_API_KEY` slot for it.

**Read the source docs.**
- OpenRouter: [API overview](https://openrouter.ai/docs/api/reference/overview),
  [chat completions](https://openrouter.ai/docs/api-reference/chat-completion),
  [quickstart](https://openrouter.ai/docs/quickstart).
- Anthropic: [Messages](https://platform.claude.com/docs/en/api/messages),
  [errors](https://platform.claude.com/docs/en/api/errors),
  [rate and spend limits](https://platform.claude.com/docs/en/api/rate-limits),
  [versioning](https://platform.claude.com/docs/en/api/versioning),
  [structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs),
  [pricing](https://platform.claude.com/docs/en/about-claude/pricing),
  [Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing).
