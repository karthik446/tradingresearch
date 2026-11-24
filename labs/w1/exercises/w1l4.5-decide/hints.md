# Hints: w1l4.5

## Hint 1

The rule is in the config's comment, written before the run: the primary metric decides, the guard can only veto.
"Above 0" is about the interval's low end, not the mean.

## Hint 2

Ask two questions, both answered before the run. Which end of the primary interval decides, and compared with what
number? That condition is what stops you shipping an effect that could be zero or negative. May the guard drop at all,
even by a hair? That condition is what stops you buying the gain with a regression. Ship only when both hold;
anything else keeps the baseline, and the two answers are the strings the docstring names. Then try your function at
the edges: a low end of exactly 0, a tiny one above 0, a guard of exactly 0 and a tiny drop below it.
