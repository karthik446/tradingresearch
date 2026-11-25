# Hints: w5l1.3

## Hint 1

Look at how the shipped graders that already take a drop do it: evals.graders sets the arm's list on each grader it
builds, and the grader turns it into the hidden row ids validate_claims understands. The section grader needs the
same attribute and the same hand-over, and four small subclasses that only name a section.

## Hint 2

Two arms build their graders from the same classes in one run, so anything set on the class is shared by every arm.
Give the class an empty default that is never mutated, let evals.graders replace it on the instance, and compute the
hidden ids from the expected rows on every call rather than caching them.
