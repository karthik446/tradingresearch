# Hints: w4l1.3

## Hint 1

validate_claims checks a claim's number against the value it cites, and the fixed arm's table shows rounded values. If a tool hands back the unrounded number, a model that copies it exactly can still fail the check, and two arms disagree about one row. analyze.py already has the function the table uses to print a value.

## Hint 2

A row without its source_id cannot be cited at all, and a value without its unit is a bare number. For names, compare whole names, never prefixes or substrings, and when one is missing say which and list the ones there are, so the next call can be right.
