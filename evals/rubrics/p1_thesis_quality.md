# P1 rubric: did the reason play out (draft, unvalidated)

Spec: `evals/specs/p1_judge.md` (SPIKE §7.2 row P1). This text is the judge's rubric; `evals/rubrics/p1_judge_prompt.txt`
wraps it. Until an ADR records kappa on the operator's blind labels, no P1 rate is reported from it.

## Question

Did the mechanism in `reason` happen? Judge whether the specific market behaviour the thesis names in its `reason`
took place after the entry, for example "breakout from the 7-session congestion holds above `high` with
rel_volume ≥ 1.5", whatever the profit or loss.

## Inputs

You see three things, and nothing else:

- The thesis text: `prediction`, `reason` and `invalidation_text`.
- The analysis claims the thesis cites as evidence, each with its tag (fact or inference) and its number.
- The post-trade summary, written by code: the closes after entry compared with the levels the thesis cites,
  rel_volume on the trigger day, whether the congestion `high` / `low` held, MFE and MAE in R, and the exit reason
  (stop, target, time limit, invalidation).

You never see raw bars and you compute no numbers. Every number you rely on must be in the summary or a cited
claim; if the mechanism needs a number that is not there, the verdict is unknown (below).

## Met

The mechanism the `reason` names happened, as the summary shows it. When the `reason` names two mechanisms, both
must have happened.

Example: reason "breakout from the 7-session congestion holds above high 104.0 with rel_volume ≥ 1.5"; summary:
trigger-day rel_volume 1.8, the next closes 104.6 and 105.2, exit at the time limit at a small loss. The breakout
held with the stated volume, so it is met, even though the trade lost money.

## Not met

The mechanism did not happen: the level broke, the volume condition failed, the move went the other way, or the
trade made money for a reason the thesis did not name.

Example: same reason; summary: trigger-day rel_volume 1.8, then closes 102.9 and 101.5 below 104.0, exit at the
stop. The price closed back inside the congestion on day 2, so the breakout did not hold: not met.

Example of "won for a different reason": reason "pullback holds the 20-day low at 95.0" (stop 93.0); summary: price
closed at 94.2, below the level, on day 1, then gapped up on earnings to the target. The level did not hold; the win
came from the gap, so it is not met.

## Unknown

The summary cannot decide, because the mechanism names something code did not measure (for example "sector
rotation into semiconductors", "short covering", "the market reacts to the CPI print"), or a cited level or
condition is missing from the summary. Do not guess from the price path or the outcome.

## Hindsight

Judge the mechanism, not the outcome. A losing trade can be met (the reason played out, the market still went
against it); a winning trade can be not met (it won for a reason the thesis did not give). Do not let the exit
reason or the P&L decide the verdict; use them only where the `reason` itself names them.

## Verdict format

Reason it through first, then end the reply with one JSON object on its own line, the last JSON object in the
reply:

{"verdict": "pass", "explanation": "one sentence"}

- `pass` = met.
- `fail` = not met.
- Unknown is `fail` with an explanation that starts with `unknown:` (for example
  `{"verdict": "fail", "explanation": "unknown: the reason names sector rotation, which the summary does not measure"}`).
  The verdict is binary (gigai-core `JudgeVerdict`); unknowns are excluded from kappa and counted.

Use exactly the keys `verdict` and `explanation`, the verdict in lower case.
