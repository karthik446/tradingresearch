# Hints: w1l1.1

## Hint 1

`values` is the SOURCES table as a dict: source id to number. "In the table" means "a key of `values`". Collect the
cited ids that are not keys, in the order they are cited, and reject the claim if there are any.

## Hint 2

Order matters: the fact branch below reads `values` with every cited id, which is the KeyError you see. Your check
has to run before anything looks a cited id up. The detail is the unknown ids, comma-separated.
