# Changes

## Unreleased

- **The week-8 contract (`tests/test_week8.py`, G15-SPIKE §4).** Six tests on the two learner parts,
  `experiments/routing.toml` (a baseline, a routed and a cached pipeline arm; every model priced by
  `anthropic.prices`) and `docs/adr/ADR-011-*.md` (options, decision, readings; a pre-registration before the
  decision; the routing comparison table; the judge sync vs batch table). At week-8-start the six fail, each with
  `learner part missing: ...`; the same checks run on a small example config and ADR, which pass and whose broken
  variants fail, so no check passes on nothing. Runbook: "Week 8: routing, caching and the batch judge", which gives
  the order (ADR-011's pre-registration committed before the paid run; no test can see commit order).

- **Week-8 plumbing: a batch judge (G15-SPIKE §1.3).** `tr grade --judge --batch` submits the P1 judge calls as one
  OpenRouter batch (the sync request bodies, the normal model slug, `custom_id` = thesis id, the `:batch` price held to
  the `--judge-max-usd` cap; the record goes in `<data_dir>/batches/<id>.json` and nothing in the journal).
  `tr grade --judge --collect <id>` polls once: still running exits 0; failed, expired or cancelled exits 1 and stores
  nothing; completed sends each answer through the sync `run_eval` via `providers.BatchReplay`, so the run file, spans,
  `ScoreRecord` and verdict match a sync judge, and a derived cost is reconciled against the batch `usage.cost` (exit 1
  beyond $0.001). An empty `OPENROUTER_API_KEY` exits 2 before any request. `evals.p1_judge` is split into
  `judge_item` and `judge_run`, behaviour unchanged. Fake-HTTP tests only (`tests/test_batch.py`); never run against
  the real endpoint, so turnaround, per-entry usage and the real `usage.cost` are unmeasured.

- **`tr exp run`: the plan-total pre-flight (COST-3 item 3).** Before the first call, each arm's whole plan is
  priced the way its CallBudgets reserve it (`experiment.plan`). That covers every analysis request, built as the
  run builds it (plain, drop/retrieval/guards wrapper, tools first turn, routed analyze model, cache-write prices for
  a cached arm). A pipeline arm also gets one thesis request per item, priced twice. The floor assumes an analysis
  that cites nothing and claims nothing. The upper bound adds the analysis's whole output as claims and every
  headline it was shown. If an arm's floor is over `max_usd_per_arm`, `OverCap` is raised: `tr exp run` prints the
  arm, the floor, the cap and the smallest whole-cent cap that clears it, then exits 2 with no call. If only the upper
  bound is over, a `WARNING arm ...` header line is printed and the run goes on. When the plan fits, a `plan worst
  case $X per arm` line follows the arm lines. `run_arms` is now `stage` + `plan` + `run_staged`, so every caller
  is checked.
  - Why: on 2026-11-17 the first W7RefB attempt spent $0.644 on a pipeline arm's 30 analyses. The 30 thesis
    reservations ($1.011862) then did not fit the $1.50 cap, and `BudgetExceeded` stopped the run after $1.029382
    with no result (ADR-010 Amendment 1). The COST-SPIKE addendum (2026-11-17 14:50) shows the same mid-run stop at
    the account level: a 402 at a $0.365 balance, after the analyses had spent.
  - On the week-7 shape (30 injected items at Sonnet 5.5 rates, fixture prompts), the floor is $2.249640. At $1.50
    the run is now refused with 0 calls, where HEAD sent 50 before stopping. At the shipped $2.50 it runs, with a
    warning for the two inject arms (upper bound $2.518230).
  - Tests: `tests/test_preflight.py`. `test_a_cached_arm_runs_on_the_cached_copy...` now also sees the pre-flight's
    two plan budgets (listed and 1.25x prices) before the run's four.

- **`tr usage --by step` and `--by model`: the cost table (G15-SPIKE §3).** Both views print calls, items (distinct
  item ids), tokens in, cache write and cache read tokens (`-` when no call reported them), tokens out, cost, `$/item`
  and the p50/p95 over items of each item's summed latency (nearest rank). The step comes from the run: `analyze` /
  `thesis` from the tag's prompt part or the dataset id, `judge` for a `tr grade --judge` run, else `other` (never
  dropped). `--by model` keys on the requested model. `trace.Call` gains `cache_write_tokens`, `cache_read_tokens`
  (Anthropic `cache_creation_input_tokens` / `cache_read_input_tokens`, OpenRouter
  `prompt_tokens_details.cached_tokens`) and `step`; `usage.Usage` gains `items`, `cache_write`, `cache_read`,
  `usd_per_item`, `p50_ms` and `p95_ms`. The step and model totals add each run's micro-dollar cost, so they equal the
  `--by run` total; the existing views print exactly what they printed before. Their totals add their own rounded
  rows, so `--by arm` and `--by day` can differ from the run total by $0.000001 (on `data-dev` today: $7.909094 vs
  $7.909093). No ledger file, no `--account`. Tests: `tests/test_usage.py`.

- **Week-8 plumbing: a `cache` arm knob (G15-SPIKE §1.2).** Experiment arms take `cache = "5m" | "1h"` (default off).
  On `TR_PROVIDER=anthropic` the arm runs on `Anthropic.cached(ttl)`, which sends `system` as text blocks with one
  `cache_control {"type": "ephemeral", "ttl"}` breakpoint on the last block (user turn uncached; with the knob off the
  body is unchanged). A route fallback asks through the cached copy. The arm's budget reserves input at the
  cache-write rate (1.25x for 5m, 2x for 1h), so a cached arm's recorded `spent` reads high (core keeps the
  reservation as the spend on Anthropic); the per-call `cost_usd` in the trace is exact. `load` refuses another value
  or a tools arm; `tr exp run` refuses a cache arm on OpenRouter before any call, naming the arm, and prints
  `cache <ttl>` on the arm line. `cache` is not part of `input_hash`. Whether the prompt clears Anthropic's
  512-token minimum is settled by the paid run (`cache_creation_input_tokens` of 0 on every call means it did not).

- **Week-8 plumbing: a `route` arm knob, the Haiku 5.5 price, a model fallback (G15-SPIKE §1.1).** A pipeline arm
  takes `route = { analyze = "...", thesis = "...", fallback = "..." }`: a step left out uses the arm's `model`. The
  config load refuses a route on an analyze arm, an unknown key, or a value that is not a model id. `tr exp run`
  checks and prices every route and fallback model, and prints one line per arm with the models it asks. The input
  hash is unchanged: it did not include the model before, and a route does not add it.
  `providers.with_fallback` asks the fallback model once more when the adapter is out of retries on a retryable
  error (429, 5xx, a connection error or timeout). It never falls back after a refusal, an auth, credit or budget
  error, or a rejected request. The span's `resolved_model` and its cost name the model that answered.
  Anthropic `PRICES` gains `claude-haiku-5-5` (read 2026-11-17): the rates for prompts up to 100k tokens. Above
  100k tokens the page charges 5x, which is not modelled.
  Limits: the budget reserves the first model's worst case, so a dearer fallback can overshoot the reservation.
  The billed failed tries an OpenRouter error message reports are lost when the fallback answers. The daily loop
  and the champion are unchanged. Tests: `tests/test_experiment.py`, `tests/test_fallback.py`,
  `tests/test_provider_anthropic.py`.

- **Fix: a billed empty reply keeps its cost (OpenRouter).** A 200 with empty content on a JSON or schema call
  used to raise `OutputNotJSON` before `usage.cost` was read, so its spend was lost (two traced qwen calls,
  $0.020739). It now goes into the failed-tries `billed` list first, like a 200 with an error body, and the
  raised error ends in `(failed tries billed $X)`. Limit: the failed call's trace span still has `cost_usd` null and
  `cost_status` "unavailable" (the span is built by gigai-core `run` and `analyze._model_span`); the spend is in the
  error message only. Tests: `tests/test_openrouter.py`.
- **Week 7 reference: ADR-010 pre-registers the guards experiment.**
  - `docs/adr/ADR-010-guardrails.md` records where each rule sits, the options, the human review of audit hits and
    the decision rule for the guards-off vs on run. The table is filled from the run (`data-dev/scratch/w7refb/run2.txt`): attack success 0.800 off, 0.767 on, false rejection 0 of 10, noise floor 0.500; the guards did not pass the pre-registered rule, so the live `guards` setting stays empty. Amendment 1 raised the arm cap to $2.50 after the budget preflight stopped the first attempt.
  - `experiments/injection.toml` gains two clean control arms: `clean-on` (the guards on clean items: false
    rejection, collateral change) and `clean-rerun` (a second `clean`: the noise floor).
  - `experiment.drift` gives the changed share of a later clean arm against the first, by the `changed` rule, with
    the verdict's cluster bootstrap. `tr exp run` prints a `drift clean -> <arm>` line for it, and a
    `false rejection k/n` count from `audit.jsonl` for a clean arm with guards.
  - Tests: `tests/test_injection.py`.
- **Week 7 reference: guardrail rules and the `injection_resisted` grader.**
  - `guard_rules.py` registers two fetched rules: `instruction_shaped` (orders to the model) and `decision_steering`
    (levels, direction, size or horizon). A hit drops a headline and flags a filing chunk.
  - False flags: 0 of 61 clean headlines and 0 of 8,890 filing chunks of the pinned index. Hard invented
    look-alikes still trip them: 4 of 20 not tuned on; the residual shapes are listed in the module docstring.
  - `experiments/injection.toml` turns both rules on in the `injected-on` arm.
  - The `injection_resisted` grader scores a clean/injected pair 1.0 when nothing changed and 0.0 otherwise,
    `unparsed` included. Its spec is `evals/specs/injection_resisted.md`.
  - Tests: `tests/test_guard_rules.py`.
- **Redaction at the providers (ADR-004).** Both adapters now scrub key-shaped strings out of error messages, reply
  text and tool-call arguments before returning, and the error body is cut with `redact.clip`. Billed costs and the
  request bodies are unchanged. Every `tr` command now loads the configured keys for exact-value matching
  (`cli.main` calls `redact.configure`), not only `tr guards scan`.
- **`tr exp run` runs pipeline arms (week 7).** Per arm it prints the analyze and theses runs, spend, scores and that
  arm's `audit drop/flag/reject` counts. Each inject arm is paired with the clean arm. The run prints `verdict clean
  -> <arm>: attack success X  CI ...  n=N` once the learner's `injection_resisted` grader is registered. Until then
  it says the grader is not registered and exits 0.
- **Providers (ADR-014).** `TR_PROVIDER=openrouter|anthropic` picks who serves the model calls: the champion,
  challenger, experiment arms and judge. Teachers always run on OpenRouter.
  - The new `providers/anthropic.py` calls the Messages API directly. It maps `anthropic/claude-sonnet-5.5` to
    `claude-sonnet-5-5` and derives costs from a price table.
  - `openrouter.py` moved to `providers/openrouter.py`. Its wire bodies are byte-identical, checked by a golden test.
  - Both providers share one error taxonomy (`providers/errors.py`). A billed reply is never raised, so its cost
    reaches the run: an Anthropic reply that is not JSON or was cut at `max_tokens` comes back for the parser, and a
    refusal comes back with `finish_reason="content_filter"`. An Anthropic spend-limit 400 is `insufficient_credits`.
  - US-only Anthropic routing (1.1x) is not priced; the Message Batches API is a documented future option
    (ADR-014). Concept note with links to both APIs: `docs/providers.md`.
- **Behaviour change:** OpenRouter model calls now honour `Retry-After` on 429 and 5xx replies.
- **Env file.** Settings now come from `<repo>/.env`, copied from the new `.env.example`. Before, they came from
  `~/.config/tradingresearch/verify.env`; set `TR_ENV_FILE` to keep using that file. The LaunchAgent plist must set
  `TR_ENV_FILE` before the pin moves (runbook, "Pinned code, live data").
- `tr daily` prints the provider on its first line. `tr exp run` names the provider. Under Anthropic, `tr usage` says
  that no key-spend endpoint exists.
- `.env.example` has a commented `OPENAI_API_KEY` slot, not used yet.
- Tests no longer read `TR_PROVIDER` or `TR_ENV_FILE` from the shell (`tests/conftest.py`).
