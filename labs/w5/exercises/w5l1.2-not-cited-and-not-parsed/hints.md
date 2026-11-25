# Hints: w5l1.2

## Hint 1

A score of 1.0 would say every claim about the section is grounded, and 0.0 that none is; with no claim about it,
neither is true, so the grader declines instead of scoring. Declining is CannotGrade, and the runner records it as
no score. Decide the parse question first, because an unparsed reply has no claims to look at.

## Hint 2

The parse status is a string on the sample, and only one of its values means the reply parsed; a parsed reply can
still be a dict with no claims list. For the explanation, collect the reason of each failing citing claim, keep each
reason once, sort them, and count failing against citing claims for this section only.
