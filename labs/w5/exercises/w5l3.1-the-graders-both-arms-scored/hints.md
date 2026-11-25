# Hints: w5l3.1

## Hint 1

Core refuses a whole comparison when one grader it is handed has no score in a run, or has scores on no item the
other run scored. A drop arm never cites its dropped section, so its grader is missing there. Decide grader by grader,
before core sees any of them, which ones it can compare, and hand core only those.

## Hint 2

`Run.values(grader)` maps item id to score, and is empty for a grader the run never scored. A grader can be compared
when the two mappings share at least one key; a score of 0.0 is still a score. Core reads an empty list of graders as
every grader both runs scored, so an empty kept list must refuse before core is called.
