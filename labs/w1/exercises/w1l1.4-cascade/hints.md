# Hints: w1l1.4

## Hint 1

`kept` holds only the claims that passed so far, in reply order. So "derives from a claim not in `kept`" covers both
a rejected parent and a parent that comes later. `ids` holds every claim id in the reply; it tells those two cases
apart from an id the model made up.

## Hint 2

Collect the parents that are not in `kept`. If there are any, the reason is `bad_derivation`; the detail says
"derives from a rejected or later claim" when every missing parent is in `ids`, and "unknown claim id" otherwise.
The check belongs in the inference branch, before the value check that looks a parent up in `kept`.
