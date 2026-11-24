# Hints: w2l3.1

## Hint 1

Look only at the levels on the losing side of a long, the ones priced under the entry. Of those, which would price
meet first on its way down? That is the level the stop has to clear. The levels arrive in stored order, not sorted
by price, and a level at exactly the entry sits on neither side.

## Hint 2

Two edges decide the shape. A stop exactly on that level has not cleared it. And a long can have no level under its
entry at all: then there is nothing to clear, so make sure your code never asks an empty list for its nearest price.
