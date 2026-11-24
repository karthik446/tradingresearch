# Hints: w1l4.5

## Hint 1

The rule is in the config's comment, written before the run: the primary metric decides, the guard can only veto.
"Above 0" is about the interval's low end, not the mean.

## Hint 2

Before you run anything, predict the answer for each of these, then check your function agrees:
CI (0.0, 0.6) with guard 0; CI (1e-9, 0.6) with guard 0; CI (0.45, 0.95) with guard -1e-9; CI (0.01, 0.1) with
guard +0.5. If one of your answers turned on how big a number is, rather than on which side of 0 it sits, look at the
rule again: it has no margin anywhere, and the guard has no say unless it got worse.
