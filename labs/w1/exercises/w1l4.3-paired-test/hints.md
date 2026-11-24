# Hints: w1l4.3

## Hint 1

Pairing means one difference per item, so check `a.keys() == b.keys()` first. For a 0/1 metric a difference is +1,
0 or -1; McNemar uses only the +1s and -1s.

## Hint 2

Under "no difference", each discordant pair is a fair coin: `n = up + down`, and the two-sided p is
`min(1, 2 * sum(comb(n, k) for k in range(min(up, down) + 1)) / 2**n)`. (14, 0) gives 2 / 16384 = 0.000122.
