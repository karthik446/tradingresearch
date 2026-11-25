# Hints: w5l4.2

## Hint 1

A split is its parameters: the cutoff, the embargo and the Prereg it is scored by. When it was written down is not
one of them, so the id must not change when the same split is asked for again later. Make the id from the parameters
alone, and let the id decide whether the split is already stored.

## Hint 2

`hashing.digest` turns a JSON-ready dict into `sha256:` and hex; a pydantic model can dump itself as JSON with fields
left out. `find` already returns the stored split or None. Look before you write: the journal refuses a second row
with the same id. Converting an aware datetime to another zone keeps the instant and changes the date it falls on.
