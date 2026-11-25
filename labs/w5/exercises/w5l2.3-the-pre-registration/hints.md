# Hints: w5l2.3

## Hint 1

A pre-registration fixes, before any result exists, what will be measured and what result means what. Here that is
three things: the one metric that decides, the one that must not get worse, and a rule that turns the decided
metric's interval into a verdict for each dropped section. Write them where anyone opening the config reads them
first, as comments above the first setting.

## Hint 2

Pick the primary metric by asking which grader can move: last week the all-or-nothing score sat at its floor in both
arms, while the per-claim rate had room on both sides. The guard is the plainest one, the share of replies that
parsed. The rule needs both verdicts: when the section stays (the interval sits wholly on the losing side of zero)
and when it goes (it does not, the guard holds, and the prompt gets cheaper). Each item starts on its own comment line
with its label, colon included.
