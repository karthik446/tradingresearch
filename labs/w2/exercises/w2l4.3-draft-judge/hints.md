# Hints: w2l4.3

## Hint 1

The judge is registered like the code graders, with the id the configs use (`p1_judge`), but its kind says a
model decides, and one more class attribute, `validated`, says nobody has checked its verdicts yet.

## Hint 2

`grade` never looks at the sample and never builds a client: its only line raises `CannotGrade`, with a reason
that contains the word "draft" and says when the judge will run (on closed trades, in week 3).
