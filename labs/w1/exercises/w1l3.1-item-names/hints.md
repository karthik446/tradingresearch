# Hints: w1l3.1

## Hint 1

`expected` is what a grader gets next to the model output. Today it holds `values` (source id → number). The new
grader needs source id → name (`sma_200`), and `ctx.rows` has both on every row.

## Hint 2

`expected={"values": ctx.values(), "names": {row.source_id: row.name for row in ctx.rows}}`. Note the dataset hash
moves: a run made before this change used a different dataset.
