# Hints: w1l4.2

## Hint 1

For `replay`: `load` gives the arms, items and grader ids; `registry` turns the ids into graders. For each arm,
take the recording of its prompt, keep only the config's ticker-days, and grade every reply with `score`. A `None`
means the grader could not grade that reply: leave it out of the mean.

## Hint 2

For the config: copy the shape of `experiments/observe.toml` (same model, tickers and sessions), add a second arm
that differs only in its prompt, and add the lab w1l3 grader. The top comment pre-registers the decision before any
run: the primary metric and the guard metric, each named by its grader id. Run the observe to see what the arms
score on the recorded replies.
