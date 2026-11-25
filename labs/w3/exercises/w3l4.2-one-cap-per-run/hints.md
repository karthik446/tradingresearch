# Hints: w3l4.2

## Hint 1

The cap belongs to the run, so each call may use only what the run has left: the cap minus everything spent so far,
not minus the last call alone. Under a $0.05 cap two recorded calls fit (about $0.040 is left after them, below the
$0.043 worst case), a third does not. The loop already skips every thesis once the cap is spent; your part says when
that happens.

## Hint 2

Not every failure means the same thing. The cap that cannot cover a call ends the paid part of the run; anything else
(a reply with no verdict, a failed call, bars that would not load) belongs to that one thesis. If the broad case is
handled first, the cap is never noticed and every later thesis tries anyway. As for cost: a thesis spent what the run
files written during its own call say, all of them, and a thesis that made no call spent nothing.
