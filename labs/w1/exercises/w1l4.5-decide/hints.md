# Hints: w1l4.5

## Hint 1

The rule is in the config's comment, written before the run: the primary metric decides, the guard can only veto.
"Above 0" is about the interval's low end, not the mean.

## Hint 2

`return "ship" if primary_ci[0] > 0 and guard_diff >= 0 else "keep baseline"`.
