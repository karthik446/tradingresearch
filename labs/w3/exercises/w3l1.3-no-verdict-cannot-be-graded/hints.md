# Hints: w3l1.3

## Hint 1

Three verdicts are readable: pass, fail and unknown, as lower-case strings. Anything else (no object, no key, null,
maybe, Pass, a reply cut off mid-object) is a reply the rubric does not define. Do not turn it into a fail or an
abstain: refuse it with the exception for "nothing to grade" that evals.py already imports.

## Hint 2

Check before anything reads the verdict further, and check for exact equality with one of the three words: a verdict
with a space in front, a hedge such as pass/fail, or a list holding pass are all undefined. The refusal's message should
show what the judge sent, so a reply of a few words appears whole.
