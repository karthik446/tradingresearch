# Hints: w3l3.2

## Hint 1

Your p1_verdict already does the reading, unknown and no-verdict included: let its CannotGrade pass through. Every field
the Score and the ScoreRecord need is in scope (the judge, the sample, the spans, P1Judge, JUDGE_MODEL), and evals.py
already imports `new_id` for a fresh score id ("sc" prefix).

## Hint 2

A sqlite3 connection is a context manager: inside `with conn:` everything commits together at the end, or rolls back
if anything raises. `journal._insert_score` does not commit on its own; `add_judge_verdict` opens its own `with conn:`,
which commits when it ends: what was written before it lands with it, what comes after it is on its own. The verdict
row names the score id, too.
