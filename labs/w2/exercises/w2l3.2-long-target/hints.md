# Hints: w2l3.2

## Hint 1

This is the stop rule turned around: keep the level prices strictly over the entry, and the next one is the
lowest of them. The target may reach that price plus half of the ATR passed in, and reaching it exactly passes.

## Hint 2

Name the allowance once from `TARGET_ALLOWANCE_ATR` and `atr14`, so the short side in w2l3.3 can reuse it. As
with the stop, the empty case goes first.
