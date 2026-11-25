# Hints: w3l4.1

## Hint 1

A thesis waits for the judge when three things hold: it has a Grade, its arm is champion or challenger, and no verdict
is stored for it. All three are facts in the journal's tables, so the query can answer them itself instead of leaving a
filter to Python. Keep the order the query already has: the order the theses were written in.

## Hint 2

The check's counterexamples: a teacher thesis that has a Grade (never judged), a thesis on another ticker (it waits
like any other), and a thesis whose stored verdict is a plain fail. A stored verdict of either kind counts: an unknown is
stored as fail, and judging either again pays twice for the same answer.
