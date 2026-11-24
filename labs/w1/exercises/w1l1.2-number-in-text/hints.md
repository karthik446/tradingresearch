# Hints: w1l1.2

## Hint 1

Do not write a regex for "a digit that is not in a date or a name". `ALLOWED_DIGITS` already matches the three
allowed forms; delete its matches with `.sub("", text)` and the rule becomes "any digit left is a number in text".

## Hint 2

`re.search(r"\d", ALLOWED_DIGITS.sub("", text))`, and return `("number_in_text", text[:120])`. Put it first: a claim
with a number in its prose is rejected for that, whatever else is wrong with it.
