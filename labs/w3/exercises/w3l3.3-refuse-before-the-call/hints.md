# Hints: w3l3.3

## Hint 1

label.labelable already decides who may be judged, the same rule `tr label` uses. What it raises is the wrong type for a
grader: catch it where it is called and raise the type every grader raises when it will not grade.

## Hint 2

Keep the refusal's own words: they say which rule refused and why, and the message of what p1_judge raises is what
`tr grade --judge` prints next to the thesis it could not judge.
