# Hints: w1l3.5

## Hint 1

`dist_sma_200_atr` is the close's distance from sma_200, in ATRs. A claim that cites it has seen sma_200 too. Add
the inner name to `found` in `cited`, before the recursion.

## Hint 2

The inner name is what is left once the `dist_` prefix and the `_atr` suffix are cut off. Add it for every cited
name that has both; the recursion then carries it to the children.
