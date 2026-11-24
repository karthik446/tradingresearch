# Hints: w2l3.1

## Hint 1

Keep only the level prices strictly under the entry. The nearest of those is the highest one, and the stop must
be strictly lower than it. The levels arrive in stored order, not sorted by price.

## Hint 2

An empty list has no highest price. Say "no level under the entry, or the stop below the highest one" in that
order, so the empty case never reaches the comparison.
