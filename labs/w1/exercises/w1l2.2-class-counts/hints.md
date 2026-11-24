# Hints: w1l2.2

## Hint 1

"Analyses per class" counts rows, not mentions. Turn each row's `classes` into a set first, then add the set to a
`Counter`.

## Hint 2

`{name.strip() for name in (row["classes"] or "").split(";")} - TAGS - {""}` is the set for one row; `csv.DictReader`
gives `row`. `counts.update(that_set)`, then `return dict(counts)`.
