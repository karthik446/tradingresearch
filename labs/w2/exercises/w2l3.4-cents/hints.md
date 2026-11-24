# Hints: w2l3.4

## Hint 1

Round, do not truncate: 338.699 must become 338.70, and a market_open close of 343.4138 must become 343.41.
Every price goes through the same helper before any comparison: the entry (after `entry_price` picks it), the
stop, the target and each level. Then the existing below/above filters and comparisons need no change.

## Hint 2

The ATR is not a price, so the allowance is left as computed. Rounding it too moves the target boundary by up to
half a cent, and a test sits exactly there.
