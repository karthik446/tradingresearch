# Hints: w3l1.1

## Hint 1

The rubric's Verdict format puts the answer in the last JSON object of the reply, and the judge may think aloud, quote
the format example or try a draft verdict before it. Searching the text yourself for braces or for the key goes wrong on
exactly those replies. The judge library evals.py already imports has a reader for the last top-level object; use it.

## Hint 2

The verdict and the explanation are two separate questions to that reader. The reason you return is stored as text in a
NOT NULL column, so anything that is not a string (no explanation, null, a list) becomes the empty string, not its
printed form.
