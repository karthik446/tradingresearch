# Hints: w1l3.2

## Hint 1

For each inference, two sets: `allowed` (every name its parents cite; `cited(parent)` already gives one parent's)
and `used` (vocab names found in text + steps). Anything used but not allowed is ungrounded.

## Hint 2

`allowed` is the union over the parents in `derived_from`; an inference with no parents allows nothing. Report
each inference with names left over as "cN: name, name", names sorted: that is the explanation the tests read.
