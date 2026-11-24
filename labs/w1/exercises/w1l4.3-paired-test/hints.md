# Hints: w1l4.3

## Hint 1

Pairing means one difference per item, so check that both sides have the same items first. For a 0/1 metric a
difference is +1, 0 or -1; McNemar uses only the +1s and -1s.

## Hint 2

Under "no difference", each discordant pair is a fair coin toss. Ask how surprising the observed split is if the
coin is fair, counting every split at least as lopsided, on either side. Work (2, 0) by hand: both coins land
"variant" with chance 1/4, and the split just as lopsided the other way has 1/4 too, so p = 0.5. Then (1, 1): one each
way is the least lopsided split there is, so what can p be at most? Does your p change when you swap the two counts?
It should not.
