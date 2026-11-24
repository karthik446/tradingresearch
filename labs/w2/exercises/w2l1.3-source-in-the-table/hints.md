# Hints: w2l1.3

## Hint 1

`values` maps source id to value; "in the table" means a key of `values`, whatever it holds (a label row holds None
and still counts). Look at every id in `claim.source_ids`.

## Hint 2

Two steps, in this order: an inference returns True straight away (rules 3 and 4 judge facts); then one cited id
missing from the keys is enough to fail. A fact with no value still goes through this check.
