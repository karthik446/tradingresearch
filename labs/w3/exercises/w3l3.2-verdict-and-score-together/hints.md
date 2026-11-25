# Hints: w3l3.2

## Hint 1

Your p1_verdict already reads the reply, unknown and no-verdict included: let its CannotGrade reach the caller. Every
field the Score and its ScoreRecord need is already in scope in p1_judge: the judge, the sample and its spans, P1Judge,
JUDGE_MODEL. Each score gets a fresh id (`new_id`), and the reply text the Score keeps is the reply as it came back.

## Hint 2

The verdict and the ScoreRecord are one fact: both rows land or neither does. Look at which journal writes commit on
their own and which do not. A write that commits on its own ends a transaction: whatever was written before it lands
with it, whatever comes after it is on its own. Counterexample: the second write fails after the first committed, and
the journal holds a verdict with no score, a thesis w3l4.1 never queues again. The verdict row names the score id, too.
