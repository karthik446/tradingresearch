# Hints: w1l3.3

## Hint 1

An inference cites no sources itself; what it can name comes from its own parents. So `cited(c2)` for an inference
`c2` is what c2's parents cite, which is a recursive call. `seen` stops a claim that (wrongly) derives from itself.

## Hint 2

Inside `cited`, before `return found`:
`for parent in claim.get("derived_from") or []: found |= cited(parent, seen | {claim_id})`.
