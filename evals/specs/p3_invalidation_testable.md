# Eval spec: p3_invalidation_testable

**What it checks:** SPIKE §7.2 row P3. A thesis states an `invalidation_price`: the price at which its idea is
wrong. P3 asks whether code can test that price: it must lie between the entry and the stop, or equal the stop.
An invalidation on the profit side of the entry, or beyond the stop, can never be the first thing the market
reaches before the stop, so it says nothing testable. One of the code checks of *process grading*
(https://arxiv.org/abs/2305.20050).

**Where it lives:** you write it.
- `src/tradingresearch/checks.py`: `p3_invalidation_testable(thesis: Thesis, reference_close: float) -> bool`
  - `thesis`: a `records.Thesis`; reads `direction`, `entry`, `stop`, `invalidation_price`.
  - `reference_close`: the analysis snapshot's last close (`analysis.snapshot.values["close"]`). Used only when
    `thesis.entry.kind == "market_open"` (no entry price yet; SPIKE §1.1 Thesis rule 1, as
    `thesis.reference_price` does).
- `src/tradingresearch/evals.py`: a `@grader` class with `id = "p3_invalidation_testable"`, `kind = "code"`,
  `version = "1"`. Same sample handling as `p2_evidence_valid` (thesis-run sample, items built with
  `thesis.build`, `reference_close` from the snapshot). Score 1 if every built thesis passes, else 0; CannotGrade
  when the output did not parse or no item builds.

**Rule:** E = `entry.price`, or `reference_close` for a `market_open` entry; I = `invalidation_price`; S = `stop`.
- long: S ≤ I < E.
- short: E < I ≤ S.

**Edge cases:**
- I equal to the stop passes (the stop is the invalidation).
- I equal to the entry fails (it would trigger on the fill).
- For `stop` and `limit` entries `reference_close` is ignored, even if it would change the answer.
- `tr thesis` already refuses a thesis that breaks this rule (`thesis.check_thesis`, reason `invalidation`), so on
  stored theses P3 should be all ones; it earns its place on teacher theses, other writers and hand edits.

**Pass / fail means:** pass = reconcile can watch one price and know the idea failed before the stop. Fail = the
invalidation is decoration.

**Worked example:** long, `market_open`, stop 96, invalidation 101. With `reference_close = 100`: 96 ≤ 101 < 100 is
false, so it fails. With `reference_close = 102`: 96 ≤ 101 < 102 holds, so it passes. The same thesis with a `stop`
entry at 102 passes whatever `reference_close` is.

**Acceptance:** `tests/test_week2.py` runs every case in `tests/fixtures/week2/p3_invalidation_testable.json`
(long and short, market_open, stop equal to invalidation) and checks the registry entry.

**Out of scope:** whether `invalidation_text` describes the same price (a judge question); whether the stop
respects the stop floor (`thesis.stop_floor`, checked at write time).
