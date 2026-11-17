# ADR-002: ship prompt analyze-2 as the default

**Status:** accepted, 2026-11-16 (week 1)

**Context.** The taxonomy's two largest mechanical classes were window names in prose (31 claims, 15 of 20
analyses) and inferences naming uncited indicators (15 analyses). analyze-2 changes three rules of analyze-1:
name indicators by table name, never by window; an inference names only indicators its parents cite; an opinion
lists no parents. It also restates that {value} is used only when value is set.

**Pre-registered before the run** (`experiments/prompt-v2.toml`): primary metric `all_claims_valid`; ship if the
95% interval of the paired difference lies above 0 and `parsed` does not drop.

**Result.** `tr exp run experiments/prompt-v2.toml`, 20 ticker-days (10 tickers × 2026-11-12, 2026-11-13), both
arms fresh, paired by item and clustered by ticker (10 clusters):

| Metric | analyze-1 | analyze-2 | Difference, 95% CI | Test |
|---|---|---|---|---|
| all_claims_valid | 0.150 | 0.850 | +0.700 [+0.450, +0.950] | McNemar p = 0.000122 |
| inferences_grounded | 0.300 | 0.950 | +0.650 [+0.350, +0.900] | McNemar p = 0.000977 |
| claims_valid | 0.814 | 0.977 | +0.162 [+0.085, +0.243] | Wilcoxon p = 0.00104 |
| parsed | 1.000 | 1.000 | +0.000 | — |

Cost: $0.3594 (baseline) and $0.3283 (variant) as reported by the runs.

**Decision.** Ship: the lower bound (+0.45) is above 0 and `parsed` held, as the pre-registered rule asks. With an MDE of
0.494 this run could only have seen a large effect; it saw one.
`DEFAULT_PROMPT` becomes `analyze-2` in week 2.

**Watch.** The variant's three remaining failures are 2 × `unknown_source` and 1 × `number_in_text`; unknown_source
was 1 claim in the observe run. With 20 items that is noise until a larger run says otherwise. Not measured at all:
verdicts inside facts (taxonomy class 3), which waits for the judge (ADR-001).

**Readings.** Shankar & Husain on running the change against the same inputs; the gigai-core comparison refuses
any pair whose datasets differ.
