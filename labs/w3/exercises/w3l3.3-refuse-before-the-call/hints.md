# Hints: w3l3.3

## Hint 1

Who may be judged is already decided in the repo, by the rule `tr label` uses: a teacher thesis, or one with no Grade
yet, is refused with a reason, before the thesis is even read for the prompt. That refusal arrives as an error of its
own type, one a grader's caller does not know; what every grader raises when it will not grade is CannotGrade. Only the
refusal becomes a CannotGrade. A storage error, a file that will not read or a record that will not parse (a ValueError,
a LookupError) says nothing about the thesis, and reaches the caller as it is.

## Hint 2

Keep the refusal's own words: they say which rule refused and why, and the message of what p1_judge raises is what
`tr grade --judge` prints next to the thesis it could not judge.
