# Hints: w3l2.2

## Hint 1

The judge's evidence is what the thesis cited and what code measured after the trade, nothing else. label.py already
writes both, the same lines the operator reads: the claims a thesis cites from its own analysis (which you fetch from
the journal by the thesis's analysis id), and the post-trade summary from the grade. The bars stay out.

## Hint 2

Two groups, each under its own heading line, with one empty line between them; the heading texts are in the INPUT block
of labs/w3/data/judge_request.json. Show the claims the thesis cites, not every claim of its analysis, and all of them
however many: the check judges a second thesis that cites only one of the two, and a third that cites three, the last an
inference whose steps label.py writes too.
