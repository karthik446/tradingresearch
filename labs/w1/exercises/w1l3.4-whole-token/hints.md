# Hints: w1l3.4

## Hint 1

`"sma_20" in "sma_200"` is True. Match the name only where the character before and after it cannot be part of a
name: a letter, a digit or `_`. `\b` is not the same: it needs a word character on one side of it, so after a name
that ends in a `)`, such as `rsi_14(close)`, followed by a space or a full stop, it never matches. Test the characters
around the name, not a word boundary.

## Hint 2

A negative lookbehind and a negative lookahead for those characters, around the escaped name (`re.escape`),
do it. Search the words with that pattern where the plain `in` test was.
