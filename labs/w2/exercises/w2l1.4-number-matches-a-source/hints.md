# Hints: w2l1.4

## Hint 1

`close_within(a, b, tolerance)` is already in the file: relative to the larger magnitude, edge included. Pass it the
`tolerance` argument, not the module constant.

## Hint 2

A fact whose `value` is None passes (test `is None`; 0.0 is a value). Otherwise collect the cited sources' values,
drop the ones that are None, and pass if any one of the rest is close.
