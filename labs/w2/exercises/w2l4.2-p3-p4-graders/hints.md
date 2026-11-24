# Hints: w2l4.2

## Hint 1

Copy the shape of your P2 grader twice, with the ids the configs use (`p3_invalidation_testable`,
`p4_levels_coherent`). Only the one-line function given to `every_thesis` changes: each check takes what it reads
from the analysis's snapshot. The registry already refuses a second class with an id it holds; leave `grader` as
it is.

## Hint 2

The snapshot keeps its numbers in `values`, a dict: the last close is under "close" and the ATR under "atr_14".
P3 needs the close (for a market_open entry); P4 needs the snapshot's `levels`, then the ATR, then the close, in
the order `p4_levels_coherent` declares them.
