# Hints: w1l1.1

## Hint 1

`values` is the SOURCES table as a dict: source id to number. "In the table" means "a key of `values`". Collect the
cited ids that are not keys, keep their order, and return early if there are any.

## Hint 2

The check must come before the `tag == "fact"` block: that block reads `values[s]`, which is the KeyError you see.
Three lines: a list comprehension over `cited`, an `if`, and a return of `("unknown_source", ", ".join(...))`.
