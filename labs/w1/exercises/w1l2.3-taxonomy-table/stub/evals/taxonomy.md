# Claim-failure taxonomy (week 1)

Source: the 20 analyses of `run_c40caab0968e44a3` (experiment `observe`, prompt analyze-1, 10 tickers × 2026-11-12
and 2026-11-13), 229 claims. Open-coded notes are in `labels.csv`; each class below groups those notes.
"Claims" counts failing claims, "analyses" counts analyses with at least one.

| # | Class | Claims | Analyses | Caught today by | Example |
|---|---|---|---|---|---|
| 1 | window_name: an indicator named by its window ("200-day", "20-day", "14-day RSI") | 31 | 15 | code (`number_in_text`) | JPM 11-12 c2 "The 200-day average, sma_200, stood at {value}" |

<!-- TODO(w1l2.3): one row per class your notes show, 5 to 8 rows: `name: definition`, failing claims, analyses,
what catches it today ("code (`reason`)" or "nothing ..."), one real example as `TICKER MM-DD cN "quote"`.
Then say what is not a class, the run's rates, and what the counts say. -->
