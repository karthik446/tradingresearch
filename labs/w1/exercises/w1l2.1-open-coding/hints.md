# Hints: w1l2.1

## Hint 1

Work one analysis at a time: print its claims (`jq -c 'select(.item=="AAPL:2026-11-12") | .output_parsed.claims[]'
labs/w1/data/observe.jsonl`) and ask "what would a reader object to first?". That claim is `first_failure`. The
note says which claims and what is wrong, in your words. Leave `classes` empty; they come in w1l2.4.

## Hint 2

If the first claim the code rejects is an inference rejected as `bad_derivation`, look at its parents: the parent's
failure is the note. Do not stop at rejected claims: AMZN 2026-11-13 passes every check and still has c4 naming
sma_20 and sma_50 it never cited. `-` means clean (the author has one: KO 2026-11-13).
