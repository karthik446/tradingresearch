# Hints: w1l3.4

## Hint 1

`"sma_20" in "sma_200"` is True. Match the name only where the character before and after it cannot be part of a
name: a letter, a digit or `_`. (`\b` gives the same here because `_` is a word character; the author spells the
class out so the rule reads like the spec.)

## Hint 2

A negative lookbehind and a negative lookahead for those characters, around the escaped name (`re.escape`),
do it. Search the words with that pattern where the plain `in` test was.
