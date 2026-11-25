# Hints: w5l4.1

## Hint 1

The embargo keeps the sessions just before the cutoff out of both sets, because a thesis written on one of them can
still be open when the test period starts. Count how far one thesis reaches: the sessions it may wait for its entry,
plus the longest it may hold after entering. Both numbers already exist in the code base; the floor is their sum.

## Hint 2

HOLD_RANGE maps each horizon to its (shortest, longest) hold, so the longest hold of all is the largest second value.
The swing window lets a thesis enter on either of the two sessions after it is written. Build the reason string from
the same two numbers, so the floor and the words that explain it cannot drift apart.
