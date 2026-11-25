# Hints: w5l4.3

## Hint 1

A split is only honest if it was written down before its test period began. Ask, in order: is the embargo long enough
for the longest trade, is the cutoff a day the exchange opens, has that day not already happened, and has its open
not already passed, for the clock and for the pre-registration. The first broken rule is the reason given.

## Hint 2

The record itself refuses a short embargo with a pydantic error, so the refusal has to come before a TrainingSplit is
built. `sessions` already knows the calendar, the last completed session at a given time, and each session's open in
UTC. A split already stored was honest when it was stored, so look it up before the clock checks.
