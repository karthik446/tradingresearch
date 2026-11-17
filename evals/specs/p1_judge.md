# Eval spec: p1_judge (draft, unvalidated)

**What it checks:** SPIKE §7.2 row P1, the primary process criterion: did the mechanism in the thesis's `reason`
happen, whatever the P&L? Example: "breakout from the 7-session congestion holds above `high` with rel_volume ≥ 1.5".
Code cannot read a mechanism, so a model does: *LLM-as-judge*, a second model scoring the first one's output
against a rubric (https://arxiv.org/abs/2306.05685). A judge's numbers mean nothing until it agrees with your own
blind labels (*judge validation*: https://hamel.dev/blog/posts/llm-judge/), measured with Cohen's kappa (agreement
beyond chance: https://en.wikipedia.org/wiki/Cohen%27s_kappa). Labels need closed trades, so this week the judge is
a **draft**: registered, flagged unvalidated, never reported as a rate (SPIKE §7.3; REPO-PLAN week 2).

**Where it lives:** you write both.
- `evals/rubrics/p1_thesis_quality.md`: the rubric text the judge receives. It must have these sections, each an
  `## ` heading line exactly as written:
  - `## Question`: the one question, in the words of SPIKE §7.2 P1.
  - `## Inputs`: what the judge sees: the thesis text (`prediction`, `reason`, `invalidation_text`), the analysis
    claims it cites, and the code-written post-trade summary (closes vs the cited levels, rel_volume on the trigger
    day, whether congestion `high`/`low` held, MFE/MAE, exit reason). Never raw bars; the judge computes no numbers.
  - `## Met`: what counts as the mechanism happening, with one example.
  - `## Not met`: what counts as it not happening, with one example (including "won for a different reason").
  - `## Unknown`: when the summary cannot decide (the mechanism names something code did not measure).
  - `## Hindsight`: judge the mechanism, not the outcome; a loss can be "met", a win can be "not met".
  - `## Verdict format`: the reply's last JSON object is `{"verdict": "pass" | "fail", "explanation": "..."}`;
    pass = met, fail = not met; unknown is `fail` with an explanation starting `unknown:` (SPIKE §1.3: gigai-core's
    `JudgeVerdict` is binary; abstains are excluded from kappa and counted).
- `src/tradingresearch/evals.py`: a `@grader` class with `id = "p1_judge"`, `kind = "model"`, a `version` string,
  and the class attribute `validated = False`. Week 2 makes no model call: `grade` raises `CannotGrade` with a
  message saying the judge is a draft. In week 3 it wraps gigai-core `llm_judge(provider, rubric=<the rubric file
  text>, settings=..., grader_id="p1_judge")` (`gigai_core/graders/judge.py:382`) and runs on closed trades.
  `validated` turns True only by an ADR that records kappa on the operator's labels (SPIKE §7.3 step 3).

**Inputs (week 3):** one closed champion or challenger thesis (teacher theses are never judged), its cited claims,
and the post-trade summary, as above.

**Edge cases:**
- The judge sees the outcome, as the operator does; the Hindsight section is the guard. The Earned / Lucky /
  Unlucky / Deserved-loss table (SPIKE §7.2) makes the remaining bias visible.
- A `reason` with two mechanisms: met only if both happened.
- A thesis cancelled before entry is not judged (no trade happened).

**Pass / fail means:** pass = the reason played out; fail = it did not, or the summary cannot tell (unknown). Until
`validated` is True, a P1 rate is printed only with an "unvalidated" banner, or not at all.

**Worked example:** reason "breakout from the 7-session congestion holds above high 104.0 with rel_volume ≥ 1.5";
summary: trigger-day rel_volume 1.8, two later closes 102.9 and 101.5 below 104.0, exit at stop. Verdict `fail`,
explanation "closed back inside the congestion on day 2; the breakout did not hold". Same summary with closes
104.6 and 105.2 and an exit at the time limit at a small loss: `pass` (the mechanism held; the P&L is not the
question).

**Acceptance (week 2, offline only):** `tests/test_week2.py` checks that the rubric file exists with the seven
headings above and that `GRADERS["p1_judge"]` has `kind == "model"` and `validated is False`. No model call in any
test.

**Out of scope this week:** running the judge, labels, kappa (weeks 3–4).
