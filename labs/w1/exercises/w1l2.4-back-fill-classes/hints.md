# Hints: w1l2.4

## Hint 1

Go down `labels.csv` and, for each note, list every class it shows, `;`-separated, using the names in your table.
Add `cascade` after the classes when the analysis has a `bad_derivation` rejection.

## Hint 2

Run `uv run python -m tradingresearch.taxonomy evals/labels.csv` and put its counts next to your table's Analyses
column. Where they differ, either a note is missing a class or the table's count was a guess: fix the one that is
wrong.
