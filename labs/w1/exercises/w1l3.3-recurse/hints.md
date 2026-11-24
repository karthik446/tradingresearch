# Hints: w1l3.3

## Hint 1

An inference cites no sources itself; what it can name comes from its own parents. So `cited(c2)` for an inference
`c2` is what c2's parents cite, which is a recursive call. `seen` stops a claim that (wrongly) derives from itself.

## Hint 2

The recursion goes inside `cited`, after the claim's own sources are collected and before it returns: add what
each parent cites. Pass `seen` with the current claim added, so a loop stops.
