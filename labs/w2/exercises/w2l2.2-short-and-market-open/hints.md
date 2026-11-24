# Hints: w2l2.2

## Hint 1

A short loses when price rises: the stop is above the entry, the invalidation strictly above the entry and at most
the stop. The inclusive end is the stop on both sides.

## Hint 2

`entry_price(thesis, reference_close)` is already in the file: the close for a market_open entry, the entry's own
price otherwise. Use it for both directions, so a short market_open works too.
