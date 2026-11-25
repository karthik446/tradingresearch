# Hints: w5l4.4

## Hint 1

The embargo is counted in sessions the exchange opens, not in calendar days or weekdays: a holiday inside the window
pushes its first session one day further back. The window ends the session before the cutoff, never on the cutoff.
Once its first session is known, every journal day falls in exactly one place, by comparing it with two dates: that
first session and the cutoff.

## Hint 2

`sessions` already counts sessions back from a given session, oldest first, and finds the session before a day. The
window comes from the calendar alone; the journal only decides which of its days land in each set. The journal may
hold a day twice or out of order, so make its days distinct and put them in date order before you split them.
