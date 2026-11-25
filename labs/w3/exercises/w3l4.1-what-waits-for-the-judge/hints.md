# Hints: w3l4.1

## Hint 1

Three conditions, all in SQL: the thesis has a row in `grade` (a JOIN on thesis_id keeps only those), its arm is one of
two, and `judge_verdict` has no row for it (a correlated NOT EXISTS). Leave the ORDER BY as it is.

## Hint 2

`rowid` is the order the theses were written in. A stored verdict of either kind counts: an unknown is stored as fail,
and judging it again would pay for the same answer twice.
