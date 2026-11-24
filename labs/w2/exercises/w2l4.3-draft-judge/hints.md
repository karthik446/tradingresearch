# Hints: w2l4.3

## Hint 1

What does a report need to know about this grader before it reads a single score? The configs already name it, so
it needs that id. Then ask: who decides P1, a rule or a model? And has anyone checked this judge's verdicts against
outcomes yet? Each answer is a class attribute the registry or a report reads.

## Hint 2

What could a draft judge honestly return for the recorded AAPL reply? A 1.0 or a 0.0 would be counted in P1's
rate, and so would a 0.5. Look at how the graders above it say "I will not grade this sample" when there is nothing
they can read. Does the draft's answer depend on what the sample holds? A judge that refuses empty replies but scores
full ones fails, and so does one that tries a model first and catches the error.
