# Hints: w3l1.2

## Hint 1

An unknown is not a third verdict: the journal's verdict column takes only pass or fail. It is stored as fail, and the
reason's prefix is what marks it as an abstain. The journal's abstain test looks for exactly lower-case unknown: at the
very start of the reason, nothing else.

## Hint 2

Decide from the verdict, never from words in the reply: a pass whose text mentions the rubric's Unknown section is still
a pass. Put the prefix in front only when the explanation does not already begin with it; an explanation that begins
with unknown: and no space is already marked, one that begins with a capital U is not, and neither is one that begins
with spaces. The explanation is kept as the judge wrote it, spaces and newlines included.
