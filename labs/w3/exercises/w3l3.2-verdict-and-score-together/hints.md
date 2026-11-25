# Hints: w3l3.2

## Hint 1

The verdict is read from the reply the sample holds, the way lab w3l1 reads it, unknown and no-verdict included: a reply
that cannot be read raises CannotGrade, and that must reach the caller, not become a stored fail. Every field the Score
and its ScoreRecord need is already in scope in p1_judge: the judge, the sample and its spans, P1Judge, the judge model.
Each score gets a fresh id, made the way the journal's other records get theirs, and the Score's note keeps the calls
the spans record, as they are: the reply as it came back, the request digest with it. Every verdict gets the same note
and the same record, pass, fail or unknown.

## Hint 2

The verdict and the ScoreRecord are one fact: both rows land or neither does. Look at which journal writes commit on
their own and which do not. A write that commits on its own ends a transaction: whatever was written before it lands
with it, whatever comes after it is on its own. Counterexample: the second write fails after the first committed, and
the journal holds a verdict with no score, a thesis w3l4.1 never queues again. The verdict row names the score id, too.
