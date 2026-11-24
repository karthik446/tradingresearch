# Hints: w1l2.2

## Hint 1

"Analyses per class" counts rows, not mentions: a row that lists a class twice still adds one. Tidy each row's
names first (spaces, empty pieces, the tags in `TAGS`), then count each distinct name once for that row.

## Hint 2

The `classes` cell can be empty or missing: both mean no classes. A `Counter` adds one for every name you hand
it, so hand it each name of a row once. The fixture labels.csv repeats a class in a row on purpose.
