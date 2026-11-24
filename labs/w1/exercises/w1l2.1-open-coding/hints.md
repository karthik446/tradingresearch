# Hints: w1l2.1

## Hint 1

For `tally_notes`: index both files by analysis_id (the run's traces and your rows), then walk the run in its own
order, so the four lists come out in that order. A row whose analysis_id is no trace of the run goes to `unknown`.
`rejected(trace)` lists the claims the code checks reject: a `first_failure` among them was caught, any other
claim is one only a reader saw.

## Hint 2

For the notes: work one analysis at a time and ask "what would a reader object to first?". That claim is
`first_failure`, and `-` means clean (the author has one: KO 2026-11-13). If the first rejected claim is an
inference rejected as `bad_derivation`, look at its parents: the parent's failure is the note. Do not stop at
rejected claims: AMZN 2026-11-13 passes every check and still has c4 naming sma_20 and sma_50 it never cited. Leave
`classes` empty; they come in w1l2.4. Run the observe after every few rows.
