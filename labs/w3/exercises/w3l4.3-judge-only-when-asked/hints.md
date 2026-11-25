# Hints: w3l4.3

## Hint 1

Two places. In commands/grade.py, cmd_grade already has a judge_lines that handles the dry run and the empty list; it
needs calling, and only on one flag. In grade.py, render_judged's two outcome lines and its summary need the money.

## Hint 2

One judge call costs about half a cent, so two decimals print $0.01 for a call and four round it: the run files keep
six, and so does the output (`:.6f`). The not-judged line is paid too when the reply came back with no verdict.
