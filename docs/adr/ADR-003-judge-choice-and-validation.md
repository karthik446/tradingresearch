# ADR-003: P1 judge model and validation plan

**Status:** model accepted, thresholds proposed, 2026-11-17 (week 2). The thresholds wait on operator decision Q1
(SPIKE §7.3). Measured kappa: none yet, awaiting labels.

**Context.** P1 asks whether the mechanism in a thesis's `reason` happened, win or lose (`evals/specs/p1_judge.md`).
Code cannot read a mechanism, so a second model grades it against a rubric: *LLM-as-judge*, a model scoring
another model's output (https://arxiv.org/abs/2306.05685). A judge's rate means nothing until it agrees with the
operator's own blind labels (https://hamel.dev/blog/posts/llm-judge/). Agreement is measured as Cohen's kappa,
agreement beyond chance (https://en.wikipedia.org/wiki/Cohen%27s_kappa). This week the judge is a registered draft,
`validated = False`, and makes no model call.

**Decision.** Judge model:

| Role | Model | Price per 1M tokens in / out | Why |
|---|---|---|---|
| Judge | `openai/gpt-6-sol` | $2 / $10 (`:batch` $1 / $5) | SPIKE §9.1 default; a different vendor from the writer `anthropic/claude-sonnet-5.5` (`thesis.py` DEFAULT_MODEL), so the judge is not grading its own vendor's model. Self-preference, a judge favouring its own outputs: https://arxiv.org/abs/2404.13076 |
| Budget fallback | `openai/gpt-6-luna` | $0.10 / $0.50 (`:batch` $0.05 / $0.25) | SPIKE §9.1 alternative; used only if it passes the same validation |

Prices were read from https://openrouter.ai/api/v1/models at 2026-11-17T04:42:35Z. That list also has
`openai/gpt-6.1-sol` at the same price; it was not a SPIKE §9.1 candidate and is not chosen here. Cost per closed
trade is a SPIKE §9.2 estimate, not a measurement: about 4,000 tokens in and 500 out, ≈ $0.013 on `gpt-6-sol`.

Validation plan (SPIKE §7.3):

| Step | When | Rule |
|---|---|---|
| 1. Labels | about 15 in week 3, 30 by week 4, as trades close | The operator labels P1 blind to the judge (`LabelRecord` with `blind=True`, through a `tr label` command not built yet), stratified across horizons where possible |
| 2. Agreement | once 30 labels exist | gigai-core `judge_agreement` and `cohen_kappa`; stored as a `JudgeValidationRecord` |
| 3. Use | after step 2 | κ ≥ 0.6 (gigai-core `MIN_KAPPA`, `agreement.py:17`): P1 rates are printed with the banner "κ = x on n = 30". κ < 0.6: fix the rubric and re-run on the same 30 labels, up to 3 rounds; if it still fails, P1 comes from operator labels only |
| 4. Re-check | any change to the judge model, rubric or prompt; otherwise every 2 weeks | label 10 new trades and re-run the judge on every labelled trade |

Abstains: when the post-trade summary cannot decide, the judge returns `fail` with an explanation starting
`unknown:`. Those items are counted and left out of kappa (`p1_judge.md`, SPIKE §1.3).

**Consequences.**
- gigai-core's own gate needs `MIN_UNITS = 126` labels (`agreement.py:18`, `validation_passes` at `:157`), so it fails
  by construction at 30. Following SPIKE's recommended option (a), the judge stays "descriptive, not validated" in
  gigai-core's sense even when κ ≥ 0.6, and the banner always shows n.
- With 30 labels the 95% half-width of kappa is about ±0.29 (a SPIKE §7.3 large-sample estimate), so a κ of 0.6 means
  anywhere from about 0.31 to 0.89. The threshold separates a working judge from a broken one; it does not rank judges.
- `validated` in `evals.py` turns True only through a later ADR that records the measured kappa.
- Teacher theses are never judged; a thesis cancelled before entry is not judged.

**Readings.** Zheng et al. on LLM-as-judge (https://arxiv.org/abs/2306.05685); Husain on validating a judge against
your own labels (https://hamel.dev/blog/posts/llm-judge/); Shankar et al. on criteria drifting while you label
(https://arxiv.org/abs/2404.12272); Panickssery et al. on self-preference (https://arxiv.org/abs/2404.13076).
