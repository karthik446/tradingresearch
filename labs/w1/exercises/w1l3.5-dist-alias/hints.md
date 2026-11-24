# Hints: w1l3.5

## Hint 1

`dist_sma_200_atr` is the close's distance from sma_200, in ATRs. A claim that cites it has seen sma_200 too. Add
the inner name to `found` in `cited`, before the recursion.

## Hint 2

`found |= {name[5:-4] for name in found if name.startswith("dist_") and name.endswith("_atr")}`.
