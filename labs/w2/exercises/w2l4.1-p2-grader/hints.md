# Hints: w2l4.1

## Hint 1

Two pieces. `every_thesis` collects the horizon of each thesis that fails `passes`, in the order the theses came;
an empty collection means 1.0 with no explanation, anything else means 0.0 and the horizons after "fails: ". The
grader is a class the `@grader` decorator puts in `GRADERS`: look at `Parsed` above it for the three class
attributes the registry reads, and keep the version a string.

## Hint 2

`grade` does no checking of its own. `built_theses(sample, expected)` gives the analysis and the theses (and raises
`CannotGrade` for you when there is nothing to grade: let it propagate). The source table is a dict from each
row's `source_id` to its `value`, over the second thing `snapshot_rows(analysis.snapshot)` returns. Then hand
`every_thesis` a one-line function of a thesis that calls `checks.p2_evidence_valid` with the analysis's claims.
