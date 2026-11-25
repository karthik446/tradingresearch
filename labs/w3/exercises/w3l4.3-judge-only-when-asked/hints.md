# Hints: w3l4.3

## Hint 1

Two places. In commands/grade.py, cmd_grade already has a helper for the judge's lines (`judge_lines`) that handles the
dry run and the empty queue: it runs only when --judge is given, under the cap --judge-max-usd sets, and a dry run
neither calls the judge nor looks anything up. In grade.py, render_judged's outcome lines and its summary need the money.

## Hint 2

One judge call costs about half a cent: two decimals print $0.01 for a call and four round it away. The run files keep
six places, and so does the output. A fail is printed as a fail, and the not-judged line is paid too when the reply came
back with no verdict.
