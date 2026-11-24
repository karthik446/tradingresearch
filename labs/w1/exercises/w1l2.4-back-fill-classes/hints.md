# Hints: w1l2.4

## Hint 1

For `backfill_todo`: `unlabelled` and `unknown` need only your two files. For `code`, let `code_classes` be the
judge: a class the code finds that the row lacks is `+`, a window_name or label_in_value the row lists that the code
does not find is `-`. `cascade` goes one way only, since a reader may see a cascade the code cannot (NVDA 11-12).
For `counts`, set `class_counts` of your labels next to each table row's Analyses.

## Hint 2

For the column: go down `labels.csv` and, for each note, list every class it shows, `;`-separated, with the names
in your table. Add `cascade` when the analysis has a `bad_derivation` rejection. Then run the observe (`check`) and
work through what it lists: either a note is missing a class or the table's count was a guess.
