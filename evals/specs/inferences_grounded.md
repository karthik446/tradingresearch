# Eval spec: inferences_grounded

**Failure it measures:** taxonomy class 2. An inference names an indicator (sma_20, ema_9, ...) that none of its
parents cite, so the conclusion rests on a number the reader cannot trace. In the observe run 15 of 20 analyses
have one, and 6 of those pass every existing check.

**Unit and score:** one analysis. Score 1 if every inference is grounded, 0 if any is not (binary, so experiments
compare it with McNemar). The explanation lists the claims and names, e.g. `c4: sma_20, sma_50`.

**Rule:** for each claim tagged `inference`:
1. allowed = the table names of every source cited by its `derived_from` claims, followed recursively through
   parent inferences. A cited `dist_<name>_atr` also allows `<name>`.
2. used = every table name containing an underscore that appears as a whole token in `text` or `steps`.
   Names without an underscore (close, open) are skipped because they are also English words.
3. The inference is grounded if used ⊆ allowed.

**Inputs:** the parsed reply and `expected["names"]` (source id → table name), added to each dataset item by
`item_for`. Output that did not parse raises CannotGrade (it is already counted by `parsed`).

**Acceptance (all must hold before the grader is registered):**
- On `run_c40caab0968e44a3` it flags exactly the 15 analyses labelled `inference_wider` in `labels.csv`, no more.
- AMZN 2026-11-13 c4 gives `c4: sma_20, sma_50`; MSFT 2026-11-13 c6 (cites all four averages it names) passes.
- `sma_20` does not match inside `sma_200` or `dist_sma_20_atr`.
- Tests in `tests/test_evals.py` use claims copied from that run, not invented ones.

**Out of scope:** whether the inference is true (a judge question), and numbers in steps (class 6, 2 claims; too
few to pay for a grader this week).
