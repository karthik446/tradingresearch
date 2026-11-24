# Hints: w1l4.4

## Hint 1

Resample tickers, not items: a ticker's two days move together, and resampling items would pretend there are 20
independent draws. Group the diffs by `clusters[item]` first; with fewer than 10 groups raise ValueError.

## Hint 2

Seed one `random.Random` and, each round, draw as many tickers as there are, with replacement; the round's mean is
over all diffs of the drawn tickers. For the bounds, think in shares of the sorted means: `level` is the share the
interval keeps, and what it leaves out is split evenly between the two tails, so a smaller `level` moves both ends in
towards the middle. Then check your indices on a tiny case by hand: with n = 2 and level 0.5, which of the two means
is each end? The page's "Which percentile" paragraph says how this lab rounds.
