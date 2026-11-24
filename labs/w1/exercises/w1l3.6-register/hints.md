# Hints: w1l3.6

## Hint 1

`graders(names)` looks names up in `GRADERS`; anything not there exits. Which line builds `GRADERS`, and which
classes can it hold right now? Configs keep naming the graders that are already there.
Then run the observe command: the analyses it flags should be the ones you labelled `inference_wider` in lab w1l2.

## Hint 2

The registry is keyed by each grader's `id`, so the new class is found by the name a config uses. If the flags
and labels still differ, print both lists and read those analyses: that disagreement is the spec's acceptance test.
