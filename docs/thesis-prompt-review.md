# thesis-1 prompt review (week 2)

What this is: a read of every item `prompts/thesis-1.txt` produced on its first live session, checked against the
prompt's own rules and the P4 spec (`evals/specs/p4_levels_coherent.md`). No trade has settled yet, so this is about
form, not results. It proposes changes; it does not create thesis-2. A change ships only after a paired run against
thesis-1 on the same analyses, as ADR-002 did for analyze-2.

## What was produced

Session 2026-11-16, writer `anthropic/claude-sonnet-5.5`, 6 tickers × 3 horizons = 18 items: 6 theses,
12 no_trades, 0 rejections. The 6 thesis runs each scored 1.0 on the code checks and cost $0.123590 together
(`data/runs`, 2026-11-17). All 6 theses are PROPOSED; their entry windows open 2026-11-17 14:30 UTC.

| Ticker, horizon | Setup | Entry (limit) | vs close | Stop | Target | Risk / floor | Reward : risk | P4 at cents |
|---|---|---|---|---|---|---|---|---|
| AAPL swing | pullback_to_level | 343.41 (level_hvn_2) | −1.16 ATR | 338.70 (= level_pivot_low_2) | 360.83 (high_20) | 4.71 / 2.01 | 3.70 | fail: stop on the level |
| HD swing | pullback_to_level | 335.71 (sma_20) | −1.37 ATR | 332.56 (= sma_200) | 349.18 (level_hvn_4) | 3.15 / 2.15 | 4.28 | fail: stop above level_hvn_3 319.08 |
| JPM short | range_fade | 336.67 (congestion low) | −0.21 ATR | 334.80 | 340.01 (sma_50) | 1.87 / 1.83 | 1.79 | pass |
| JPM swing | pullback_to_level | 335.11 (level_hvn_1) | −0.42 ATR | 332.80 | 344.40 (level_pivot_high_1) | 2.31 / 1.83 | 4.02 | pass |
| XOM short | pullback_to_level | 163.38 (level_hvn_1) | −0.81 ATR | 160.11 (= low_20) | 168.75 (level_hvn_2) | 3.27 / 1.07 | 1.64 | fail: stop on the level |
| XOM swing | pullback_to_level | 163.38 (level_hvn_1) | −0.81 ATR | 160.11 (= low_20) | 169.64 (level_pivot_high_1) | 3.27 / 1.07 | 1.91 | fail: stop on the level |

Floor = max(0.5% of entry, 0.25 × atr_14). The ATR term was the larger one in all 6, so the floor the input shows
"at the close" equals the floor at the limit price. P4 here applies the spec's rule at cents, as the P4 spec's
week-2-end amendment says: entry, stop, target and every level rounded to 2 decimals.

No_trades: all 6 day horizons, 4 short (AAPL, HD, KO, AMZN), 2 swing (KO, AMZN). Each gives a concrete reason: no
gap or event for the day window, price pinned under a level, a breakout with no level above for a target, or
reward below risk (AMZN: about 9 USD of risk for about 6 of reward).

## Findings and proposed changes

1. **Stops sit on a level, not beyond it (4 of 6 fail P4).** AAPL's stop is level_pivot_low_2 itself (338.70) and
   both XOM stops are low_20 itself (160.11). HD's stop is sma_200, which is not a level; the nearest level below the
   entry is level_hvn_3 at 319.08. Rule 2 says "beyond the nearest level against the trade" but defines neither
   "beyond" nor "level". Proposed: "a level is a `level_*` row, high_20 or low_20; moving averages are not levels.
   Beyond means past it: for a long, stop < level; for a short, stop > level."
2. **The prompt says code rejects what code does not check.** "Beyond the nearest level" (rule 2) and rule 6 sit
   under "Rules code checks (a thesis that breaks one is rejected)", but `thesis.check_thesis` checks only order,
   floor, invalidation, hold, evidence and window. Level placement is graded later by P4. Proposed: move both into a
   separate "graded after the fact" list, or enforce them in `check_thesis`. One of the two, not both.
3. **Rounding: the input shows one value, P4 compares another.** The SOURCES table prints levels to 6 significant
   digits (343.41, 163.377, 335.114, 160.11), rule 7 says round to cents, and the stored levels are unrounded
   (343.40978…, 163.37702…, 335.11379…, 160.1101). Compared on raw floats, 4 of the 6 P4 verdicts flip (AAPL and both XOM pass, JPM swing
   fails), because an entry like 343.41 sits a fraction of a cent above "its" level. The P4 amendment now compares
   at cents. Proposed on the prompt side: print level rows at cents in the thesis input, so the value the model
   copies is the value that is graded.
4. **Rule 6 and P4 disagree on targets.** XOM swing's target 169.64 is past the next level (level_hvn_2 168.75), so
   it breaks rule 6 as written, yet it passes P4, whose allowance is 0.5 × ATR = 2.15 (up to 170.90). Proposed:
   state the allowance in the prompt, or drop it from P4.
5. **Limit entries far below the close.** AAPL swing waits 1.16 ATR (2.66%) below the close and HD swing 1.37 ATR
   (3.40%). The model's own AAPL short no_trade says that same level, 2.7% below, makes "a one-session limit fill
   unlikely"; for the two-session swing window it took it. An unfilled limit ends EXPIRED (`window_missed`): not a
   trade, but counted in the fill rate (SPIKE §6.5). Proposed: no rule yet. Read the fill rate from reconcile first,
   then decide whether to cap the entry's distance from the close.
6. **The evidence does not cover the plan's levels.** HD cites the close, level_hvn_4 (its target) and rsi_14. No
   cited claim covers its entry (sma_20) or stop (sma_200), and no claim in its analysis mentions either one. Rule 7
   allows SOURCES numbers, and P2 checks only that the cited claims are valid. Candidate for a prompt variant: at
   least one cited claim names the entry or stop level. Expect more no_trades; test it before shipping.
7. **Two mechanisms in one reason.** XOM swing's reason adds "strong Q3 earnings" (its analysis has CY2026Q3 EDGAR
   claims) to a level pullback, and works out a ratio in prose ("about 1.9 times the risk"; it is 6.26 / 3.27 = 1.91).
   The P1 judge counts a two-mechanism reason as met only if both happened, and the post-trade summary measures no
   earnings effect, so the likely verdict is `unknown` (`evals/specs/p1_judge.md`). Proposed: one mechanism per
   reason, and it must be one the post-trade summary measures (closes against levels, rel_volume, a congestion
   bound that held).
8. **One setup recorded twice.** XOM short and XOM swing share entry 163.38 and stop 160.11 and differ only in target.
   A stop-out loses on both, and per-thesis rates count one idea twice. Proposed: report P-rates and R grouped by
   ticker-session as well as per thesis; leave the prompt alone until this happens often.

Watch, no change proposed after one session: all 6 theses are long limit pullbacks or fades (every snapshot was in
the bull-high regime); every swing chose hold_sessions 10 and every short chose 3, regardless of target distance;
JPM short clears its stop floor by 0.04 (1.87 against 1.83).

Numbers in this file: the journal (`data/journal.db`, thesis, no_trade and analysis rows for 2026-11-16), the 6 thesis
run files in `data/runs`, `thesis.py` (floor), and the P4 spec rule, recomputed from the stored snapshots.
