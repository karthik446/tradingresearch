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
    answered in `resolved_model`;
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

**Results** (one run, 2026-11-17 New York; run ids in the list below the tables, never in a cell):

| metric | sonnet | routed | cached |
|---|---|---|---|
| `all_claims_valid` (mean of the items) | 0.767 | 0.800 | 0.700 |
| $ per ticker-day (USD, analyze plus thesis) | 0.0385 | 0.0225 | 0.0325 |
| p50 latency per item, analyze step (ms) | 7819 | 9714 | 7676 |
| p95 latency per item, analyze step (ms) | 9515 | 11872 | 11778 |
| thesis changed (share of items, against `sonnet`) | n/a | 0.617 | 0.650 |

Run ids (analysis run, thesis run): `sonnet` run_1eba503380b7444c, run_b7a046db477e4359; `routed`
run_98681aba3fe24a79, run_80c8bf85db874007; `cached` run_0311bd3c03344a3a, run_073c4b1e547f4930.

| judge | sync | batch |
|---|---|---|
| cost per call (USD) | awaiting run | awaiting run |
| turnaround (s) | awaiting run | awaiting run |
| cost per day at 10x shortlist (USD) | awaiting run | awaiting run |

**Result (read under the registered rule, written after the run).**
- The registered rule passes. `compare sonnet -> routed` printed `all_claims_valid` 0.767 -> 0.800, difference +0.033,
  95% CI [-0.100, +0.167]. The lower bound -0.100 is above -0.15, so `NoWorseThan("all_claims_valid", margin=0.15,
  bound="ci_lower")` passes, applied by hand.
- The registered power caveat applies. The discordant share of the 60 paired items is 20 of 60, ψ = 0.333 (9 items
  valid only on `sonnet`, 11 only on `routed`), above the registered 0.22. The interval is wide, so the pass is not a
  proof of non-inferiority. The same-model noise floor is no smaller: `cached` against `sonnet` gave ψ = 0.267 (10 and
  6), a difference of -0.067 with CI [-0.167, +0.050], whose lower bound is below -0.15 for a pair that differs only
  by a cache. The earlier resample estimate of ψ 0.10 to 0.25 (G15 spike §2) was too low for these 60 items.
- Secondary graders, not deciding: `claims_valid` 0.962 -> 0.973 (CI [-0.011, +0.032]); `inferences_grounded` 0.983 ->
  0.983 (CI [-0.050, +0.050]); `parsed` 1.000 in all three arms. `routed` had one audit reject (`reject=1`).
- Cost: the analyze step costs $0.0858 on Haiku 5.5 against $1.0304 on Sonnet 5.5 (60 items each; the Haiku output is
  135,389 tokens against 66,809), 92% less. The thesis step is unchanged ($1.2659 against $1.2783). Per ticker-day,
  `routed` costs 41% less than `sonnet` (0.0225 against 0.0385). The run spent $5.6118 in all ($2.3086, $1.3517,
  $1.9515), above the expected $5.4 and below every cap.
- Latency: Haiku 5.5 is slower per item on the analyze step (p50 9714 ms against 7819 ms), because it writes about
  twice as many tokens.
- Drift: the thesis changed on 0.617 of the items under `routed` (CI [0.483, 0.750]) and on 0.650 under `cached`
  (CI [0.483, 0.800]). The two are the same within noise: a thesis changes between any two runs about as often as it
  changes under a different analyze model, so `thesis changed` does not separate the model effect.
- Fallback: 0 of 60 analysis calls of `routed` were served by Sonnet 5.5 (every span's `resolved_model` is
  `claude-haiku-5-5`), so the fallback path did not run in this experiment.
- Cache: the cache worked. Analyze: 1,216 cache-write tokens once and 71,744 read tokens (59 calls of 1,216), against 0
  and 0 on `sonnet`. Thesis: 2,112 written and 124,608 read. `cached` cost 12.7% less on the analysis ($0.8990 against
  $1.0304) and 17.7% less on the thesis ($1.0525 against $1.2783). The risk registered above did not occur: the cached
  analyze block is 1,216 tokens, so the "about 510 tokens" estimate of the prompt was too low.
- Recommendation: route the analyze step to Haiku 5.5 only after a second run settles the quality question, because
  the interval cannot rule out a loss of 0.10 and ψ is above the registered 0.22. The saving is real and measured
  (41% per ticker-day), the quality evidence is not conclusive. `tr daily` stays on Sonnet 5.5 on both steps; nothing
  was adopted.

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

## Amendment 1 (2026-11-18, pre-registered; the first run's rule, Result and numbers above do not change)

A second run of the `sonnet` vs `routed` comparison on fresh items, `experiments/routing-replication.toml`, with the
adoption rule fixed here before the run. Nothing above is edited: the first run's Result stands as written, and this
amendment is committed before the replication's first paid call. Every number below is either quoted from a file or
a printed line (named), or computed here and marked as such.

**1. Why.** Three facts from the Result above, all quoted:
- the registered rule passed on the first run's 60 items: `all_claims_valid` routed minus sonnet +0.033, 95% CI
  [-0.100, +0.167], lower bound above the -0.15 margin;
- the discordant share was 0.333 (20 of 60 items, 9 valid only on `sonnet`, 11 only on `routed`), against the 0.22
  those 60 items were sized for, so the pass came with a wide interval and the registered power caveat;
- the same-model pair `cached` vs `sonnet` gave -0.067, CI [-0.167, +0.050], discordant share 0.267 (10 and 6): two
  runs of one model on one set of prompts differ by about the size of the effect being tested.
The Result's recommendation was a second run before Haiku routing is adopted. This is that run: fresh items, a rule
fixed in advance, sized on the observed 0.333, and the result recomputed by an independent reader.

**2. Fresh items and how they are drawn.** The same 10 tickers (AAPL MSFT NVDA AMZN JPM XOM UNH HD KO CAT) on the 12
NYSE sessions immediately before the first run's earliest session, 2026-11-10: `sessions.recent(12, date(2026, 11,
9))` returns 2026-10-23, 10-26, 10-27, 10-28, 10-29, 10-30, 11-02, 11-03, 11-04, 11-05, 11-06 and 11-09 (the call
was run on 2026-11-18 and printed exactly that list; the calendar makes the choice, not the writer). 10 x 12 = 120
items, each `<ticker>:<session>`; none is among the first run's 60, whose sessions are 2026-11-10 to 2026-11-17.
Headlines for all 120 are already in the news store: `tr news TICKER --session 2026-11-04 --days 9` (run 2026-11-17)
covers the nine sessions 2026-10-23 to 11-04 (`--days` counts sessions back from `--session`), and the files for
11-05, 11-06 and 11-09 were already present from earlier fetches (the files carry the session date, not the fetch
date, so their provenance is not checkable from the store). Every one of the 120 `news/<ticker>/<session>.jsonl`
files exists, and 15 of the 120 are empty (no headline that day), as in the first run, where 7 of 60 were empty.
The empties cluster by name: HD 4, UNH 4, CAT 3, KO 2, XOM 2, the same tickers that held the first run's 7 empties
(HD 2, UNH 3, CAT 1, XOM 1), so the "no headline" condition is itself ticker-clustered and rides inside those
clusters. Said plainly: the tickers repeat, so the 10 clusters of the bootstrap are the same 10 names, not new ones,
and a ticker-specific effect is not separated from the model effect. This replication tests the sessions, not new
names.

**3. Arms.** `sonnet` and `routed`, defined exactly as in `routing.toml` (Sonnet 5.5 on both steps; Haiku 5.5 on
analyze with Sonnet 5.5 on the thesis and as the fallback), prompt `analyze-3`, `kind = "pipeline"`, the same four
graders. There is NO `cached` arm. That is a choice, and the reasons are: the cache effect is already measured above
(1,216 tokens written, 12.7% and 17.7% saved) and does not need a second sample; a third arm at 120 items would bring
the expected spend to about 11.2 USD (2 x (2.3086 + 1.3517 + 1.9515) = 11.22, computed from the first run's arm
totals, linear in items) of the 12 USD ceiling the orchestrator set for this run; and the reading the same-model pair
gave, the run-to-run noise, is carried into the rule by item 6 instead of a new arm.

**4. Size.** The paired non-inferiority sample size is n = (z(1-a) + z(1-b))^2 x psi / margin^2. The first
pre-registration used 6.19 = (1.645 + 0.842)^2, one-sided a = 0.05, power 0.80. The rule reads a two-sided 95%
interval, whose lower bound is a one-sided test at a = 0.025, so the honest constant is (1.960 + 0.842)^2 = 7.85
(computed). With the first run's psi = 0.333 and margin 0.15:
n = 7.85 x 0.333 / 0.15^2 = 7.85 x 0.333 / 0.0225 = 116.2 (computed), so 120 items. What 120 items cover: the psi
they cover is 120 x 0.15^2 / 7.85 = 0.344 `[INFERENCE: the same formula inverted]`. The formula treats the items as
independent, while the interval is a cluster bootstrap on 10 tickers, so the real coverage is lower than 0.344. If
the replication's discordant share is above 0.344, the check is underpowered and rule 5(d) says what happens.

**5. The adoption rule, fixed before the run.** Routing the analyze step to Haiku 5.5 is recommended for adoption
only if ALL of (0) to (e) hold on the 120 fresh items, each read from a printed number with no judgement call. The
rules are evaluated in the order (0), (d), (a), (b), (c), (e); the result reads the first rule that fails, or the
adoption reading if none fails, so every outcome maps to exactly one reading:
- (0) completeness: both `arm` lines print `failed=0`, every grader on both score lines (the indented line under
  each `arm` line) prints `(n=120)`, and `compare sonnet -> routed` prints `120 items, 10 clusters` with a numeric CI
  on the `all_claims_valid` line. If the run exits before the compare block, or any of these is not met, the result
  reads `incomplete run: <the arm line or exit line, quoted>`, (a) to (e) are not applied, nothing is adopted, and
  any re-run is a new amendment with its own registration (the spend of the incomplete run is reported);
- (a) non-inferiority: on the `all_claims_valid` line of `compare sonnet -> routed`, the lower bound of the printed
  95% CI is not below -0.150 (the same `NoWorseThan("all_claims_valid", margin=0.15, bound="ci_lower")`, the same
  seeded paired cluster bootstrap `tr exp run` prints, applied by hand; three decimals as printed);
- (b) parsing: the score line under `arm routed` prints `parsed=1.000 (n=120)` (no unparsable analysis; a failed call
  is caught by (0), not here; an unparsed reply also records no `all_claims_valid` score, so it drops that grader's
  `n` below 120 and (0) catches it first; (b) is kept as the printed cross-check);
- (c) direction: on the same `all_claims_valid` compare line, the printed `diff` is not below -0.050. This is a guard
  against a lucky interval: the first run's point estimate was +0.033, and a replication whose point estimate is
  below -0.05 does not agree with it in direction even if its interval clears the margin. It errs toward not
  adopting: a model truly equal to Sonnet prints a `diff` below -0.050 about 15% of the time `[INFERENCE: normal
  approximation, SE about 0.048 at 120 items from the first run's interval width]`, so its reading is "direction
  disagrees", never "worse";
- (d) power: the discordant share, counted from the per-item `all_claims_valid` scores of the two analysis runs paired
  by item id (each run file's `sample` records map a `trace_id` to an `item_id`, its `score` records carry the
  grader's value for that trace; an item is discordant when the two values differ; under (0) every item has both
  values), is at most 41 of 120 = 0.342 (computed: 41/120 = 0.342 is at most 0.344, 42/120 = 0.350 is not). If it is
  above, the result is `underpowered` and nothing is adopted, whatever the interval says;
- (e) served model: at most 6 of the 120 `routed` analysis spans (5%, a threshold fixed here before the run) in
  `traces/<routed analysis run>.jsonl` have a `resolved_model` other than `claude-haiku-5-5`. If more, the result
  reads "not adopted: the fallback served N of 120 analyses" (the arm then measured Sonnet 5.5 in part), whatever
  (a) to (d) show; the count is reported in every case. The first run had 0 of 60.
What is read in each case:
- all of (0) to (e) hold: the result reads "non-inferior on fresh items; Haiku 5.5 on the analyze step recommended";
- (0) fails: the result reads `incomplete run`, and nothing else is read;
- (0) holds and (d) fails: the result reads `underpowered`, and (a) to (c) and (e) are reported but decide nothing;
- (0) and (d) hold and (a) fails: the result reads "cannot show non-inferior" (not "worse"), whatever (b), (c) and
  (e) show;
- (0), (d) and (a) hold and (b) fails: the result reads "not adopted: unparsable analysis on routed", with the count;
- (0), (d), (a) and (b) hold and (c) fails: the result reads "not adopted: the direction disagrees with the first
  run" (not "worse": a truly equal model fails this guard about one time in seven);
- (0), (d), (a), (b) and (c) hold and (e) fails: the result reads "not adopted: the fallback served N of 120
  analyses".
"Recommended for adoption" means a separate, operator-approved change to `tr daily`; this amendment adopts nothing
and the live loop is untouched, as the Decision above says. The replication's `compare sonnet -> routed` line is the
primary evidence. The first run is reported beside it, never pooled into the interval: it is a different item set,
read after the fact, and the first run's 60 items are not fresh.

**6. Noise reading (in place of a third arm).** The first run's `cached` arm was the baseline with a prompt cache. A
cache cannot change what the model says, so the -0.067 gap between `cached` and `sonnet` (CI [-0.167, +0.050],
discordant share 0.267) is run-to-run sampling noise between two runs of the same model on the same prompts, with
temperature left to the provider default: the stored first-run analysis run `run_1eba503380b7444c` carries
`"temperature": null`, `"top_p": null` and `"seed": null` in its `settings` (read 2026-11-18). That noise is of the
size of the effect under test (a margin of 0.15 against a same-model gap of 0.067 whose own lower bound is -0.167),
which is why one 60-item run could not settle routing. For rule 5(a) this means: the lower bound already carries the
run-to-run noise, because the interval is computed from the paired item differences of this run, which include it.
The rule does not subtract a noise floor a second time, and a `cached` arm would only re-measure the same figure.

**7. Cost.** Expected spend: the first run's arm totals doubled, 2 x 2.3086 = 4.62 USD for `sonnet` and 2 x 1.3517 =
2.70 USD for `routed` `[INFERENCE: linear in items]`, about 7.3 USD in all against the 12 USD ceiling. The per-arm
cap is set from the plan pre-flight, as in the first run: a probe of `routing-replication.toml` with
`max_usd_per_arm = 0.01`, run on 2026-11-18 with no model call (it exits 2 before the first call), printed the floors
$9.014726 (`sonnet`) and $4.170791 (`routed`), the smallest whole-cent caps that clear the check being $9.02 and
$4.18. The floors are 2.00 x the first run's ($4.508856 and $2.085773; computed ratios 1.999 and 2.000). A refused
probe prints floors only; the same pre-flight (`experiment.plan`, run 2026-11-18 at the committed cap 10.50 through
the `tr exp run` code path and stopped before the first call) computed the bounds $10.108368 (`sonnet`, 1.121 x its
floor, the week-7 ratio) and $5.264433 (`routed`), with `experiment.warnings` empty: `max_usd_per_arm = 10.50`
clears both floors and both bounds, and `tr exp run` prints no `WARNING` line. The cap is a ceiling and not the
expected spend: the tool guarantees only the two caps, 21 USD at both, or 15.37 USD at the plan's bounds
`[INFERENCE: 10.108368 + 5.264433]`; no pair of caps summing to 12 USD clears the floors (9.01 + 4.17 = 13.19). The
12 USD ceiling is a budget expectation, not a guarantee: the expected 7.3 USD sits under it with room for the first
run's 4% overshoot (5.6118 against 5.4). The prompt cache is not used, so the baseline pays the full input price,
as the first run's `sonnet` arm did. Paid on the Anthropic credit only (`TR_PROVIDER=anthropic`); nothing on
OpenRouter.

**8. How it will be run and read.** This amendment and `experiments/routing-replication.toml` are committed before
the run. Then, in this order:
1. `TR_PROVIDER=anthropic TR_DATA_DIR=$PWD/data-dev uv run tr exp run experiments/routing-replication.toml`, output
   kept whole (`data-dev/scratch/w8rep1-run.txt` or a file named in the Result);
2. rule 5(0) is read from both `arm` lines, their score lines and the `compare sonnet -> routed` header; rules 5(a)
   to 5(c) from the score line under `arm routed` and the `all_claims_valid` line of `compare sonnet -> routed`;
   rule 5(d) from the two analysis run files as item 5 describes; rule 5(e) from the `routed` analysis run's trace
   file (`traces/<run id>.jsonl`, the `resolved_model` of each analysis span), as in the first run;
3. cost from `tr usage --by run` on the four run ids;
4. an independent reader recomputes rules (0) to (e), the discordant count and the served-model count from the run
   and trace files, without the writer's numbers in hand, before the Result is written;
5. the result goes in a **Result (replication)** section under this amendment, read under rule 5 and nothing else;
   the first run's Result above is not edited.
