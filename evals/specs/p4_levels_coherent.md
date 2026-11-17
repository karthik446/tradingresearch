# Eval spec: p4_levels_coherent

**What it checks:** SPIKE §7.2 row P4. Code computes support and resistance levels (SPIKE §5: HVN levels,
pivots, high_20/low_20). P4 asks whether the thesis's stop and target respect them: the stop sits beyond the
nearest level against the trade, and the target is at or before the next level in the trade's direction, allowing
0.5·ATR past it. A stop inside the nearest level is hit by ordinary noise; a target far past the next level asks
price to break through it first. One of the code checks of *process grading* (https://arxiv.org/abs/2305.20050).

**Where it lives:** you write it.
- `src/tradingresearch/checks.py`:
  `p4_levels_coherent(thesis: Thesis, levels: tuple[Level, ...], atr14: float, reference_close: float) -> bool`
  - `thesis`: a `records.Thesis`; reads `direction`, `entry`, `stop`, `target`.
  - `levels`: `analysis.snapshot.levels` (every kind counts).
  - `atr14`: `analysis.snapshot.values["atr_14"]`.
  - `reference_close`: the snapshot's last close; the entry for a `market_open` thesis, as in P3.
- `src/tradingresearch/evals.py`: a `@grader` class with `id = "p4_levels_coherent"`, `kind = "code"`,
  `version = "1"`. Same sample handling as `p2_evidence_valid`. Score 1 if every built thesis passes, else 0.

**Rule:** E = `entry.price`, or `reference_close` for `market_open`.
- long: let L = the highest level price below E, U = the lowest level price above E.
  Pass if `stop < L` and `target ≤ U + 0.5·atr14`.
- short: let U = the lowest level price above E, L = the highest level price below E.
  Pass if `stop > U` and `target ≥ L − 0.5·atr14`.

**Edge cases:**
- "Beyond" is strict: a stop exactly on the level fails.
- The target allowance is inclusive: exactly 0.5·ATR past the level passes.
- No level on a side: that half of the rule holds (a breakout to a new high has no level above to respect).
- A level exactly at E is neither above nor below and is ignored.
- `atr14` scales the allowance: a target 2 past the level passes with ATR 4 and fails with ATR 2.
- For a `market_open` entry the reference decides which levels are "nearest": the same stop can pass from one
  close and fail from another.

**Pass / fail means:** pass = stop and target are placed where the analysis's own levels say they should be.
Fail = the plan ignores the map code drew for it.

**Worked example:** levels 90, 95, 105, 110, 115; ATR 4; long, stop entry at 101. L = 95, U = 105. Stop 94 < 95
and target 107 ≤ 105 + 2 pass. Target 108 fails (3 past the level, > 2). Stop 95 fails (on the level, not beyond).

**Acceptance:** `tests/test_week2.py` runs every case in `tests/fixtures/week2/p4_levels_coherent.json` (long and
short, market_open, target beyond the next level by more than 0.5·ATR vs within) and checks the registry entry.

**Out of scope:** level strength and kind (all levels count equally); reward-to-risk ratio; whether the setup type
fits the levels (P1).
