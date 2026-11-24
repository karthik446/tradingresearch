# Hints: w1l4.4

## Hint 1

Resample tickers, not items: a ticker's two days move together, and resampling items would pretend there are 20
independent draws. Group the diffs by `clusters[item]` first; with fewer than 10 groups raise ValueError.

## Hint 2

Seed one `random.Random` and, each round, draw as many tickers as there are, with replacement; the round's mean is
over all diffs of the drawn tickers. Sort the n means; the low end sits at position n × 0.025 (rounded down), the high
end just before position n × 0.975.
