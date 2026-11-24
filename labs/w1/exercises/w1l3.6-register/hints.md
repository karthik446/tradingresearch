# Hints: w1l3.6

## Hint 1

Run the check and read the exit message: it prints the names the registry knows. Find where in `evals.py` that
set of names comes from. Configs keep naming the graders that are already there, so none of them may drop out.
Then run the observe command: the analyses it flags should be the ones you labelled `inference_wider` in lab w1l2.

## Hint 2

Two readers use the registry: `graders()` and `labs/w1/tools/regrade.py`. A change only one of them sees leaves the
other one broken. If the flags and labels still differ once the grader is found, print both lists and read those
analyses: that disagreement is the spec's acceptance test.
