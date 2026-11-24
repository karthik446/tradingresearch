# Hints: w1l3.6

## Hint 1

`graders(names)` looks names up in `GRADERS`; anything not there exits. Add the class to the tuple that builds it.
Then run the observe command: the analyses it flags should be the ones you labelled `inference_wider` in lab w1l2.

## Hint 2

`GRADERS = {grader.id: grader for grader in (Parsed, ClaimsValid, AllClaimsValid, InferencesGrounded)}`. If the flags
and labels still differ, print both lists and read those analyses: that disagreement is the spec's acceptance test.
