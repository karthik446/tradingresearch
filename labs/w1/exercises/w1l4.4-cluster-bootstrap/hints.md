# Hints: w1l4.4

## Hint 1

Resample tickers, not items: a ticker's two days move together, and resampling items would pretend there are 20
independent draws. Group the diffs by `clusters[item]` first; with fewer than 10 groups raise ValueError.

## Hint 2

`rng = random.Random(seed)`; each round `rng.choices(keys, k=len(keys))`, flatten the drawn tickers' diffs, take the
mean. Sort the n means and return `means[int(n * 0.025)]`, `means[int(n * 0.975) - 1]` for level 0.95.
