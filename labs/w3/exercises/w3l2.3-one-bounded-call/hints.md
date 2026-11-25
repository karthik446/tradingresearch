# Hints: w3l2.3

## Hint 1

Two bounds, each one argument away. The reply bound is a field of the call settings, and ADR-003's constant for it is at
the top of evals.py. The money cap is a field of the budget, next to the price table p1_judge is already given. Keeping
the run is part B's; leave the NotImplementedError as it is.

## Hint 2

The cap is the max_usd the caller passed, unchanged: no margin, no rounding, no slack, and no ceiling of your own. The
check sits a twentieth of a cent, a thousandth of a cent, then a microdollar either side of the budget's estimate of one
call's worst case and expects a send on one side and a refusal on the other; at twice the recorded prices it expects a
$0.10 cap to send. Use the provider and the prices you are given; a client or a price lookup of your own reaches for
the network, which the labs block.
