# Hints: w2l1.4

## Hint 1

"Close enough" is already decided for you somewhere in the file: relative to the larger number, edge included. The
caller can loosen or tighten it, so ask which tolerance your check should honour, the one it was handed or the
module's default.

## Hint 2

A fact can match one of its sources and miss the others: HD swing's close fact of 1.0 citing sources that hold 5, 6
and 1 matches the third. Does it trace to the table? Then the edges: a fact that states no number, a fact that
states 0.0, a cited row that holds None, and a fact of 0.004 against a source of 0.004 (no rule here works in
cents).
