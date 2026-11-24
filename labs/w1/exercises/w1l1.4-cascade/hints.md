# Hints: w1l1.4

## Hint 1

`kept` holds only the claims that passed so far, in reply order. So "derives from a claim not in `kept`" covers both
a rejected parent and a parent that comes later. `ids` holds every claim id in the reply; it tells those two cases
apart from an id the model made up.

## Hint 2

`missing = [d for d in item.get("derived_from") or [] if d not in kept]`. If it is not empty, the reason is
`bad_derivation`, and the detail starts "derives from a rejected or later claim" when `all(d in ids for d in
missing)`, else "unknown claim id". It goes inside `if tag == "inference":`, before the value check that reads
`kept[d]`.
