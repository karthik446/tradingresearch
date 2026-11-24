# Hints: w1l4.5

## Hint 1

The rule is in the config's comment, written before the run: the primary metric decides, the guard can only veto.
"Above 0" is about the interval's low end, not the mean.

## Hint 2

Two conditions, both needed to ship: the primary interval lies wholly above 0, and the guard did not drop. Anything
else keeps the baseline. The two answers are the strings the docstring names.
