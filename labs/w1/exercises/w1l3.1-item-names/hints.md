# Hints: w1l3.1

## Hint 1

`expected` is what a grader gets next to the model output. Today it holds `values` (source id → number). The new
grader needs source id → name (`sma_200`), and `ctx.rows` has both on every row.

## Hint 2

Put the names next to `values` in `expected`, keyed by source id the same way. Note the dataset hash moves: a run
made before this change used a different dataset.
