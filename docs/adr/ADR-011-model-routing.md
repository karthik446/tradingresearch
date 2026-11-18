# ADR-011: model routing: Haiku on the analyze step, measured against Sonnet before anything is switched

**Status:** proposed. Pre-registration written 2026-11-17, before any paid call of `experiments/routing.toml`; the
result and the recommendation go in a later **Result** section, under the rule below, which does not change.

**Context.** Every pipeline item makes two Sonnet 5.5 calls: analyze (the claims and inferences about one ticker-day)
and thesis (the trade decision built on that analysis). Week 8 ships three knobs: a `route` per pipeline arm (a model
per step, plus a fallback model after the adapter's retries run out), a `cache` per arm (one Anthropic prompt-cache
breakpoint on the last system block) and a batch mode for the P1 judge (`tr grade --judge --batch`, one OpenRouter
batch at the `:batch` price). Haiku 5.5 is listed at $0.10 in and $0.50 out per million tokens for prompts up to 100k
tokens, against Sonnet 5.5's $2 in and $10 out, so the analyze step is where a cheaper model would save the most. The
question this ADR settles: **can the analyze step run on Haiku 5.5 (the thesis stays on Sonnet 5.5) without losing
`all_claims_valid`, and what do a prompt cache and the batch judge change in cost?**

**Options considered.**
- All Sonnet 5.5, both steps (the status quo). This is the `sonnet` arm, the baseline every other arm is read against.
- Route the analyze step to Haiku 5.5, keep the thesis on Sonnet 5.5, Sonnet 5.5 as the fallback. Chosen to test, as
  the `routed` arm.
- Route both steps to Haiku 5.5. Not tested: the thesis is the step that makes the money-relevant decision (levels,
  direction, no-trade), and week 8 asks only whether the cheaper step can be made cheaper.
- Prompt caching of the static system prefix. Tested, as the `cached` arm: a cost-only knob that does not change the
  content, so it also gives a second sample of the baseline.
- Anthropic Message Batches for the experiment arms. Not used: a batch suits latency-tolerant judge calls, and an
  experiment needs its results inside the run.
- OpenRouter provider routing or the `:floor` variant. Not used: it routes between hosts of one model, not between
  models; the teachers and the bake-off stay on OpenRouter, and this experiment runs on the Anthropic provider only.

**Pre-registration (written before the run, 2026-11-17; not to change after it).** One run of
`TR_PROVIDER=anthropic TR_DATA_DIR=$PWD/data-dev uv run tr exp run experiments/routing.toml`, made after the news
store holds headlines for every ticker on every session below.
- Arms, all `kind = "pipeline"` (analyze, then a thesis in memory; nothing journaled), prompt `analyze-3`, one run each:
  - `sonnet`: Sonnet 5.5 on both steps, no route, no cache. The baseline (the first arm);
  - `routed`: Haiku 5.5 (`anthropic/claude-haiku-5.5`) on analyze, Sonnet 5.5 on the thesis, Sonnet 5.5 as the
    fallback;
  - `cached`: the baseline plus `cache = "5m"`. Also a second sample of the baseline, so the `sonnet` vs `cached`
    pair gives the noise floor.
- Items: 10 tickers x 6 sessions = 60 items per arm. Tickers AAPL MSFT NVDA AMZN JPM XOM UNH HD KO CAT (the
  `injection.toml` ten); sessions 2026-11-10, 2026-11-11, 2026-11-12, 2026-11-13, 2026-11-16 and 2026-11-17, the six
  latest sessions with stored headlines when the run is made (the G15 spike's "latest 6 with bars" is met by the
  same six).
- Graders per the config: `parsed`, `claims_valid`, `all_claims_valid`, `inferences_grounded`.
- Primary metric: `all_claims_valid`, paired by item (`<ticker>:<session>`); the interval is the seeded paired
  cluster bootstrap, clustered by ticker (10 clusters), 95%.
- Decision rule, fixed before the run: `routed` counts as not worse than `sonnet` if
  `NoWorseThan("all_claims_valid", margin=0.15, bound="ci_lower")` would pass, that is, the lower 95% bound of
  routed minus sonnet is at least -0.15. `tr exp run` prints that difference and its CI in
  `compare sonnet -> routed` but applies no gate and sets no exit code from it, so the lower bound printed there is
  compared with -0.15 by hand and the comparison is written into the Result section. If the bound is below -0.15,
  the result reads "cannot show non-inferior", not "worse".
- A pass is a recommendation only. The live loop is not routed in week 8: the live pin and the bake-off run on
  OpenRouter, and the `route` knob needs the Anthropic provider.
- Power: earlier same-model resamples gave discordant `all_claims_valid` shares of 1/10, 1/10, 2/10, 2/20 and 5/20
  (G15 spike §2), so the discordant share ψ is about 0.10 to 0.25. The paired non-inferiority sample size is
  n = 6.19 ψ / margin², so 60 items cover ψ up to 0.218 `[INFERENCE: 60 x 0.15² / 6.19]`. A different model will
  disagree with Sonnet more than a resample does. If ψ(routed, sonnet), counted from the paired item scores, is above
  0.22, a failed rule reads as "cannot show", and a pass with a wide interval is not a proof.
- Secondary, reported, not deciding:
  - drift: the `thesis changed` share in `drift sonnet -> routed` and `drift sonnet -> cached`; the cached line is
    the noise floor of the routed line;
  - $ per ticker-day: an arm's analysis run cost plus its thesis run cost, over its 60 items (`tr usage --by run`);
  - p50 and p95 latency per item: `tr usage --by step --run RUN_ID` on the arm's analysis run (the step the arms
    vary); the thesis run's figures are given beside the table. `--run` takes one run id, so every per-item figure of
    `tr usage --by step` is read per arm with `--run` (a run of all arms together would mix them);
  - cache write and cache read tokens on both runs of `cached` (`tr usage --by step --run RUN_ID`);
  - fallback count on `routed`: the analysis calls whose served model is Sonnet 5.5 rather than the Haiku 5.5 that was
    asked. No `tr usage` view shows it (`--by call` has no served-model column and `--by model` keys on the asked
    model), so it is counted from the arm's analysis run in `traces/`, where each call records the model that
    answered in `provider_route`;
- Excluded:
  - P1 vs Sonnet: the journal has 1 graded trade and 0 verdicts, and `P1Judge` cannot grade samples, so it cannot be
    measured in week 8;
  - the batch judge run: it waits on a funded OpenRouter key and at least 10 graded trades, so the judge table
    below stays `awaiting run`.
- Cost and cap: expected about $5.4 in total (sonnet about $2.28, routed about $1.30, cached about $1.81 to $1.86;
  G15 spike §2 cost table), on Anthropic credit only. `max_usd_per_arm` = 5.50, a per-arm ceiling; the spend is
  expected near $5.4 for all three arms together, and no arm is expected near its cap.
  - Why 5.50 and not the spike's 3.00: the plan pre-flight (COST-3a) prices each arm conservatively, the analysis
    calls at their worst-case reservations plus the smallest thesis reservations. A probe of this config with the cap
    at 0.01, run on 2026-11-17 with no model call, printed floors of $4.508856 (sonnet), $2.085773 (routed) and
    $4.586072 (cached), so a 3.00 cap would stop the run with exit 2 before its first call.
  - An arm's upper bound sits about 12% above its floor `[INFERENCE: the week-7 ratio, $2.518230 over $2.249640]`,
    about $5.05 for sonnet and $5.13 for cached, so 5.50 clears both the floor and the upper bound without a
    `WARNING` line.
  - Week 7 had to raise its cap after a stopped run (ADR-010 Amendment 1). This ADR fixes the cap before the run
    for that reason.
- Cache minimum: the analyze system prompt is about 510 tokens (2,038 characters at 4 characters a token) against
  Anthropic's 512-token minimum. If the analyze calls of `cached` show 0 cache-write tokens, the result is "the
  prompt is too short to cache", a measured outcome, and `cached` still stands as the second sample of the baseline.

**Decision.** Run the experiment as registered above. Adopt nothing in the live loop in week 8: `tr daily` keeps
Sonnet 5.5 on both steps, no cache. The result and the recommendation go in a later **Result** section, read under
the registered rule; the status stays proposed until then.

**Results** (awaiting the run; the `run_<16 hex>` ids the numbers come from go beside each table, never in a cell):

| metric | sonnet | routed | cached |
|---|---|---|---|
| `all_claims_valid` (mean of the items, 95% CI) | awaiting experiment | awaiting experiment | awaiting experiment |
| $ per ticker-day (USD, analyze plus thesis) | awaiting experiment | awaiting experiment | awaiting experiment |
| p50 latency per item, analyze step (ms) | awaiting experiment | awaiting experiment | awaiting experiment |
| p95 latency per item, analyze step (ms) | awaiting experiment | awaiting experiment | awaiting experiment |
| thesis changed (share of items, against `sonnet`) | n/a | awaiting experiment | awaiting experiment |

| judge | sync | batch |
|---|---|---|
| cost per call (USD) | awaiting run | awaiting run |
| turnaround (s) | awaiting run | awaiting run |
| cost per day at 10x shortlist (USD) | awaiting run | awaiting run |

**Consequences.**
- `tr exp run` on `routing.toml` prints a header line per arm (analyze model, thesis model, fallback, cache), a
  `compare sonnet -> routed` and a `compare sonnet -> cached` line per grader, a `drift` line for each later arm and
  each arm's run ids. The routing table is filled from those lines and from `tr usage`, the ids beside it.
- Nothing changes in `tr daily` in week 8, whatever the result.
- Limits of this design, stated before the result:
  - One model family (Anthropic), so nothing follows about other cheap models.
  - 60 items from 6 sessions of one market week; the clusters are tickers, so a week-wide effect is not separated
    from the model effect.
  - Haiku 5.5's price is read from Anthropic's pricing page and has not yet been checked against a billed call.
  - The cache and the fallback have never run against the real endpoint before this run (golden bodies and a fake
    provider only).
  - The batch judge is tested with fake HTTP only; its turnaround, per-entry usage and real `usage.cost` are
    unmeasured.

**Readings.**
- Anthropic, prompt caching (breakpoints, TTL, minimum cacheable length):
  https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Anthropic, pricing (Haiku 5.5 and Sonnet 5.5 rates, cache write and hit rates):
  https://platform.claude.com/docs/en/about-claude/pricing
- OpenRouter, batch API (the judge's batch mode): https://openrouter.ai/docs/guides/features/batch-api
- `docs/runbook.md`, "Week 8: routing, caching and the batch judge" and "Week 8 contract"; ADR-010 Amendment 1 (why
  the cap is fixed before the run); ADR-003 (why the judge is a different vendor).
