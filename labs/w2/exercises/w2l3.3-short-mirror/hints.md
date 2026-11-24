# Hints: w2l3.3

## Hint 1

A short loses when price rises, so the sides swap: the stop is judged against the levels over the entry and the
target against the levels under it. Swap the sides and the comparisons together; changing only one of them gives
a rule that passes stops sitting inside the level.

## Hint 2

The nearest level over the entry is the lowest of those prices; the next one under it is the highest of those.
The allowance now lets the target run below that level, and reaching it exactly still passes.
