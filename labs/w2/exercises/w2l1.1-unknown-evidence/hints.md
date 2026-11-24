# Hints: w2l1.1

## Hint 1

`claims` is a tuple, and `thesis.evidence` holds ids. Build a dict from `claim_id` to claim once, then look each
evidence id up with `.get`, which gives None for an id no claim has. `evidence_ok` gets that claim (or None) and
decides.

## Hint 2

Two places change. In `p2_evidence_valid`: every id must pass (`all(...)` over the ids, not over the claims). In
`evidence_ok`: rule 1 is the first test, a None claim fails before anything reads its fields.
