# Hints: w1l4.3

## Hint 1

Pairing means one difference per item, so check that both sides have the same items first. For a 0/1 metric a
difference is +1, 0 or -1; McNemar uses only the +1s and -1s.

## Hint 2

Under "no difference", each discordant pair is a fair coin toss. With n discordant pairs, the chance of exactly k of
them going one way is C(n, k) / 2^n, where C(n, k) counts the ways to pick k of n (`math.comb`). The two-sided p is
twice the chance of a count at most as extreme as the smaller of the two, capped at 1. Work a small case by hand, such
as (2, 0), and check your function gives the same.
