# Hints: w2l1.2

## Hint 1

Every claim has a `tag`: one of `fact`, `inference`, `opinion`, lower case (see `records.py`). Rule 2 reads the tag,
not the wording or the parents.

## Hint 2

The rule is per evidence id, so it belongs in `evidence_ok` next to rule 1, not in `p2_evidence_valid`. Only
`opinion` fails here: an inference is still evidence.
