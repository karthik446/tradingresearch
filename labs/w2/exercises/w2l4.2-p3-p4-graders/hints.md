# Hints: w2l4.2

## Hint 1

Your P2 grader already scores a whole run. What changes when the check is P3 or P4 instead? Look at what each check
takes besides the thesis, and at which ids the configs give these two graders. A run whose first thesis fails and
whose second passes must still fail.

## Hint 2

Where does the close of a market_open entry come from: the recorded day, or the sample being graded? Picture the
same reply graded against an analysis whose snapshot closed at 349.0 instead of 352.78. Every number P3 and P4
compare belongs to that sample's snapshot, exactly as stored: an ATR of 8.0457 rounded to 8 moves P4's target
boundary.
