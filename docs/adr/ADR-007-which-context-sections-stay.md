# ADR-007: which SOURCES sections stay in the analysis context

**Status:** accepted, 2026-11-17 (week 5), as the record of one run of `experiments/context-ablation.toml` judged by
the rule pre-registered below. The rule says both dropped sections "go"; this ADR does **not** change analyze's
default (see Decision).

**Context.** The analyze-3 SOURCES table has four sections (`masking.SECTIONS`): indicators, levels, EDGAR facts and,
new this week, up to 5 news headlines (`analyze.MAX_HEADLINES`) read from the local news store. Each section costs
input tokens on every call and each is something the model can cite wrongly; headlines are also untrusted text in
the prompt. ADR-005 kept the fixed context over tools; this ADR asks which parts of that context earn their place.
`experiments/context-ablation.toml` runs three fixed arms of analyze-3 on the week-4 sample (10 tickers × sessions
2026-11-12 and 2026-11-13 = 20 ticker-days, clustered by ticker): `full`, `no-headlines` (`drop = ["headlines"]`)
and `no-edgar` (`drop = ["edgar"]`). One dataset serves all three; `masking.Masked` removes the rows from each
request.

The week-4 finding this builds on (ADR-005): on the same 20 ticker-days, analyze-1 in the fixed context had
`all_claims_valid` 0.100 (2 of 20 analyses with every claim valid) and `claims_valid` 0.798, in both arms. That floor
is why the primary metric below is `claims_valid` and not `all_claims_valid`.

What the sample holds before any call (`tr news` for all 20 ticker-days, then the rendered prompts):
- 39 headlines shown over 20 ticker-days; 16 have at least one, 4 have none (UNH 11-12 and 11-13, HD 11-12,
  CAT 11-12). On those 4 the `full` and `no-headlines` requests are byte-identical, so they pair a request with
  itself; on the other 16 the requests differ. `full` and `no-edgar` differ on all 20.
- Headline rows are an estimated 5.1% of the system + user characters on average (6.4% over the 16 days with
  headlines, 12.4% at most, MSFT 11-12); EDGAR rows about 17.6% (15.4% to 18.8%). Estimates from characters, not
  tokens, over a mean prompt of 4,919 characters. The run measured the token shares (Result).

**Pre-registered metrics (fixed before the run).**
- **Primary:** `claims_valid`, the share of an analysis's claims that pass `validate_claims`, per ticker-day, paired
  by item (drop arm minus `full`), clustered by ticker, 95% interval and Wilcoxon p from `tr exp compare`. Not
  `all_claims_valid`: it was 0.100 in both week-4 arms (ADR-005, interval [−0.200, +0.200], McNemar p = 1), a floor
  at which one bad claim zeroes an analysis, so it cannot separate arms. `claims_valid` was 0.798 in both week-4 arms
  with an interval of [−0.083, +0.086] at n = 20 (MDE 0.124), so it has room to move both ways.
- **Guard:** `parsed` must not be lower in a drop arm than in `full`.
- **Reported, not deciding:** `all_claims_valid`; the four `<section>_grounded` graders (`evals/specs/section_grounding.md`;
  a section no claim cites gets no score, so their n differs by arm and they are not paired); input tokens, cost and
  latency per item.

Note added after the run (the registration above is unchanged): `tr exp compare` did not exist when this was
registered, and `tr exp run` refused both comparisons (a drop arm cannot score its dropped section's grader), so the
intervals below were computed outside `tr exp run` with the same gigai-core `compare`. Both gaps were then fixed
(`tr exp compare RUN_A RUN_B` exists; graders one arm cannot score are skipped with a printed reason), and the
numbers below match that command's output on the same stored runs.

**Result.** One run, `TR_DATA_DIR=$PWD/data-dev uv run tr exp run experiments/context-ablation.toml` on 2026-11-17,
`anthropic/claude-sonnet-5.5`, prompt analyze-3, cap $1.00 per arm: full `run_c32ea07781a54982`, no-headlines
`run_acb9119f015e4911`, no-edgar `run_95536ffe7c5e4b78`. No item failed and every item parsed in all three arms,
so every grader mean is over 20 analyses unless it says otherwise.

| metric | full | no headlines | no EDGAR |
|---|---|---|---|
| parsed (guard) | 1.000 | 1.000 | 1.000 |
| claims_valid (primary) | 0.964 | 0.969 | 0.986 |
| all_claims_valid | 0.850 | 0.750 | 0.850 |
| failed items | 0 | 0 | 0 |
| claims per item, mean | 11.15 | 11.15 | 10.80 |
| claims rejected, total | 8 | 7 | 3 |
| dropped_source claims | 0 | 0 | 0 |
| indicators_grounded: claims citing | 130 | 136 | 133 |
| levels_grounded: claims citing | 1 | 5 | 4 |
| edgar_grounded: claims citing | 9 | 17 | 0 |
| headlines_grounded: claims citing | 19 | 0 | 19 |
| tokens in, mean | 2,963.7 | 2,824.7 | 2,431.5 |
| tokens out, mean | 1,126.45 | 1,122.95 | 1,053.05 |
| cost per item, mean (USD) | 0.017192 | 0.016879 | 0.015394 |
| cost, arm total (USD) | 0.343838 | 0.337578 | 0.307870 |
| latency per item, mean | 8,028.95 ms | 7,812.75 ms | 7,434.85 ms |

The section graders, mean over the analyses they scored (a section no claim cites gets no score):

| grader | full | no headlines | no EDGAR |
|---|---|---|---|
| indicators_grounded | 0.992 (20 scored) | 0.962 (20) | 1.000 (20) |
| levels_grounded | 1.000 (1) | 1.000 (4) | 1.000 (3) |
| edgar_grounded | 1.000 (6) | 1.000 (11) | not scored (0) |
| headlines_grounded | 0.906 (16) | not scored (0) | 0.875 (16) |

Where each number comes from:
- Grader means and scored counts, failed items: the three `arm` lines `tr exp run` printed (`claims_valid=0.964
  (n=20)`, `failed=0` and so on; `experiment.means` over `data-dev/runs/<run_id>.jsonl`).
- Tokens and cost: `tr usage` on `data-dev` (run_c32ea07781a54982 59,274 in, 22,529 out, $0.343838;
  run_acb9119f015e4911 56,494 / 22,459 / $0.337578; run_95536ffe7c5e4b78 48,630 / 21,061 / $0.307870; 20 calls each),
  divided by 20 items. The comparison does not print tokens.
- Latency: per item, the `latency_ms` of its one model call in `data-dev/traces/<run_id>.jsonl`, mean over 20.
- Claims per item, rejections, `dropped_source` and claims citing each section: the parsed replies in the run files,
  re-checked with `validate_claims` and the arm's hidden rows (as `ClaimsValid` does) and counted per section with
  `SectionGrounded.cites`'s rule; a claim citing two sections counts in both.

The paired comparison (drop arm − `full`, 20 items, 10 ticker clusters, intervals resampled over tickers). **Computed
outside `tr exp run`, because `tr exp run` refused it**: `commands/exp.py` passes every grader in the config to
gigai-core `compare` as a metric, and a drop arm never cites its dropped section, so `headlines_grounded` (no-headlines)
and `edgar_grounded` (no-edgar) have no score in one run and `compare` refuses the whole comparison (`metric 'X' is not
scored in both runs`). The numbers below are the same `gigai_core.compare`, run on the stored run files one grader at a
time; each interval uses the library's fixed bootstrap seed, so it does not depend on which other graders are compared.

| Metric | no headlines − full | 95% interval | Test | no EDGAR − full | 95% interval | Test |
|---|---|---|---|---|---|---|
| parsed | +0.000 | [+0.000, +0.000] | McNemar p = 1 | +0.000 | [+0.000, +0.000] | McNemar p = 1 |
| claims_valid | +0.005 | [−0.027, +0.042] | Wilcoxon p = 0.906, MDE 0.057 | +0.023 | [−0.014, +0.068] | Wilcoxon p = 0.438, MDE 0.064 |
| all_claims_valid | −0.100 | [−0.300, +0.100] | McNemar p = 0.625 | +0.000 | [−0.250, +0.250] | McNemar p = 1 |
| indicators_grounded | −0.030 | [−0.062, −0.007] | Wilcoxon p = 0.125, MDE 0.038 | +0.008 | [+0.000, +0.025] | Wilcoxon p = 1, MDE 0.023 |

The other section graders give no usable comparison: against no headlines, `levels_grounded` pairs 1 item and
`edgar_grounded` 6 (5 clusters), both with no interval, and `headlines_grounded` is refused; against no EDGAR,
`levels_grounded` is refused (`no_paired_items`: the two arms scored it on different items), `edgar_grounded` is
refused and `headlines_grounded` pairs 16 items (−0.031, no interval, 9 clusters).

Measured share of input tokens (the request differs only by the masked rows, so the per-item difference in
`input_tokens` between `full` and a drop arm is what those rows cost; trace `usage.input_tokens`):
- Headlines: 139.0 tokens per item on average, 4.69% of `full`'s 2,963.7; 5.83% over the 16 days with headlines
  (0 on the 4 without, up to 362 on MSFT 11-12). The character estimate was 5.1% / 6.4%.
- EDGAR: 532.2 tokens per item, 17.96% (471 to 550 on every day). The character estimate was 17.6%.

What the analyses did with the sections (the counts above):
- Headlines: 19 claims in 16 analyses cited a headline in `full`; 3 of them failed `validate_claims`, all
  `number_in_text` (the claim's text repeats a figure from the headline), hence `headlines_grounded` 0.906.
- EDGAR: only 9 claims in 6 of the 20 `full` analyses cited an EDGAR row, so 14 `full` analyses never used it and the
  no-edgar comparison mostly pairs analyses that would not have cited it anyway. With headlines dropped, EDGAR citations
  rose to 17 claims in 11 analyses.
- `dropped_source`: 0 claims in either drop arm. No reply cited a row its arm never saw, so the check that fails such a
  claim never fired.

**Decision.** The rule, as registered, applied to each drop arm against `full`:
- **Headlines: go by the rule.** `claims_valid` +0.005, interval [−0.027, +0.042], not wholly below 0; the guard held
  (`parsed` 1.000 in both); mean input tokens fell from 2,963.7 to 2,824.7.
- **EDGAR: go by the rule.** `claims_valid` +0.023, interval [−0.014, +0.068], not wholly below 0; the guard held
  (`parsed` 1.000 in both); mean input tokens fell from 2,963.7 to 2,431.5.
- **What "go" means here: no measured loss, nothing more.** The token clause of the rule tests nothing: dropping rows
  always lowers input tokens, so "goes" reduces to "no significant loss on `claims_valid` and the guard held". That is
  absence of evidence of a loss, not evidence of no loss. The rule has no non-inferiority margin; the §7.3 gate in
  `split.py` (`GATE_MARGIN` = 0.15, `NoWorseThan(claims_valid, bound=ci_lower) >= -0.15`) has one, this ADR does not.
- **analyze's default does not change, whatever the rule says.** `DEFAULT_PROMPT` stays analyze-1 (`analyze.py`), no
  new prompt version without headlines or EDGAR is made, and analyze-3 is untouched. Adopting a drop needs a separate
  decision with a pre-registered non-inferiority margin and its own run.
- Not deciding, reported as registered: dropping EDGAR saves $0.001798 per analysis, 10.5% ($0.017192 −
  $0.015394; $0.015394 ÷ $0.017192 = 0.895), and headlines $0.000313, 1.8%. `all_claims_valid` fell by 0.100 without
  headlines (interval −0.300 to +0.100). `indicators_grounded` fell by 0.030 without headlines with its interval
  wholly below 0 ([−0.062, −0.007]; 5 analyses with one failing indicator claim, against 1 in `full`); it is one of many
  reported metrics, not pre-registered, and decides nothing.

**Gaps (what the data cannot show).**
- n = 20 ticker-days in 10 clusters. The run's MDEs on `claims_valid` are 0.057 (no headlines) and 0.064 (no EDGAR),
  so a loss of about 0.06 or less would go unseen; week 4's MDE was 0.124 and its half-width about 0.085, at which a
  loss near 0.1 hides. `full` sits near the ceiling (0.964; 17 of its 20 analyses at 1.000), so a drop arm can gain
  at most +0.036 on average while it could lose much more: the room is one-sided.
- The 4 headline-free ticker-days are identical requests in the no-headlines comparison and pull its difference toward
  0. They are not noise-free: on HD 11-12 the same request scored 1.000 in `full` and 0.818 in no-headlines. Over the
  16 days with headlines the mean difference is +0.018 (computed by hand, post hoc: the mean of the 16 per-item
  differences; no interval computed), against +0.005 over all 20.
- `claims_valid` is a per-claim rate: an arm that makes fewer claims can score higher (no-edgar made 10.80 claims per
  analysis against 11.15).
- A headline claim passes on its citation alone: whether it says what the headline says is not checked, so a wrong
  paraphrase counts as valid and headlines can only look better here on faithfulness, which flatters `full`.
- The guard is a point comparison on 20 items (1.000 against 1.000 here), with no interval behind it.
- Two comparisons (no headlines, no EDGAR), each at 95%, with no correction for multiplicity.
- `no-edgar` says little about EDGAR's value: only 9 claims in 6 of 20 `full` analyses cited EDGAR at all.
- One model, one prompt, 20 ticker-days over two sessions; a result does not carry to other models, prompts or
  market regimes. Indicators and levels are not ablated (the config drops only headlines and EDGAR).
- analyze-3's `full` arm had `all_claims_valid` 0.850 where analyze-1 had 0.100 in week 4 on the same ticker-days; the
  prompt, the headlines and the run all differ, so this is not a comparison and says nothing about why.

**Consequences.**
- The analysis path is unchanged: `tr analyze` and `tr daily` keep `DEFAULT_PROMPT` analyze-1, and analyze-3 with its
  headlines and the `tr news` prerequisite stays an experiment prompt.
- Dropping a section from a default prompt needs a new pre-registration with a non-inferiority margin on
  `claims_valid` (as the §7.3 gate has), a sample large enough for that margin, a rule for the per-claim-rate bias and
  a faithfulness check for headline claims, then its own run.
- If headlines enter a default prompt later, the week-7 injection guards come first (headlines are untrusted text).
- `tr exp run` cannot compare a drop arm whose config lists the dropped section's grader (`metric_missing`), nor a
  section grader scored on no common item (`no_paired_items`); until that is fixed, a drop-arm config's comparison has
  to be computed from the run files as here.
