# Hints: w1l1.2

## Hint 1

Do not write a regex for "a digit that is not in a date or a name". `ALLOWED_DIGITS` already matches the three
allowed forms. Take its matches out of the text and the rule becomes "any digit left is a number in text".

## Hint 2

Put this check first: a claim with a number in its prose is rejected for that, whatever else is wrong with it.
The detail is the start of the text, so a reader can see the number.
