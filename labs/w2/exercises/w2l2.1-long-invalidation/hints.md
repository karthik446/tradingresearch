# Hints: w2l2.1

## Hint 1

A long loses when price falls: the stop is below the entry, and the invalidation has to sit at or above the stop and
strictly below the entry. Read the three prices from `thesis.entry.price`, `thesis.invalidation_price`,
`thesis.stop`.

## Hint 2

Python chains comparisons: `a <= b < c` is one expression. Mind which side is inclusive. The close plays no part
yet: every chapter thesis has a limit entry.
