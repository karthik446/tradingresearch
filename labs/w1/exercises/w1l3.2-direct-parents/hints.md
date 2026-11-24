# Hints: w1l3.2

## Hint 1

For each inference, two sets: `allowed` (every name its parents cite; `cited(parent)` already gives one parent's)
and `used` (vocab names found in text + steps). Anything in `used - allowed` is ungrounded.

## Hint 2

`allowed = set().union(*(cited(parent) for parent in claim.get("derived_from") or []))`, then after `used`:
`if extra := sorted(used - allowed): ungrounded.append(f"{claim_id}: {', '.join(extra)}")`.
