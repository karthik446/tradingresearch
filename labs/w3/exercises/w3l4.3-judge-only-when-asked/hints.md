# Hints: w3l4.3

## Hint 1

Two places. In commands/grade.py, the judge's part of `tr grade` already exists further down the file, with the dry run,
the empty queue and the cap --judge-max-usd sets: cmd_grade only has to reach it when the judge was asked for, and never
otherwise, whatever other option is given. In grade.py, render_judged's outcome lines and its summary need the money.

## Hint 2

One judge call costs about half a cent: two decimals print $0.01 for a call, and four print $0.0052, which is not what
the run file says. The run files keep six places, and so does the output: each line its own cost, and the last line
their sum, added up first and rounded once, or the microdollars the lines drop never reach the total. A fail is printed
as a fail with its reason, as a pass is, and the not-judged line is paid too when the reply came back with no verdict.
