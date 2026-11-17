# Claim-failure taxonomy (week 1)

Source: the 20 analyses of `run_c40caab0968e44a3` (experiment `observe`, prompt analyze-1, 10 tickers × 2026-11-12
and 2026-11-13), 229 claims. Open-coded notes are in `labels.csv`; each class below groups those notes.
"Claims" counts failing claims, "analyses" counts analyses with at least one.

| # | Class | Claims | Analyses | Caught today by | Example |
|---|---|---|---|---|---|
| 1 | window_name: an indicator named by its window ("200-day", "20-day", "14-day RSI") | 31 | 15 | code (`number_in_text`) | JPM 11-12 c2 "The 200-day average, sma_200, stood at {value}" |
| 2 | inference_wider: an inference names indicators its parents never cite | 15 | 15 | nothing directly; 9 are rejected only because a parent failed | AMZN 11-13 c4 "above sma_20, sma_50 and sma_200" from close and sma_200 |
| 3 | judgement_in_fact: a fact carries a verdict the source does not state | 33 | 19 | nothing (judge later, ADR-001) | HD 11-13 c8 "buyers finished the day in control" |
| 4 | opinion_cites: an opinion lists derived_from | 5 | 5 | code (`not_a_claim`, record rules) | CAT 11-13 c12 |
| 5 | label_in_value: a text label put in {value} with value null | 4 | 4 | code (`empty_placeholder`) | KO 11-12 c9 "labeled {value} on this date, which is bull-high" |
| 6 | number_outside_value: a number written in prose or in steps | 5 | 3 | code for prose (3); nothing for steps (2) | XOM 11-13 c10 steps quote revenue no parent cites |
| 7 | other: unknown source id, a wrong comparison, a backwards sign | 3 | 3 | code for the unknown source (1) | UNH 11-13 c10 "closer to the low side" (it is above the midpoint) |

Not a class: `bad_derivation` (14 claims) rejects an inference whose parent was rejected. It is a consequence of
classes 1, 6 and 7, so fixing those removes it.

Rates from the run itself (`tr exp run experiments/observe.toml`): `claims_valid` 0.748 (mean share of valid claims),
`all_claims_valid` 0.200 (4 of 20 analyses fully valid), `parsed` 1.000.

## What the counts say

- Class 1 is most of the code rejections (31 of 59) and a prompt rule can remove it.
- Class 2 is the largest failure the code does not see: 6 analyses pass every check with an ungrounded inference.
  It is mechanical (names in text vs names in cited sources), so it gets a code eval: `specs/inferences_grounded.md`.
- Class 3 is the largest by count but needs judgement about wording. It waits for an LLM judge with measured
  agreement (week 4), per ADR-001.
